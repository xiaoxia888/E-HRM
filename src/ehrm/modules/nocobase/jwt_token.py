from __future__ import annotations

import base64
import binascii
import json

from ehrm.modules.nocobase.exceptions import NocoBaseAuthenticationError
from ehrm.modules.nocobase.models import NocoBaseTokenClaims


def decode_jwt_claims(token: str) -> NocoBaseTokenClaims:
    """Decodes JWT claims for expiry checks without asserting its signature.

    The server remains authoritative for token validity. This local decode is
    only used to avoid sending a token that is already expired.
    """

    parts = token.strip().split(".")
    if len(parts) != 3 or not parts[1]:
        raise NocoBaseAuthenticationError("NocoBase 登录接口返回的 Token 格式错误")
    payload_part = parts[1]
    payload_part += "=" * (-len(payload_part) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_part.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeError, ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise NocoBaseAuthenticationError(
            "NocoBase 登录接口返回的 Token 无法解析"
        ) from exc
    if not isinstance(payload, dict):
        raise NocoBaseAuthenticationError("NocoBase Token 载荷结构错误")
    try:
        user_id = _required_integer(payload, "userId")
        issued_at = _required_integer(payload, "iat")
        expires_at = _required_integer(payload, "exp")
    except (TypeError, ValueError) as exc:
        raise NocoBaseAuthenticationError("NocoBase Token 缺少有效时间信息") from exc
    if expires_at <= issued_at:
        raise NocoBaseAuthenticationError("NocoBase Token 过期时间无效")
    return NocoBaseTokenClaims(
        user_id=user_id,
        temporary=payload.get("temp") is True,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _required_integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise TypeError(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise TypeError(key)
