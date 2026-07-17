"""Windows cp949 콘솔 등에서 print가 UnicodeEncodeError로 API를 중단하지 않게 한다."""
from __future__ import annotations

import sys


def console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def safe_print(*args, **kwargs) -> None:
    print(*[console_safe(str(arg)) for arg in args], **kwargs)
