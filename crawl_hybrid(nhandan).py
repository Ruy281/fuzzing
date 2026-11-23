import sys
import json
import queue
import asyncio
import threading
from urllib.parse import urlparse, urlunparse, urljoin

from playwright.async_api import async_playwright
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QLineEdit, QTextEdit, QLabel, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QSplitter,
)

from target_analyzer import TargetAnalyzer, Target

STATIC_EXT = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".css", ".js", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".rar", ".7z", ".gz", ".mp3", ".mp4", ".avi", ".mov",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)

# Loại tài nguyên bị chặn để trang tải nhanh hơn (không ảnh hưởng việc lấy link)
BLOCKED_RESOURCES = {"image", "media", "font", "stylesheet"}


def normalize_url(url: str):
    """Chuẩn hoá URL; trả về None nếu không hợp lệ hoặc là file tĩnh.
    Giữ hash-route của SPA (#/login, #!/x), bỏ fragment thường (#section)."""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None

    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if path.lower().endswith(STATIC_EXT):
        return None

    fragment = p.fragment if p.fragment.startswith(("/", "!")) else ""
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, p.params, p.query, fragment))


class CrawlerThread(QThread):
    """Điều phối: tạo K thread con, mỗi thread chạy 1 event loop asyncio riêng
    với 1 Chromium và M tab. Dữ liệu dùng chung được bảo vệ bằng Lock."""

    log = pyqtSignal(str)
    target_classified = pyqtSignal(int, object)  # (depth, Target)
    progress = pyqtSignal(int, int)

    def __init__(self, start_url, max_depth, num_browsers, tabs_per_browser, max_pages):
        super().__init__()
        self.start_url = start_url
        self.max_depth = max_depth
        self.num_browsers = num_browsers
        self.tabs_per_browser = tabs_per_browser
        self.max_pages = max_pages
        self.is_running = True
        self.analyzer = TargetAnalyzer()
        self.targets: list[Target] = []

    def stop(self):
        self.is_running = False

    # ---------- điều phối ----------
    def run(self):
        target = self.start_url
        if not target.startswith("http"):
            target = "http://" + target
        target = normalize_url(target)
        if target is None:
            self.log.emit("<span style='color:red;'>[-] URL không hợp lệ.</span>")
            return

        self.base_domain = urlparse(target).netloc

        # --- trạng thái dùng chung giữa các thread ---
        self.q = queue.Queue()          # thread-safe
        self.lock = threading.Lock()    # bảo vệ visited / pending / scanned / targets
        self.visited = {target}
        self.pending = 1                # số việc đang chờ + đang xử lý
        self.scanned = 0
        self.targets = []

        self.q.put((target, 0))

        threads = [
            threading.Thread(target=self._thread_main, args=(i + 1,), daemon=True)
            for i in range(self.num_browsers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.log.emit(
            f"<b style='color:green;'>[*] Đã dừng quét. Tổng cộng {len(self.targets)} target được phân loại.</b>"
        )

    # ---------- mỗi thread con: 1 event loop ----------
    def _thread_main(self, bid: int):
        try:
            asyncio.run(self._engine(bid))
        except Exception as e:
            self.log.emit(
                f"<span style='color:red;'>[-] Browser {bid} lỗi: {e}</span>"
                f"<br><i>(Đã chạy 'playwright install chromium' chưa?)</i>"
            )

    async def _engine(self, bid: int):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.route("**/*", self._route_handler)

            tasks = [
                asyncio.create_task(self._worker(context, f"{bid}.{i + 1}"))
                for i in range(self.tabs_per_browser)
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            await context.close()
            await browser.close()

    @staticmethod
    async def _route_handler(route):
        if route.request.resource_type in BLOCKED_RESOURCES:
            await route.abort()
        else:
            await route.continue_()

    # ---------- worker: 1 tab ----------
    async def _worker(self, context, wid: str):
        page = await context.new_page()
        try:
            while self.is_running:
                try:
                    url, depth = self.q.get_nowait()
                except queue.Empty:
                    with self.lock:
                        if self.pending == 0:
                            break
                    await asyncio.sleep(0.05)
                    continue

                try:
                    await self._process(page, url, depth, wid)
                except Exception as e:
                    msg = str(e).splitlines()[0] if str(e) else type(e).__name__
                    self.log.emit(f"<span style='color:red;'>[-] W{wid} lỗi {url}: {msg}</span>")
                finally:
                    with self.lock:
                        self.pending -= 1
        finally:
            await page.close()

    # ---------- xử lý 1 URL ----------
    async def _process(self, page, url: str, depth: int, wid: str):
        with self.lock:
            self.scanned += 1
            scanned, found = self.scanned, len(self.visited)
        self.progress.emit(scanned, found)
        self.log.emit(f"[W{wid}] (Depth {depth}) {url}")

        await page.goto(url, timeout=15000, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector("a[href]", timeout=3000)
        except Exception:
            pass
        await page.wait_for_timeout(300)

        # Tạo danh sách đối tượng Target (mỗi vị trí đầu vào = 1 Target với 1 nhãn dán)
        page_targets = await self.analyzer.analyze_page(page, url)
        if page_targets:
            with self.lock:
                self.targets.extend(page_targets)
            for target_obj in page_targets:
                self.target_classified.emit(depth, target_obj)

        if depth >= self.max_depth:
            return

        hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")

        for href in hrefs:
            full_url = normalize_url(urljoin(url, href))
            if full_url is None or urlparse(full_url).netloc != self.base_domain:
                continue

            with self.lock:
                if full_url in self.visited:
                    continue
                if len(self.visited) >= self.max_pages:
                    break
                self.visited.add(full_url)
                self.pending += 1
                found = len(self.visited)

            self.q.put((full_url, depth + 1))
            self.progress.emit(self.scanned, found)


# ---------------- GIAO DIỆN ----------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web URL Crawler & Target Classifier (Thread + Async)")
        self.resize(1100, 620)
        self.crawler_thread = None
        self.collected_targets: list[Target] = []

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Nhập URL (VD: http://localhost:3000/#/)")

        self.depth_spin = self._spin(0, 10, 2)
        self.browser_spin = self._spin(1, 6, 2)
        self.tab_spin = self._spin(1, 10, 3)
        self.max_pages_spin = self._spin(1, 100000, 500)

        self.btn_start = QPushButton("Bắt đầu")
        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setEnabled(False)

        top = QHBoxLayout()
        top.addWidget(QLabel("URL:"))
        top.addWidget(self.url_input, 1)
        for text, w in (("Depth:", self.depth_spin), ("Browser:", self.browser_spin),
                        ("Tab/browser:", self.tab_spin), ("Tối đa:", self.max_pages_spin)):
            top.addWidget(QLabel(text))
            top.addWidget(w)
        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Depth", "URL", "Nhãn dán", "Vị trí chi tiết"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.log_box)
        splitter.setSizes([380, 200])

        self.status_label = QLabel("Đã quét: 0 | URL phát hiện: 0 | Target tạo: 0")
        self.btn_export = QPushButton("Xuất danh sách Target (JSON)")
        bottom = QHBoxLayout()
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.btn_export)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.btn_start.clicked.connect(self.start_crawler)
        self.btn_stop.clicked.connect(self.stop_crawler)
        self.btn_export.clicked.connect(self.export_targets)

    @staticmethod
    def _spin(lo, hi, val):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def start_crawler(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_box.append("<span style='color:red;'>Vui lòng nhập URL!</span>")
            return

        self.table.setRowCount(0)
        self.collected_targets.clear()
        self.log_box.clear()
        self.status_label.setText("Đã quét: 0 | URL phát hiện: 0 | Target tạo: 0")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        nb, nt = self.browser_spin.value(), self.tab_spin.value()
        self.log_box.append(
            f"<b>Bắt đầu: {url} | depth={self.depth_spin.value()} | "
            f"{nb} browser x {nt} tab = {nb * nt} luồng song song</b>"
        )

        self.crawler_thread = CrawlerThread(
            url, self.depth_spin.value(), nb, nt, self.max_pages_spin.value()
        )
        self.crawler_thread.log.connect(self.log_box.append)
        self.crawler_thread.target_classified.connect(self.add_target)
        self.crawler_thread.progress.connect(self.update_progress)
        self.crawler_thread.finished.connect(self.on_finished)
        self.crawler_thread.start()

    def stop_crawler(self):
        if self.crawler_thread and self.crawler_thread.isRunning():
            self.crawler_thread.stop()
            self.btn_stop.setEnabled(False)
            self.log_box.append("<i>Đang dừng, vui lòng đợi các tab hoàn tất...</i>")

    def on_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def add_target(self, depth: int, target: Target):
        self.collected_targets.append(target)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(depth)))
        self.table.setItem(row, 1, QTableWidgetItem(target.url))
        self.table.setItem(row, 2, QTableWidgetItem(target.label))
        detail_str = json.dumps(target.detail, ensure_ascii=False)
        self.table.setItem(row, 3, QTableWidgetItem(detail_str))
        self.status_label.setText(
            f"Đã quét: {self.crawler_thread.scanned} | "
            f"URL phát hiện: {len(self.crawler_thread.visited)} | "
            f"Target tạo: {len(self.collected_targets)}"
        )

    def update_progress(self, scanned: int, found: int):
        self.status_label.setText(
            f"Đã quét: {scanned} | URL phát hiện: {found} | Target tạo: {len(self.collected_targets)}"
        )

    def export_targets(self):
        if not self.collected_targets:
            self.log_box.append("<span style='color:red;'>Chưa có Target để xuất.</span>")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu danh sách Target", "targets.json", "JSON (*.json)")
        if not path:
            return
        data = [t.to_dict() for t in self.collected_targets]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        self.log_box.append(f"<b>Đã lưu {len(self.collected_targets)} Target vào {path}</b>")

    def closeEvent(self, event):
        if self.crawler_thread and self.crawler_thread.isRunning():
            self.crawler_thread.stop()
            self.crawler_thread.wait(15000)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
