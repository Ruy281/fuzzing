# phase2_input.py
import time
import uuid
from urllib.parse import urlparse, urlencode
import requests

from .models import Target
from .phase4_fuzz import Fuzzer

class InputAnalyzer:
    def __init__(self, session: requests.Session,
                 form_values: dict[str, str] | None = None):
        self.session = session
        self.form_values = form_values or {}

    def test_get_param(self, target: Target) -> Target | None:
        canary = "XSS_CANARY_" + uuid.uuid4().hex[:10]
        parsed = urlparse(target.url)
        for param in target.params:
            new_params = dict(target.params)
            new_params[param] = canary
            test_url = parsed._replace(
                query=urlencode(new_params, doseq=True)
            ).geturl()
            t0 = time.time()
            try:
                r = self.session.get(test_url, timeout=5)
            except Exception:
                continue
            delay = time.time() - t0
            if canary in r.text:
                ctx = self._detect_context(r.text, canary)
                return Target(kind="get_param", url=target.url,
                              params={param: ""}, context=ctx, delay=delay)
        return None

    def test_form(self, target: Target) -> Target | None:
        fuzzer = Fuzzer(self.session, delay=0, form_values=self.form_values)
        for field in fuzzer.fuzzable_fields(target.form):
            canary = "XSS_CANARY_" + uuid.uuid4().hex[:10]
            t0 = time.time()
            response = fuzzer.submit_form(target.form, canary, field["name"])
            if response is None or canary not in response.text:
                continue
            delay = time.time() - t0
            ctx = self._detect_context(response.text, canary)
            return Target(kind="form", url=target.url, params={field["name"]: ""},
                          form=target.form, context=ctx, delay=delay)
        return None

    @staticmethod
    def _detect_context(html: str, canary: str) -> str:
        idx = html.find(canary)
        if idx == -1:
            return "none"
        before = html[max(0, idx - 200):idx]
        last_open = before.lower().rfind("<script")
        last_close = before.lower().rfind("</script>")
        if last_open > last_close:
            return "script"
        last_tag = before.rfind("<")
        if last_tag != -1:
            tag_slice = before[last_tag:]
            if tag_slice.count('"') % 2 == 1:
                return "attribute_double"
            if tag_slice.count("'") % 2 == 1:
                return "attribute_single"
        return "html"