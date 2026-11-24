# models.py
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class Target:
    """
    Hợp đồng: Phase 1 sinh ra → Phase 2 chỉnh sửa (thêm context/delay)
              → Phase 3 & 4 đọc.
    """
    kind: str                          # 'get_param' | 'form' | 'dom'
    url: str
    params: dict = field(default_factory=dict)
    form: dict = field(default_factory=dict)
    context: str = "html"              # html|attribute_double|attribute_single|script
    delay: float = 0.0

@dataclass
class Finding:
    """Hợp đồng: Phase 5 sinh ra → orchestrator tổng hợp → output."""
    type: str                          # Reflected|Stored|Blind|DOM XSS
    url: str
    payload: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class FuzzResult:
    """Hợp đồng Phase 4 → Phase 5 (Reflected)."""
    kind: str
    url: str
    param: str
    payload: str
    response: Any = None               # requests.Response
    status_code: int = 0

    def __post_init__(self):
        if self.response is not None:
            self.status_code = getattr(self.response, "status_code", 0)