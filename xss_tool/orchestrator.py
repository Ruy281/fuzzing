# orchestrator.py
import logging
import requests

from .models import Finding
from .phase1_target import TargetIdentifier
from .phase2_input import InputAnalyzer
from .phase3_payload import PayloadGenerator
from .phase4_fuzz import Fuzzer
from .phase5_verify import Verifier

log = logging.getLogger("xss")

class XSSScanner:
    def __init__(self, urls: list[str],
                 session: requests.Session,
                 oast_client=None,
                 fuzzdb_path: str | None = None,
                 delay: float = 0.5,
                 enable_dom: bool = True,
                 enable_blind: bool = True,
                 form_values: dict[str, str] | None = None,
                 progress=None):
        self.urls = urls
        self.session = session
        self.oast = oast_client
        self.fuzzdb_path = fuzzdb_path
        self.delay = delay
        self.enable_dom = enable_dom
        self.enable_blind = enable_blind
        self.form_values = form_values or {}
        self.progress = progress or (lambda m: log.info(m))

    def run(self) -> list[Finding]:
        findings: list[Finding] = []

        # ---------- PHA 1 ----------
        self.progress("[PHA 1] Xác định mục tiêu")
        targets = TargetIdentifier(self.urls, self.session).identify()

        # ---------- PHA 2 ----------
        self.progress("[PHA 2] Canary test")
        analyzer = InputAnalyzer(self.session, form_values=self.form_values)
        reflected_targets = []
        for t in targets:
            if t.kind == "get_param":
                updated = analyzer.test_get_param(t)
            elif t.kind == "form":
                updated = analyzer.test_form(t)
            else:
                updated = None
            if updated:
                reflected_targets.append(updated)

        gen = PayloadGenerator(fuzzdb_path=self.fuzzdb_path)
        fuzzer = Fuzzer(self.session, delay=self.delay,
                        form_values=self.form_values)

        # ---------- Reflected ----------
        self.progress(f"[PHA 3-5] Reflected ({len(reflected_targets)})")
        refl_results = []
        for t in reflected_targets:
            marker = gen.new_marker("XSS")
            payloads = gen.for_reflected(t.context, marker)
            refl_results.extend(fuzzer.run_reflected(t, payloads))
        findings.extend(Verifier.verify_reflected(refl_results))

        # ---------- Stored ----------
        form_targets = [t for t in targets if t.kind == "form"]
        self.progress(f"[PHA 3-5] Stored ({len(form_targets)})")
        marker_map = {}
        for t in form_targets:
            marker = gen.new_marker("XSS")
            fuzzer.run_stored(t, PayloadGenerator.for_stored(marker), marker_map)
        findings.extend(Verifier.verify_stored(self.session, marker_map,
                                               urls=self.urls))

        # ---------- Blind ----------
        if self.enable_blind and self.oast and form_targets:
            self.progress("[PHA 3-5] Blind (chờ callback)")
            cb_url = self.oast.register()
            blind_results = []
            for t in form_targets:
                r = fuzzer.run_blind(t, cb_url)
                if r:
                    blind_results.append(r)
            findings.extend(Verifier.verify_blind(self.oast, blind_results))

        # ---------- DOM ----------
        if self.enable_dom:
            dom_targets = [t for t in targets if t.kind == "dom"]
            self.progress(f"[PHA 3-5] DOM ({len(dom_targets)})")
            for t in dom_targets:
                marker = gen.new_marker("XSS")
                for payload in PayloadGenerator.for_dom(marker):
                    f = Verifier.verify_dom(f"{t.url}#{payload}", marker)
                    if f:
                        findings.append(f)
                        break

        self.progress(f"[✓] {len(findings)} lỗ hổng")
        return findings