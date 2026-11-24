# crawler.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, urldefrag
from collections import deque
import logging

log = logging.getLogger("xss")

def crawl(start_url: str, max_depth: int = 1, session: requests.Session = None) -> list[str]:
    """
    Hàm thu thập URL từ trang bắt đầu.
    Trả về một danh sách các URL nội bộ (cùng domain).
    """
    if not session:
        session = requests.Session()

    if not start_url.startswith("http"):
        start_url = "http://" + start_url

    base_netloc = urlparse(start_url).netloc
    queue = deque([(start_url, 0)])
    visited = {start_url}
    found_urls = [start_url]

    while queue:
        url, depth = queue.popleft()
        
        # Nếu đã đạt độ sâu tối đa thì không cào link ở trang này nữa
        if depth >= max_depth:
            continue
            
        try:
            r = session.get(url, timeout=5)
            if r.status_code != 200:
                continue
                
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a"):
                href = a.get("href")
                if not href:
                    continue
                    
                full_url = urldefrag(urljoin(url, href)).url
                parsed_full_url = urlparse(full_url)

                # Chỉ lấy các link cùng domain (nội bộ)
                if parsed_full_url.netloc != base_netloc:
                    continue

                # Loại bỏ các link rác (mailto, javascript, tel)
                if full_url.startswith(("mailto:", "javascript:", "tel:")):
                    continue
                page_name = parsed_full_url.path.lower().rsplit("/", 1)[-1]
                if page_name.startswith(("logout", "logoff", "signout")):
                    continue

                if full_url not in visited:
                    visited.add(full_url)
                    found_urls.append(full_url)
                    queue.append((full_url, depth + 1))
                    
        except Exception as e:
            log.debug(f"Lỗi khi cào {url}: {e}")
            continue

    log.info(f"[CRAWLER] Thu thập được {len(found_urls)} URL (depth={max_depth})")
    return found_urls