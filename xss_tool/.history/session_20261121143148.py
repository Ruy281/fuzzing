# session.py
import requests

def create_session(cookies: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.setdefault("User-Agent", "Mozilla/5.0 XSSScanner/1.0")
    if cookies:
        s.headers["Cookie"] = cookies
    return s