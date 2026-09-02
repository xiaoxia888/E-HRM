from __future__ import annotations

from ehrm.core.exceptions import AuthenticationFailedError, EhrmError


class NocoBaseAuthenticationError(AuthenticationFailedError):
    """NocoBase credentials or authentication response is invalid."""


class NocoBaseInvalidTokenError(NocoBaseAuthenticationError):
    """A protected NocoBase endpoint rejected the current JWT."""


class NocoBaseRequestError(EhrmError):
    """NocoBase returned an invalid or unsuccessful business response."""
