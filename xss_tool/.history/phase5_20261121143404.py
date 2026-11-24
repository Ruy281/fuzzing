# phase5_verify.py
import time
import requests

from .models import Finding, FuzzResult

class Verifier:
    @staticmethod
    def verify_reflected(results: list[FuzzResult]) -> list[Finding]:
        findings = []
        for r in results:
            if r.response is not None and r.payload in r.response.text:
                findings.append(Finding(
                    type="Reflected XSS", url=r.url, payload=r.payload,
                    detail={"param": r.param, "status": r.status_code},
                ))
        return findings

    @staticmethod
    def verify_stored(session: requests.Session, marker_map: dict,
                      max_wait: int = 5) -> list[Finding]:
        findings = []
        for marker, info in marker_map.items():
            urls = list({info["origin_url"], info["action"]})
            for attempt in range(max_wait):
                hit = False
                for url in urls:
                    try:
                        r = session.get(url, timeout=5)
                        if marker in r.text:
                            findings.append(Finding(
                                type="Stored XSS", url=url,
                                payload=f"marker={marker}",
                                detail={"injected_at": info["action"],
                                        "wait_seconds": attempt},
                            ))
                            hit = True
                            break
                    except Exception:
                        pass
                if hit:
                    break
                time.sleep(1)
        return findings

    @staticmethod
    def verify_blind(oast_client, blind_results: list[dict],
                     timeout: int = 600) -> list[Finding]:
        if not oast_client or not blind_results:
            return []
        findings = []
        pending = {r["marker"]: r for r in blind_results}
        start = time.time()
        while time.time() - start < timeout and pending:
            try:
                for it in oast_client.poll():
                    for marker in list(pending.keys()):
                        if marker in str(it):
                            r = pending.pop(marker)
                            findings.append(Finding(
                                type="Blind XSS", url=r["action"],
                                payload=r["callback"],
                                detail={"marker": marker},
                            ))
            except Exception:
                pass
            if pending:
                time.sleep(10)
        return findings

    @staticmethod
    def verify_dom(url: str, marker: str) -> Finding | None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script("""
                window.__xss_fired=false; window.__xss_msg='';
                ['alert','confirm','prompt'].forEach(function(fn){
                    var o=window[fn];
                    window[fn]=function(m){window.__xss_fired=true;
                        window.__xss_msg=String(m); return o.apply(this,arguments);};
                });
            """)
            triggered = False
            try:
                page.goto(url, timeout=5000)
                page.wait_for_timeout(2000)
                if page.evaluate("window.__xss_fired"):
                    if marker in str(page.evaluate("window.__xss_msg")):
                        triggered = True
            except Exception:
                pass
            finally:
                browser.close()
        if triggered:
            return Finding(type="DOM XSS", url=url,
                           payload=f"marker={marker}")
        return None