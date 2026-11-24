import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from collections import deque

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLineEdit, QTextEdit, QLabel, QHBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal

# --- LỚP THREAD ĐỂ CHẠY NGẦM (Không làm đơ giao diện) ---
class CrawlerThread(QThread):
    # Định nghĩa các tín hiệu (Signals) giống hệt code của bạn
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

        while queue and self.is_running:
            url, depth = queue.popleft()

            if depth > self.max_depth:
                continue

            self.tin_nhan.emit(f"[*] Đang quét (Depth {depth}): {url}")

            try:
                res = requests.get(url, timeout=3)
                if res.status_code != 200:
                    continue

                parsed = urlparse(url)
                if parsed.query:
                    self.tin_nhan.emit(f"<b style='color:blue;'>[+] MỤC TIÊU CÓ THAM SỐ: {url}</b>")
                    self.tim_thay_link_co_tham_so.emit(url)

                if depth < self.max_depth:
                    soup = BeautifulSoup(res.text, "html.parser")
                    for tag in soup.find_all("a"):
                        href = tag.get("href")
                        if not href:
                            continue
                        
                        full_url = urljoin(url, href)
                        
                        if urlparse(full_url).netloc == urlparse(target).netloc:
                            if full_url not in visited:
                                self.tim_thay_link_full.emit(full_url)
                                visited.add(full_url)
                                queue.append((full_url, depth + 1))

            except Exception as e:
                self.tin_nhan.emit(f"<span style='color:red;'>[-] Lỗi: {url} - {e}</span>")
        
        self.tin_nhan.emit("<b style='color:green;'>[*] Đã dừng quét.</b>")

    def stop(self):
        self.is_running = False


# --- LỚP GIAO DIỆN CHÍNH ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web Crawler Tool")
        self.resize(700, 500)

        # Layout
        layout = QVBoxLayout()
        
        # Khu vực nhập liệu
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Nhập URL (VD: example.com)")
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

        # Khu vực Log
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        layout.addLayout(input_layout)
        layout.addWidget(self.log_box)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Kết nối sự kiện
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

        # Khởi tạo và chạy luồng
        self.crawler_thread = CrawlerThread(url, depth)
        
        # Kết nối tín hiệu từ Thread tới giao diện
        self.crawler_thread.tin_nhan.connect(self.update_log)
        self.crawler_thread.tim_thay_link_co_tham_so.connect(self.handle_param_link)
        self.crawler_thread.tim_thay_link_full.connect(self.handle_new_link)
        
        self.crawler_thread.start()

    def stop_crawler(self):
        if hasattr(self, 'crawler_thread'):
            self.crawler_thread.stop()
            self.btn_stop.setEnabled(False)
            self.log_box.append("<b style='color:orange;'>[*] Đang yêu cầu dừng...</b>")

    def update_log(self, text):
        self.log_box.append(text)
        if not self.crawler_thread.isRunning():
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

    def handle_param_link(self, url):
        # Xử lý riêng các link có tham số nếu cần (ví dụ lưu ra file)
        pass

    def handle_new_link(self, full_url):
        self.log_box.append(f"<span style='color:gray;'>    [+] Tìm thấy: {full_url}</span>")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())