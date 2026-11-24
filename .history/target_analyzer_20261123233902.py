import re
from dataclasses import dataclass, field, asdict
from typing import List, Set
from urllib.parse import urlparse, parse_qs

from playwright.async_api import Page


@dataclass
class Target:
    """Đối tượng đại diện cho một mục tiêu (URL) kèm các nhãn phân loại bề mặt đầu vào."""
    url: str
    labels: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class TargetAnalyzer:
    """Phân tích trực tiếp trên đối tượng Playwright Page đang mở để tạo Target và gắn nhãn."""

    DOM_SINKS_AND_SOURCES = (
        "innerhtml", "outerhtml", "document.write", "eval(",
        "location.hash", "location.search", "window.name",
        "postmessage", "localstorage", "sessionstorage"
    )

    @staticmethod
    def _has_query_string(url: str) -> bool:
        parsed = urlparse(url)
        if parse_qs(parsed.query):
            return True
        if "?" in parsed.fragment:
            frag_query = parsed.fragment.split("?", 1)[1]
            if parse_qs(frag_query):
                return True
        return False

    async def analyze_page(self, page: Page, url: str) -> Target:
        """Đọc cây DOM của page hiện tại và trả về đối tượng Target kèm nhãn dán."""
        labels: Set[str] = set()

        # 1. Kiểm tra query_string từ URL
        if self._has_query_string(url):
            labels.add("query_string")

        # 2. Chạy JS trực tiếp trong trình duyệt để kiểm tra cây DOM (nhanh, không chặn event loop)
        dom_features = await page.evaluate("""() => {
            const forms = document.querySelectorAll('form');
            const hasForm = forms.length > 0;

            let hasFileUpload = document.querySelector('input[type="file" i]') !== null;
            if (!hasFileUpload) {
                for (const f of forms) {
                    if ((f.enctype || '').toLowerCase().includes('multipart/form-data')) {
                        hasFileUpload = true;
                        break;
                    }
                }
            }

            // Thu thập nội dung inline script để kiểm tra DOM sinks/sources
            const inlineScripts = Array.from(document.querySelectorAll('script:not([src])'))
                .map(s => s.textContent || '')
                .join('\n');

            // Kiểm tra event handler inline (onclick, onload, oninput...)
            let hasInlineEvent = false;
            const allElements = document.querySelectorAll('*');
            for (const el of allElements) {
                for (const attr of el.attributes) {
                    if (attr.name.toLowerCase().startsWith('on')) {
                        hasInlineEvent = true;
                        break;
                    }
                }
                if (hasInlineEvent) break;
            }

            // Kiểm tra thẻ nhập liệu nằm độc lập bên ngoài <form>
            let hasStandaloneInput = false;
            const inputs = document.querySelectorAll('input, textarea, select');
            for (const inp of inputs) {
                if (!inp.closest('form')) {
                    hasStandaloneInput = true;
                    break;
                }
            }

            return {
                hasForm,
                hasFileUpload,
                inlineScripts,
                hasInlineEvent,
                hasStandaloneInput
            };
        }""")

        if dom_features["hasForm"]:
            labels.add("form")

        if dom_features["hasFileUpload"]:
            labels.add("file_upload")

        has_dom = (
            dom_features["hasInlineEvent"]
            or dom_features["hasStandaloneInput"]
            or any(token in dom_features["inlineScripts"].lower() for token in self.DOM_SINKS_AND_SOURCES)
        )
        if has_dom:
            labels.add("DOM")

        ordered_labels = [
            lbl for lbl in ("query_string", "form", "file_upload", "DOM")
            if lbl in labels
        ]
        return Target(url=url, labels=ordered_labels)
