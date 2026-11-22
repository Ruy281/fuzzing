import sys
from urllib.parse import urlparse, urljoin
from collections import deque
from playwright.sync_api import sync_playwright

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLineEdit, QTextEdit, QLabel, QHBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal

# --- LỚP THREAD ĐỂ CHẠY NGẦM (Đã đổi sang Playwright) ---
class CrawlerThread(QThread):
    tin_nhan = pyqtSignal(str)
    tim_thay_link_co_tham_so = pyqtSignal(str)
    tim_thay_link_full = pyqtSignal(str)

    def __init__(self, start_url: str, max_depth: int):
        super().__init__()
        self.start_url = start_url
        self.max_depth = max_depth
        self.is_running = True

    def run(self):
        target = self.start_url
        if not target.startswith("http"):
            target = "http://" + target

        base_domain = urlparse(target).netloc
        queue = deque([(target, 0)])
        visited = set([target])

        # Khởi tạo trình duyệt ẩn 1 lần duy nhất
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True) # headless=False nếu muốn nhìn thấy trình duyệt chạy
            page = browser.new_page()

            while queue and self.is_running:
                url, depth = queue.popleft()

                if depth > self.max_depth:
                    continue

                self.tin_nhan.emit(f"[*] Đang quét (Depth {depth}): {url}")

                try:
                    # Dùng Playwright để truy cập và ĐỢI Javascript render xong
                    page.goto(url, timeout=5000, wait_until="networkidle")
                    
                    # Kiểm tra tham số URL
                    parsed = urlparse(url)
                    if parsed.query:
                        self.tin_nhan.emit(f"<b style='color:blue;'>[+] MỤC TIÊU CÓ THAM SỐ: {url}</b>")
                        self.tim_thay_link_co_tham_so.emit(url)

                    if depth < self.max_depth:
                        # Lấy tất cả thẻ <a> trên trang
                        elements = page.locator("a").all()
                        for el in elements:
                            href = el.get_attribute("href")
                            if not href:
                                continue
                            
                            full_url = urljoin(url, href)
                            
                            # Giới hạn tên miền (localhost:3000)
                            if urlparse(full_url).netloc == base_domain:
                                if full_url not in visited:
                                    self.tim_thay_link_full.emit(full_url)
                                    visited.add(full_url)
                                    queue.append((full_url, depth + 1))

                except Exception as e:
                    self.tin_nhan.emit(f"<span style='color:red;'>[-] Lỗi (hoặc Timeout): {url}</span>")
                    continue
            
            # Đóng trình duyệt khi xong
            browser.close()
        
        self.tin_nhan.emit("<b style='color:green;'>[*] Đã dừng quét.</b>")

    def stop(self):
        self.is_running = False


# --- LỚP GIAO DIỆN CHÍNH (Giữ nguyên) ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web Crawler Tool (Hỗ trợ SPA)")
        self.resize(700, 500)

        layout = QVBoxLayout()
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Nhập URL (VD: http://localhost:3000/#/)")
        self.depth_input = QLineEdit()
        self.depth_input.setPlaceholderText("Độ sâu (VD: 1)")
        self.depth_input.setFixedWidth(100)
        
        self.btn_start = QPushButton("Bắt đầu")
        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setEnabled(False)

        input_layout.addWidget(QLabel("URL:"))
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(QLabel("Depth:"))
        input_layout.addWidget(self.depth_input)
        input_layout.addWidget(self.btn_start)
        input_layout.addWidget(self.btn_stop)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        layout.addLayout(input_layout)
        layout.addWidget(self.log_box)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.btn_start.clicked.connect(self.start_crawler)
        self.btn_stop.clicked.connect(self.stop_crawler)

    def start_crawler(self):
        url = self.url_input.text().strip()
        try:
            depth = int(self.depth_input.text().strip())
        except ValueError:
            self.log_box.append("<span style='color:red;'>Vui lòng nhập độ sâu là số nguyên!</span>")
            return

        if not url:
            self.log_box.append("<span style='color:red;'>Vui lòng nhập URL!</span>")
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_box.clear()
        self.log_box.append(f"<b>Bắt đầu cào: {url} với độ sâu {depth}</b>")

        self.crawler_thread = CrawlerThread(url, depth)
        self.crawler_thread.tin_nhan.connect(self.update_log)
        self.crawler_thread.start()

    def stop_crawler(self):
        if hasattr(self, 'crawler_thread'):
            self.crawler_thread.stop()
            self.btn_stop.setEnabled(False)

    def update_log(self, text):
        self.log_box.append(text)
        if not self.crawler_thread.isRunning():
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())