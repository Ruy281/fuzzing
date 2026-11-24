# session.py
import requests

def create_session(cookies: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.setdefault("User-Agent", "Mozilla/5.0 XSSScanner/1.0")
    if cookies:
        s.headers["Cookie"] = cookies
    return s


def authenticate(login_url: str, session: requests.Session,
                 username: str, password: str) -> str | None:
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    response = session.get(login_url, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")
    for form in soup.find_all("form"):
        if not form.find("input", {"type": "password"}):
            continue
        data = {}
        username_added = False
        for field in form.find_all("input"):
            name = field.get("name")
            if not name:
                continue
            field_type = (field.get("type") or "text").lower()
            if field_type in ("submit", "button", "image", "reset", "file"):
                continue
            if field_type in ("checkbox", "radio") and not field.has_attr("checked"):
                continue
            if field_type == "password":
                data[name] = password
            elif not username_added and field_type not in ("hidden", "checkbox", "radio"):
                data[name] = username
                username_added = True
            else:
                data[name] = field.get("value", "")
        if not username_added:
            continue
        action = urljoin(login_url, form.get("action") or login_url)
        if (form.get("method") or "get").lower() == "post":
            logged_in = session.post(action, data=data, timeout=10)
        else:
            logged_in = session.get(action, params=data, timeout=10)
        logged_in_soup = BeautifulSoup(logged_in.text, "html.parser")
        if not logged_in_soup.find("input", {"type": "password"}):
            return logged_in.url
    return None