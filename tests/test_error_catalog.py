from pathlib import Path

import pytest

from ehrm.core.error_catalog import (
    ErrorCode,
    configure_error_messages,
    display_message,
)


def setup_module() -> None:
    configure_error_messages(Path("config/error_messages.toml"))


def test_error_code_resolves_to_chinese_display_message() -> None:
    assert (
        display_message(ErrorCode.EMPLOYEE_NOT_FOUND)
        == "未查询到符合条件的人员"
    )


def test_unknown_code_uses_fallback_without_exposing_internal_code() -> None:
    assert display_message("CUSTOM_ERROR", "自定义失败原因") == "自定义失败原因"


def test_catalog_rejects_missing_error_codes(tmp_path: Path) -> None:
    path = tmp_path / "error_messages.toml"
    path.write_text('[error_messages]\nSUCCESS = "处理成功"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="异常文案缺少编码"):
        configure_error_messages(path)
