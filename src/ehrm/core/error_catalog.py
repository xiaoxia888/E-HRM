from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path


class ErrorCode(StrEnum):
    """Stable status codes used between services, files, and future APIs."""

    SUCCESS = "SUCCESS"
    EHRM_ERROR = "EHRM_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    QUERY_VALIDATION_ERROR = "QUERY_VALIDATION_ERROR"
    EXCEL_VALIDATION_ERROR = "EXCEL_VALIDATION_ERROR"
    SECURITY_VERIFICATION_REQUIRED = "SECURITY_VERIFICATION_REQUIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RIGHTS_API_REQUEST_FAILED = "RIGHTS_API_REQUEST_FAILED"
    EMPLOYEE_NOT_FOUND = "EMPLOYEE_NOT_FOUND"
    QUERY_RESULT_TIMEOUT = "QUERY_RESULT_TIMEOUT"
    MULTIPLE_EMPLOYEE_MATCHED = "MULTIPLE_EMPLOYEE_MATCHED"
    WEBSITE_STRUCTURE_CHANGED = "WEBSITE_STRUCTURE_CHANGED"
    DOWNLOAD_TIMEOUT = "DOWNLOAD_TIMEOUT"
    FILE_VALIDATION_ERROR = "FILE_VALIDATION_ERROR"
    ERP_AUTHENTICATION_FAILED = "ERP_AUTHENTICATION_FAILED"
    ERP_APPLICATION_NOT_FOUND = "ERP_APPLICATION_NOT_FOUND"
    ERP_APPLICATION_AMBIGUOUS = "ERP_APPLICATION_AMBIGUOUS"
    ERP_QUERY_FAILED = "ERP_QUERY_FAILED"
    ERP_PERSON_NOT_FOUND = "ERP_PERSON_NOT_FOUND"
    ERP_PERSON_AMBIGUOUS = "ERP_PERSON_AMBIGUOUS"
    ERP_PERSON_IDENTITY_INVALID = "ERP_PERSON_IDENTITY_INVALID"
    ERP_PERSON_IDENTITY_NAME_MISMATCH = "ERP_PERSON_IDENTITY_NAME_MISMATCH"
    ERP_PERSON_QUERY_FAILED = "ERP_PERSON_QUERY_FAILED"
    ERP_DUPLICATE_ATTACHMENT = "ERP_DUPLICATE_ATTACHMENT"
    ERP_UPLOAD_FAILED = "ERP_UPLOAD_FAILED"
    ERP_UPLOAD_VERIFICATION_FAILED = "ERP_UPLOAD_VERIFICATION_FAILED"
    ERP_ATTACHMENT_NOT_FOUND = "ERP_ATTACHMENT_NOT_FOUND"
    ERP_ATTACHMENT_AMBIGUOUS = "ERP_ATTACHMENT_AMBIGUOUS"
    ERP_DELETE_FAILED = "ERP_DELETE_FAILED"
    ERP_DELETE_VERIFICATION_FAILED = "ERP_DELETE_VERIFICATION_FAILED"
    AI_CONNECTION_FAILED = "AI_CONNECTION_FAILED"
    AI_REQUEST_FAILED = "AI_REQUEST_FAILED"
    AI_RESPONSE_INVALID = "AI_RESPONSE_INVALID"
    MEDICAL_INSURANCE_UNSUPPORTED = "MEDICAL_INSURANCE_UNSUPPORTED"
    AI_NO_PERSON_EXTRACTED = "AI_NO_PERSON_EXTRACTED"
    AI_DATE_MISSING = "AI_DATE_MISSING"
    AI_PRINT_MODE_REQUIRED = "AI_PRINT_MODE_REQUIRED"
    AI_REVIEW_REQUIRED = "AI_REVIEW_REQUIRED"
    AI_EXTRACTION_WARNING = "AI_EXTRACTION_WARNING"
    IDENTITY_MATCH_PENDING = "IDENTITY_MATCH_PENDING"
    TASK_CANCELLED = "TASK_CANCELLED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


_DISPLAY_MESSAGES: dict[ErrorCode, str] = {}


def configure_error_messages(path: Path) -> None:
    """Loads and validates the external user-facing message catalog."""
    if not path.is_file():
        raise ValueError(f"异常文案配置文件不存在：{path}")
    try:
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"异常文案配置文件格式错误：{exc}") from exc

    raw_messages = payload.get("error_messages")
    if not isinstance(raw_messages, dict):
        raise ValueError("异常文案配置缺少 [error_messages] 段")

    unknown = sorted(set(raw_messages) - {code.value for code in ErrorCode})
    if unknown:
        raise ValueError("异常文案包含未知编码：" + "、".join(unknown))

    messages: dict[ErrorCode, str] = {}
    missing: list[str] = []
    for code in ErrorCode:
        value = raw_messages.get(code.value)
        text = value.strip() if isinstance(value, str) else ""
        if not text:
            missing.append(code.value)
        else:
            messages[code] = text
    if missing:
        raise ValueError("异常文案缺少编码：" + "、".join(missing))

    _DISPLAY_MESSAGES.clear()
    _DISPLAY_MESSAGES.update(messages)


def display_message(code: str | ErrorCode, fallback: str | None = None) -> str:
    """Resolves an internal status code to user-facing Chinese text."""
    try:
        normalized = ErrorCode(code)
    except ValueError:
        return fallback or "业务处理失败"
    return _DISPLAY_MESSAGES.get(normalized, fallback or normalized.value)
