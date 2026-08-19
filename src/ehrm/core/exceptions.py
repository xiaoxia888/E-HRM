from __future__ import annotations

from ehrm.core.error_catalog import ErrorCode


class EhrmError(Exception):
    """Base exception exposed to entrypoints."""

    code = ErrorCode.EHRM_ERROR
    retryable = False

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigurationError(EhrmError):
    code = ErrorCode.CONFIGURATION_ERROR


class QueryValidationError(EhrmError):
    code = ErrorCode.QUERY_VALIDATION_ERROR


class ExcelValidationError(EhrmError):
    code = ErrorCode.EXCEL_VALIDATION_ERROR


class SecurityVerificationRequired(EhrmError):
    code = ErrorCode.SECURITY_VERIFICATION_REQUIRED


class AuthenticationFailedError(EhrmError):
    code = ErrorCode.AUTHENTICATION_FAILED


class EmployeeNotFoundError(EhrmError):
    code = ErrorCode.EMPLOYEE_NOT_FOUND


class QueryResultTimeoutError(EhrmError):
    code = ErrorCode.QUERY_RESULT_TIMEOUT
    retryable = True


class MultipleEmployeeMatchedError(EhrmError):
    code = ErrorCode.MULTIPLE_EMPLOYEE_MATCHED


class WebsiteStructureChangedError(EhrmError):
    code = ErrorCode.WEBSITE_STRUCTURE_CHANGED


class DownloadTimeoutError(EhrmError):
    code = ErrorCode.DOWNLOAD_TIMEOUT
    retryable = True


class FileValidationError(EhrmError):
    code = ErrorCode.FILE_VALIDATION_ERROR


class TaskCancelledError(EhrmError):
    code = ErrorCode.TASK_CANCELLED
