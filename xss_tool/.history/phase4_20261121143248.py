# phase4_fuzz.py
import re
import time
import requests

from .models import Target, FuzzResult
from .phase3_payload import PayloadGenerator

class Fuzzer:
    def __init__(self, session: requests.Session, delay: float = 0.5):
        self.session = session
        self.delay = delay

    def run_reflected(self, target: Target,
                      payloads: list[str]) -> list[FuzzResult]:
        from urllib.parse import urlparse, urlencode
        results = []
        parsed = urlparse(target.url)
        param = list(target.params.keys())[0]
        for payload in payloads:
            new_params = dict(target.params)
            new_params[param] = payload
            test_url = parsed._replace(
                query=urlencode(new_params, doseq=True)
            ).geturl()
            try:
                r = self.session.get(test_url, timeout=5)
                results.append(FuzzResult(kind="reflected", url=test_url,
                                          param=param, payload=payload,
                                          response=r))
            except Exception:
                pass
            time.sleep(self.delay)
        return results

    def run_stored(self, target: Target, payloads: list[str],
                   marker_map: dict) -> None:
        form = target.form
        for payload in payloads:
            marker = self._extract_marker(payload)
            if not marker:
                continue
            marker_map[marker] = {"action": form["action"],
                                  "origin_url": form["origin_url"]}
            self._submit_form(form, payload)

    def run_blind(self, target: Target, callback_url: str) -> dict | None:
        form = target.form
        marker = PayloadGenerator.new_marker("BLIND")
        for payload in PayloadGenerator.for_blind(callback_url, marker):
            self._submit_form(form, payload)
        return {"marker": marker, "action": form["action"],
                "callback": f"{callback_url.rstrip('/')}/{marker}"}

    def _submit_form(self, form: dict, payload: str) -> None:
        data = {}
        if form.get("csrf"):
            data[form["csrf"]["name"]] = form["csrf"]["value"]
        for fld in form["fields"]:
            data[fld["name"]] = payload
        try:
            if form["method"] == "post":
                self.session.post(form["action"], data=data, timeout=5)
            else:
                self.session.get(form["action"], params=data, timeout=5)
        except Exception:
            pass
        time.sleep(self.delay)

    @staticmethod
    def _extract_marker(payload: str) -> str | None:
        m = re.search(r"(XSS|BLIND)_[a-f0-9]{10}", payload)
        return m.group(0) if m else None