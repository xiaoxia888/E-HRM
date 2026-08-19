from ehrm.core.exceptions import WebsiteStructureChangedError
from ehrm.modules.erp.codec import ErpQueryCodec


class FakeFrame:
    def __init__(self, available: bool) -> None:
        self.available = available

    def evaluate(self, expression: str, value: str | None = None):
        if "typeof base64swhere" in expression:
            return self.available
        if self.available and value is not None:
            return f"encoded:{value}"
        raise AssertionError("不可用 Frame 不应执行编码")


class FakePage:
    def __init__(self, frames: list[FakeFrame]) -> None:
        self.frames = frames


def test_codec_uses_frame_that_owns_erp_function() -> None:
    page = FakePage([FakeFrame(False), FakeFrame(True)])

    encoded = ErpQueryCodec(page).encode_swhere(" 1=1 ")

    assert encoded == "encoded: 1=1 "


def test_codec_reports_missing_frontend_function() -> None:
    page = FakePage([FakeFrame(False)])

    try:
        ErpQueryCodec(page).encode_swhere(" 1=1 ")
    except WebsiteStructureChangedError as exc:
        assert "base64swhere" in exc.message
    else:
        raise AssertionError("缺少编码函数时应抛出异常")
