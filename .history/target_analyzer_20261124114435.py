from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
from playwright.async_api import Page


@dataclass
class Target:
    """Đại diện cho 1 vị trí đầu vào cụ thể trên trang với 1 nhãn dán duy nhất."""
    url: str
    label: str  # Chỉ 1 nhãn: 'query_string' | 'form' | 'file_upload' | 'DOM'
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class TargetAnalyzer:
    """Phân tích HTML của trang bằng Python thuần và tách từng vị trí đầu vào thành Target riêng."""

    DOM_SINKS_AND_SOURCES = (
        "innerhtml", "outerhtml", "document.write", "eval(",
        "location.hash", "location.search", "window.name",
        "postmessage", "localstorage", "sessionstorage"
    )

    @staticmethod
    def _extract_query_params(url: str) -> List[str]:
        params = []
        parsed = urlparse(url)
        if parsed.query:
            params.extend(parse_qs(parsed.query, keep_blank_values=True).keys())
            # keep blan values de giu ca nhung tham so khong co gia tri, vi no van la 1 tham so hop le tren URL
        if "?" in parsed.fragment:
            frag_query = parsed.fragment.split("?", 1)[1]
            params.extend(parse_qs(frag_query, keep_blank_values=True).keys())
        return list(dict.fromkeys(params))

    @staticmethod
    def _build_selector(tag, fallback_index: int = 0) -> str:
        """Tạo CSS selector ngắn gọn để định danh phần tử."""
        tag_id = tag.get("id")
        if tag_id:
            return f"#{tag_id}"
        tag_name = tag.get("name")
        if tag_name:
            return f'{tag.name}[name="{tag_name}"]'
        return f"{tag.name}[index={fallback_index}]"

    async def analyze_page(self, page: Page, url: str) -> List[Target]:
        """Lấy HTML đã render từ page và trả về danh sách đối tượng Target."""
        targets: List[Target] = []

        # 1. Target loại 'query_string' (mỗi tham số trên URL là 1 Target)
        for param in self._extract_query_params(url):
            targets.append(
                Target(
                    url=url,
                    label="query_string",
                    detail={"param": param}
                )
            )

        # Lấy mã nguồn HTML đã render trên trình duyệt
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # 2. Target loại 'form' (mỗi thẻ <form> là 1 Target)
        forms = soup.find_all("form")
        for idx, form in enumerate(forms):
            form_selector = self._build_selector(form, idx)
            inputs_info = []
            for inp in form.find_all(["input", "textarea", "select"]):
                inputs_info.append({
                    "name": inp.get("name") or inp.get("id") or "",
                    "type": (inp.get("type") or inp.name).lower()
                })

            targets.append(
                Target(
                    url=url,
                    label="form",
                    detail={
                        "selector": form_selector,
                        "action": form.get("action") or "",
                        "method": (form.get("method") or "GET").upper(),
                        "inputs": inputs_info,
                    }
                )
            )

            # Kiểm tra nếu form có enctype multipart nhưng chưa có thẻ input[type=file]
            file_inputs_in_form = form.find_all("input", {"type": lambda t: t and t.lower() == "file"})
            enctype = (form.get("enctype") or "").lower()
            if not file_inputs_in_form and "multipart/form-data" in enctype:
                targets.append(
                    Target(
                        url=url,
                        label="file_upload",
                        detail={
                            "selector": form_selector,
                            "input_name": "",
                            "form_selector": form_selector
                        }
                    )
                )

        # 3. Target loại 'file_upload' (mỗi <input type="file"> là 1 Target)
        file_inputs = soup.find_all("input", {"type": lambda t: t and t.lower() == "file"})
        for idx, f_inp in enumerate(file_inputs):
            parent_form = f_inp.find_parent("form")
            targets.append(
                Target(
                    url=url,
                    label="file_upload",
                    detail={
                        "selector": self._build_selector(f_inp, idx),
                        "input_name": f_inp.get("name") or f_inp.get("id") or "",
                        "form_selector": self._build_selector(parent_form) if parent_form else None
                    }
                )
            )

        # 4. Target loại 'DOM' (input ngoài form, inline event handler, inline script chứa sink/source)
        # 4a. Input/textarea/select nằm độc lập ngoài <form>
        for idx, inp in enumerate(soup.find_all(["input", "textarea", "select"])):
            if inp.find_parent("form") is None and (inp.get("type") or "").lower() != "file":
                targets.append(
                    Target(
                        url=url,
                        label="DOM",
                        detail={
                            "type": "standalone_input",
                            "selector": self._build_selector(inp, idx),
                            "name": inp.get("name") or inp.get("id") or ""
                        }
                    )
                )

        # 4b. Phần tử có thuộc tính sự kiện inline (onclick, onload, oninput...)
        for idx, tag in enumerate(soup.find_all(True)):
            inline_events = [attr.lower() for attr in tag.attrs if attr.lower().startswith("on")]
            if inline_events:
                targets.append(
                    Target(
                        url=url,
                        label="DOM",
                        detail={
                            "type": "inline_event",
                            "selector": self._build_selector(tag, idx),
                            "events": inline_events
                        }
                    )
                )

        # 4c. Thẻ <script> nhúng trực tiếp có sử dụng nguồn/đích DOM
        for idx, script in enumerate(soup.find_all("script")):
            if not script.get("src") and script.string:
                content_lower = script.string.lower()
                matched = [token for token in self.DOM_SINKS_AND_SOURCES if token in content_lower]
                if matched:
                    targets.append(
                        Target(
                            url=url,
                            label="DOM",
                            detail={
                                "type": "inline_script",
                                "selector": f"script:inline[{idx}]",
                                "matched_tokens": matched
                            }
                        )
                    )

        return targets