from __future__ import annotations

from ehrm.modules.nocobase.exceptions import (
    NocoBaseInvalidTokenError,
    NocoBaseRequestError,
)


INVALID_TOKEN_CODE = "INVALID_TOKEN"


def raise_for_nocobase_errors(payload: object) -> None:
    if not isinstance(payload, dict):
        raise NocoBaseRequestError("NocoBase 接口响应结构错误")
    errors = payload.get("errors")
    if errors is None:
        return
    if not isinstance(errors, list):
        raise NocoBaseRequestError("NocoBase 接口错误响应结构异常")
    parsed = [item for item in errors if isinstance(item, dict)]
    invalid = next(
        (
            item
            for item in parsed
            if str(item.get("code") or "").strip().upper()
            == INVALID_TOKEN_CODE
        ),
        None,
    )
    if invalid is not None:
        message = str(invalid.get("message") or "").strip()
        raise NocoBaseInvalidTokenError(
            message or "NocoBase 登录状态已失效"
        )
    messages = [str(item.get("message") or "").strip() for item in parsed]
    rendered = "；".join(message for message in messages if message)
    raise NocoBaseRequestError(rendered or "NocoBase 接口请求失败")
