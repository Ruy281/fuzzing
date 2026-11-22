import sys
from urllib.parse import urlparse, urljoin
from collections import deque
from playwright.sync_api import sync_playwright

def normalize_url(url: str) -> str:
    #Chuẩn hóa URL để tránh cào trùng lặp (giữ nguyên fragment #/ cho SPA).#
    parsed = urlparse(url)

    # Bỏ dấu / ở cuối path nếu path không rỗng (trừ trang gốc /)
    path = parsed.path.rstrip("/") or "/"
    #path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
   
    normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
    
    if parsed.query:
        normalized += f"?{parsed.query}"

    #Dòng này giúp giữ lại phần fragment đó để crawler không bỏ sót các trang con của SPA.
    if parsed.fragment:
        normalized += f"#{parsed.fragment}"

    return normalized

def crawl(start_url: str, max_depth: int, on_log=print, stop_flag=lambda: False):
    target = start_url.strip()
    if not target.startswith("http"):
        target = "http://" + target 

    target = normalize_url(target)
    base_domain = urlparse(target).netloc
    queue = deque([(target, 0)])
    visited = set([target])

    on_log(f"[*] Bắt đầu quét: {target}")

    # Khởi tạo trình duyệt ẩn 1 lần duy nhất
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # headless=False nếu muốn nhìn thấy trình duyệt chạy
        page = browser.new_page()

        while queue and not stop_flag():
            url, depth = queue.popleft()
            if depth > max_depth:
                continue

            on_log(f"[*] Đang quét (Depth {depth}): {url}")
            try:
                # Dùng Playwright để truy cập và ĐỢI Javascript render xong
                page.goto(url, timeout=10000, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                
                if depth < max_depth:
                    elements = page.locator("a").all()

                    for el in elements:
                        if stop_flag():
                            break
                        href = el.get_attribute("href")
                        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
                            continue
                            
                        full_url = normalize_url(urljoin(url, href))

                        if urlparse(full_url).netloc == base_domain and full_url not in visited:
                            on_log(f"    [+] Tìm thấy: {full_url}")
                            visited.add(full_url)
                            queue.append((full_url, depth + 1))
                            
            except Exception:
                on_log(f"    [-] Lỗi (hoặc Timeout): {url}")
        
        # Đóng trình duyệt khi xong
        browser.close()
    
    on_log("[*] Hoàn tất!")
    return list(visited)

if __name__ == "__main__":
    u = input("Nhập URL: ")
    d = int(input("Nhập độ sâu: "))
    crawl(u, d)


# def stop(self):
#     self.is_running = False


#  --- LỚP GIAO DIỆN CHÍNH (Giữ nguyên) ---
# class MainWindow(QMainWindow):
#     def __init__(self):
#         super().__init__()
#         self.setWindowTitle("Web Crawler Tool (Hỗ trợ SPA)")
#         self.resize(700, 500)

#         layout = QVBoxLayout()
#         input_layout = QHBoxLayout()
#         self.url_input = QLineEdit()
#         self.url_input.setPlaceholderText("Nhập URL (VD: http://localhost:3000/#/)")
#         self.depth_input = QLineEdit()
#         self.depth_input.setPlaceholderText("Độ sâu (VD: 1)")
#         self.depth_input.setFixedWidth(100)
        
#         self.btn_start = QPushButton("Bắt đầu")
#         self.btn_stop = QPushButton("Dừng")
#         self.btn_stop.setEnabled(False)

#         input_layout.addWidget(QLabel("URL:"))
#         input_layout.addWidget(self.url_input)
#         input_layout.addWidget(QLabel("Depth:"))
#         input_layout.addWidget(self.depth_input)
#         input_layout.addWidget(self.btn_start)
#         input_layout.addWidget(self.btn_stop)

#         self.log_box = QTextEdit()
#         self.log_box.setReadOnly(True)

#         layout.addLayout(input_layout)
#         layout.addWidget(self.log_box)

#         container = QWidget()
#         container.setLayout(layout)
#         self.setCentralWidget(container)

#         self.btn_start.clicked.connect(self.start_crawler)
#         self.btn_stop.clicked.connect(self.stop_crawler)

#     def start_crawler(self):
#         url = self.url_input.text().strip()
#         try:
#             depth = int(self.depth_input.text().strip())
#         except ValueError:
#             self.log_box.append("<span style='color:red;'>Vui lòng nhập độ sâu là số nguyên!</span>")
#             return

#         if not url:
#             self.log_box.append("<span style='color:red;'>Vui lòng nhập URL!</span>")
#             return

#         self.btn_start.setEnabled(False)
#         self.btn_stop.setEnabled(True)
#         self.log_box.clear()
#         self.log_box.append(f"<b>Bắt đầu cào: {url} với độ sâu {depth}</b>")

#         self.crawler_thread = CrawlerThread(url, depth)
#         self.crawler_thread.tin_nhan.connect(self.update_log)
#         self.crawler_thread.start()

#     def stop_crawler(self):
#         if hasattr(self, 'crawler_thread'):
#             self.crawler_thread.stop()
#             self.btn_stop.setEnabled(False)

#     def update_log(self, text):
#         self.log_box.append(text)
#         if not self.crawler_thread.isRunning():
#             self.btn_start.setEnabled(True)
#             self.btn_stop.setEnabled(False)

# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     window = MainWindow()
#     window.show()
#     sys.exit(app.exec_())