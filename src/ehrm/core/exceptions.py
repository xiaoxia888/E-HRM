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


class ErpAuthenticationFailedError(EhrmError):
    code = ErrorCode.ERP_AUTHENTICATION_FAILED


class ErpApplicationNotFoundError(EhrmError):
    code = ErrorCode.ERP_APPLICATION_NOT_FOUND


class ErpApplicationAmbiguousError(EhrmError):
    code = ErrorCode.ERP_APPLICATION_AMBIGUOUS


class ErpQueryFailedError(EhrmError):
    code = ErrorCode.ERP_QUERY_FAILED
    retryable = True


class ErpDuplicateAttachmentError(EhrmError):
    code = ErrorCode.ERP_DUPLICATE_ATTACHMENT


class ErpUploadFailedError(EhrmError):
    code = ErrorCode.ERP_UPLOAD_FAILED
    retryable = True


class ErpUploadVerificationError(EhrmError):
    code = ErrorCode.ERP_UPLOAD_VERIFICATION_FAILED
    retryable = True


class ErpAttachmentNotFoundError(EhrmError):
    code = ErrorCode.ERP_ATTACHMENT_NOT_FOUND


class ErpAttachmentAmbiguousError(EhrmError):
    code = ErrorCode.ERP_ATTACHMENT_AMBIGUOUS


class ErpDeleteFailedError(EhrmError):
    code = ErrorCode.ERP_DELETE_FAILED


class ErpDeleteVerificationError(EhrmError):
    code = ErrorCode.ERP_DELETE_VERIFICATION_FAILED
    retryable = True


class AiConnectionFailedError(EhrmError):
    code = ErrorCode.AI_CONNECTION_FAILED
    retryable = True


class AiRequestFailedError(EhrmError):
    code = ErrorCode.AI_REQUEST_FAILED
    retryable = True


class AiResponseInvalidError(EhrmError):
    code = ErrorCode.AI_RESPONSE_INVALID
    retryable = True


class TaskCancelledError(EhrmError):
    code = ErrorCode.TASK_CANCELLED
