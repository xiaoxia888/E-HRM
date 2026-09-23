from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol


class CharacterOcrEngine(Protocol):
    def classification(self, image: bytes) -> str: ...


def _default_engine() -> CharacterOcrEngine:
    try:
        import ddddocr
    except ImportError as exc:  # pragma: no cover - depends on deployment extras
        raise RuntimeError(
            "缺少字符验证码识别组件 ddddocr，请重新执行环境初始化"
        ) from exc
    return ddddocr.DdddOcr(show_ad=False)


class CharacterCaptchaRecognizer:
    """Recognizes the exact CAPTCHA image rendered in the current page."""

    def __init__(
        self,
        engine_factory: Callable[[], CharacterOcrEngine] = _default_engine,
    ) -> None:
        self._engine_factory = engine_factory
        self._engine: CharacterOcrEngine | None = None

    def recognize(self, image: bytes) -> str:
        if not image:
            raise ValueError("验证码截图为空")
        if self._engine is None:
            self._engine = self._engine_factory()
        raw = self._engine.classification(image)
        value = re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()
        if len(value) != 4:
            raise ValueError(f"验证码识别结果应为 4 位，实际为 {len(value)} 位")
        return value
