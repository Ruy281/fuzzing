import sys
import asyncio
from urllib.parse import urlparse, urlunparse, urljoin

from playwright.async_api import async_playwright
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QLineEdit, QTextEdit, QLabel, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QSplitter,
)
from PyQt5.QtCore import Qt

# Các đuôi file tĩnh, không cần quét
STATIC_EXT = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".css", ".js", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".rar", ".7z", ".gz", ".mp3", ".mp4", ".avi", ".mov",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


def normalize_url(url: str):
    """Chuẩn hoá URL để tránh quét trùng. Trả về None nếu URL không hợp lệ/không cần quét.

    - Chỉ nhận http/https
    - Hạ chữ thường scheme + host
    - Bỏ fragment thường (#section), NHƯNG giữ hash-route của SPA (#/login, #!/x)
    - Bỏ dấu "/" thừa ở cuối path
    - Bỏ file tĩnh
    """
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


# --- THREAD CHẠY NGẦM: 1 event loop asyncio, nhiều tab ---
class CrawlerThread(QThread):
    log = pyqtSignal(str)               # tin nhắn log
    url_found = pyqtSignal(str, int)    # (url, depth) khi phát hiện URL mới
    progress = pyqtSignal(int, int)     # (đã quét, đã phát hiện)

    def __init__(self, start_url: str, max_depth: int, num_workers: int, max_pages: int):
        super().__init__()
        self.start_url = start_url
        self.max_depth = max_depth
        self.num_workers = num_workers
        self.max_pages = max_pages
        self.is_running = True

    def stop(self):
        self.is_running = False

    # ---- điểm vào của QThread ----
    def run(self):
        try:
            asyncio.run(self.crawl())
        except Exception as e:
            self.log.emit(f"<span style='color:red;'>[-] Lỗi nghiêm trọng: {e}</span>"
                          f"<br><i>(Đã chạy 'playwright install chromium' chưa?)</i>")
        self.log.emit("<b style='color:green;'>[*] Đã dừng quét.</b>")

    # ---- điều phối ----
    async def crawl(self):
        target = self.start_url
        if not target.startswith("http"):
            target = "http://" + target

        target = normalize_url(target)
        if target is None:
            self.log.emit("<span style='color:red;'>[-] URL không hợp lệ.</span>")
            return

        self.base_domain = urlparse(target).netloc
        self.queue = asyncio.Queue()
        self.visited = {target}
        self.scanned = 0

        self.url_found.emit(target, 0)
        await self.queue.put((target, 0))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            # Một context dùng chung -> các tab chia sẻ cookie/phiên
            context = await browser.new_context()

            workers = [
                asyncio.create_task(self.worker(context, i + 1))
                for i in range(self.num_workers)
            ]
            join_task = asyncio.create_task(self.queue.join())

            # Chờ hết việc, hoặc người dùng bấm Dừng
            while not join_task.done() and self.is_running:
                await asyncio.sleep(0.2)

            join_task.cancel()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

            await context.close()
            await browser.close()

    # ---- worker: mỗi worker một tab ----
    async def worker(self, context, wid: int):
        page = await context.new_page()
        try:
            while True:
                url, depth = await self.queue.get()
                try:
                    if self.is_running:
                        await self.process(page, url, depth, wid)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    msg = str(e).splitlines()[0] if str(e) else type(e).__name__
                    self.log.emit(f"<span style='color:red;'>[-] W{wid} lỗi {url}: {msg}</span>")
                finally:
                    # BẮT BUỘC có, nếu thiếu thì queue.join() treo vĩnh viễn
                    self.queue.task_done()
        except asyncio.CancelledError:
            pass

    # ---- xử lý một URL ----
    async def process(self, page, url: str, depth: int, wid: int):
        self.scanned += 1
        self.progress.emit(self.scanned, len(self.visited))
        self.log.emit(f"[W{wid}] (Depth {depth}) {url}")

        await page.goto(url, timeout=15000, wait_until="domcontentloaded")

        # Đợi SPA render link (không báo lỗi nếu trang không có thẻ <a>)
        try:
            await page.wait_for_selector("a[href]", timeout=3000)
        except Exception:
            pass
        await page.wait_for_timeout(500)

        if depth >= self.max_depth:
            return

        # Lấy toàn bộ href tuyệt đối trong 1 lần gọi
        hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")

        for href in hrefs:
            full_url = normalize_url(urljoin(url, href))
            if full_url is None:
                continue
            if urlparse(full_url).netloc != self.base_domain:
                continue
            if full_url in self.visited:
                continue
            if len(self.visited) >= self.max_pages:
                return  # đã đủ số trang tối đa

            # Không có await giữa lúc kiểm tra và add -> an toàn, không cần lock
            self.visited.add(full_url)
            self.url_found.emit(full_url, depth + 1)
            await self.queue.put((full_url, depth + 1))

        self.progress.emit(self.scanned, len(self.visited))


