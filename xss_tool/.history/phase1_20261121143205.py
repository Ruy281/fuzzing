# phase1_target.py
from urllib.parse import urlparse, urljoin, parse_qs
import requests
from bs4 import BeautifulSoup

from .models import Target      # ← chỉ import từ models

class TargetIdentifier:
    def __init__(self, urls: list[str], session: requests.Session):
        self.urls = urls
        self.session = session

    def identify(self) -> list[Target]:
        targets: list[Target] = []
        for url in self.urls:
            parsed = urlparse(url)
            if parsed.query:
                params = {k: v[0] if len(v) == 1 else v
                          for k, v in parse_qs(parsed.query).items()}
                targets.append(Target(kind="get_param", url=url, params=params))

            for form in self._extract_forms(url):
                targets.append(Target(kind="form", url=url, form=form))

            targets.append(Target(kind="dom", url=url))
        return targets

    def _extract_forms(self, url: str) -> list[dict]:
        try:
            r = self.session.get(url, timeout=5)
        except Exception:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        result = []
        for form in soup.find_all("form"):
            action = urljoin(url, form.get("action") or url)
            method = (form.get("method") or "get").lower()
            fields, csrf = [], None
            for inp in form.find_all(["input", "textarea", "select"]):
                name = inp.get("name")
                if not name:
                    continue
                itype = (inp.get("type") or "text").lower()
                if itype in ("submit", "button", "image", "reset", "file"):
                    continue
                f = {"name": name, "type": itype, "value": inp.get("value", "")}
                if any(k in name.lower() for k in ("csrf", "token", "_token")):
                    csrf = f
                else:
                    fields.append(f)
            if fields:
                result.append({"action": action, "method": method,
                               "fields": fields, "csrf": csrf,
                               "origin_url": url})
        return result