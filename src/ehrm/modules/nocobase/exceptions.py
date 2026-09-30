from __future__ import annotations

from ehrm.core.exceptions import AuthenticationFailedError, EhrmError
from ehrm.core.error_catalog import ErrorCode


class NocoBaseAuthenticationError(AuthenticationFailedError):
    """NocoBase credentials or authentication response is invalid."""


class NocoBaseInvalidTokenError(NocoBaseAuthenticationError):
    """A protected NocoBase endpoint rejected the current JWT."""


class NocoBaseRequestError(EhrmError):
    """NocoBase returned an invalid or unsuccessful business response."""


class NocoBaseApiKeyInvalidError(NocoBaseAuthenticationError):
    """Configured API key was rejected; never trigger a password login."""

    code = ErrorCode.NOCOBASE_API_KEY_INVALID


class NocoBasePermissionDeniedError(NocoBaseRequestError):
    """The key's role lacks access to the requested resource."""

    code = ErrorCode.NOCOBASE_PERMISSION_DENIED
