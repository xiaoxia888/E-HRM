from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Page

from ehrm.core.exceptions import WebsiteStructureChangedError


class ErpQueryCodec:
    """Uses the ERP page's own RC4 implementation instead of duplicating it."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def encode_swhere(self, plain_swhere: str) -> str:
        frame = self.find_codec_frame()
        try:
            value = frame.evaluate(
                "(text) => base64swhere(text)",
                plain_swhere,
            )
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                "ERP 查询条件编码失败",
                details=str(exc),
            ) from exc
        if not isinstance(value, str) or not value:
            raise WebsiteStructureChangedError("ERP 查询条件编码结果为空")
        return value

    def find_codec_frame(self) -> Frame:
        for frame in self._page.frames:
            try:
                if frame.evaluate("() => typeof base64swhere === 'function'"):
                    return frame
            except PlaywrightError:
                continue
        raise WebsiteStructureChangedError(
            "ERP 页面未找到 base64swhere 编码函数"
        )

    def is_available(self) -> bool:
        try:
            self.find_codec_frame()
        except WebsiteStructureChangedError:
            return False
        return True
