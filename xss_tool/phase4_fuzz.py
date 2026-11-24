# phase4_fuzz.py
import re
import time
import requests

from .models import Target, FuzzResult
from .phase3_payload import PayloadGenerator

class Fuzzer:
    def __init__(self, session: requests.Session, delay: float = 0.5,
                 form_values: dict[str, str] | None = None):
        self.session = session
        self.delay = delay
        self.form_values = form_values or {}

    def run_reflected(self, target: Target,
                      payloads: list[str]) -> list[FuzzResult]:
        if target.kind == "form":
            return self._run_reflected_form(target, payloads)

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
            except requests.RequestException:
                pass
            time.sleep(self.delay)
        return results

    def _run_reflected_form(self, target: Target,
                            payloads: list[str]) -> list[FuzzResult]:
        results = []
        param = list(target.params.keys())[0]
        for payload in payloads:
            response = self.submit_form(target.form, payload, param)
            if response is not None:
                results.append(FuzzResult(kind="reflected", url=response.url,
                                          param=param, payload=payload,
                                          response=response))
        return results

    def run_stored(self, target: Target, payloads: list[str],
                   marker_map: dict) -> None:
        form = target.form
        base_marker = self._extract_marker(payloads[0]) if payloads else None
        if not base_marker:
            return
        for field in self.fuzzable_fields(form):
            marker = PayloadGenerator.new_marker("XSS")
            info = {"action": form["action"],
                    "origin_url": form["origin_url"],
                    "param": field["name"], "payloads": []}
            marker_map[marker] = info
            for template in payloads:
                payload = template.replace(base_marker, marker)
                info["payloads"].append(payload)
                self.submit_form(form, payload, field["name"])

    def run_blind(self, target: Target, callback_url: str) -> dict | None:
        form = target.form
        marker = PayloadGenerator.new_marker("BLIND")
        for payload in PayloadGenerator.for_blind(callback_url, marker):
            for field in self.fuzzable_fields(form):
                self.submit_form(form, payload, field["name"])
        return {"marker": marker, "action": form["action"],
                "callback": f"{callback_url.rstrip('/')}/{marker}"}

    def submit_form(self, form: dict, payload: str,
                     field_name: str) -> requests.Response | None:
        data = self._form_data(form, field_name, payload)
        try:
            if form["method"] == "post":
                response = self.session.post(form["action"], data=data, timeout=5,
                                             allow_redirects=False)
            else:
                response = self.session.get(form["action"], params=data, timeout=5,
                                            allow_redirects=False)
        except requests.RequestException:
            response = None
        time.sleep(self.delay)
        return response

    def _form_data(self, form: dict, field_name: str, payload: str) -> dict:
        data = {}
        if form.get("csrf"):
            data[form["csrf"]["name"]] = form["csrf"]["value"]
        for fld in form["fields"]:
            name = fld["name"]
            if name == field_name:
                data[name] = payload
                continue
            configured = self.form_values.get(name)
            if configured is None and "user" in name.lower():
                configured = self.form_values.get("username")
            if configured is None and fld["type"] == "password":
                configured = self.form_values.get("password")
            data[name] = (configured if configured is not None
                          else fld.get("value") or self._default_value(fld))
        return data

    @staticmethod
    def fuzzable_fields(form: dict) -> list[dict]:
        skipped = {"hidden", "checkbox", "radio", "submit", "button",
                   "image", "reset", "file"}
        return [f for f in form["fields"] if f["type"] not in skipped]

    @staticmethod
    def _default_value(field: dict) -> str:
        if field["type"] == "email":
            return "test@example.com"
        if field["type"] == "number":
            return "1"
        return "test"

    @staticmethod
    def _extract_marker(payload: str) -> str | None:
        m = re.search(r"(XSS|BLIND)_[a-f0-9]{10}", payload)
        return m.group(0) if m else None