# --- GIAO DIỆN ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web URL Crawler (Async, hỗ trợ SPA)")
        self.resize(900, 600)
        self.crawler_thread = None

        # Hàng nhập liệu
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Nhập URL (VD: http://localhost:3000/#/)")

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(0, 10)
        self.depth_spin.setValue(2)

        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 10)
        self.worker_spin.setValue(4)

        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 100000)
        self.max_pages_spin.setValue(500)

        self.btn_start = QPushButton("Bắt đầu")
        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setEnabled(False)

        top = QHBoxLayout()
        top.addWidget(QLabel("URL:"))
        top.addWidget(self.url_input, 1)
        top.addWidget(QLabel("Depth:"))
        top.addWidget(self.depth_spin)
        top.addWidget(QLabel("Tab:"))
        top.addWidget(self.worker_spin)
        top.addWidget(QLabel("Tối đa:"))
        top.addWidget(self.max_pages_spin)
        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)

        # Bảng kết quả + log
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Depth", "URL"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.log_box)
        splitter.setSizes([380, 200])

        # Hàng dưới: tiến độ + xuất file
        self.status_label = QLabel("Đã quét: 0 | Đã phát hiện: 0")
        self.btn_export = QPushButton("Xuất danh sách URL")
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
        self.btn_export.clicked.connect(self.export_urls)

    # ---- điều khiển ----
    def start_crawler(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_box.append("<span style='color:red;'>Vui lòng nhập URL!</span>")
            return

        self.table.setRowCount(0)
        self.log_box.clear()
        self.status_label.setText("Đã quét: 0 | Đã phát hiện: 0")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        depth = self.depth_spin.value()
        workers = self.worker_spin.value()
        self.log_box.append(f"<b>Bắt đầu: {url} | depth={depth} | {workers} tab</b>")

        self.crawler_thread = CrawlerThread(url, depth, workers, self.max_pages_spin.value())
        self.crawler_thread.log.connect(self.log_box.append)
        self.crawler_thread.url_found.connect(self.add_url)
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

    # ---- cập nhật giao diện ----
    def add_url(self, url: str, depth: int):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(depth)))
        self.table.setItem(row, 1, QTableWidgetItem(url))

    def update_progress(self, scanned: int, found: int):
        self.status_label.setText(f"Đã quét: {scanned} | Đã phát hiện: {found}")

    def export_urls(self):
        if self.table.rowCount() == 0:
            self.log_box.append("<span style='color:red;'>Chưa có URL để xuất.</span>")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu danh sách URL", "urls.txt", "Text (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for r in range(self.table.rowCount()):
                f.write(self.table.item(r, 1).text() + "\n")
        self.log_box.append(f"<b>Đã lưu {self.table.rowCount()} URL vào {path}</b>")

    # ---- đóng cửa sổ an toàn ----
    def closeEvent(self, event):
        if self.crawler_thread and self.crawler_thread.isRunning():
            self.crawler_thread.stop()
            self.crawler_thread.wait(10000)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
