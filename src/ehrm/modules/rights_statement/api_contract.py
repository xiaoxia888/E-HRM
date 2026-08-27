from __future__ import annotations


class RightsApiContract:
    """Stable field names and business codes defined by the upstream API."""

    ACCESS_TOKEN_HEADER = "access-token"
    QUERY_COMMON_API_CODE = "370-0042"
    RIGHTS_BILL_AFFAIR_CODE = "B1135"
    RIGHTS_BILL_ACCEPT_TYPE = "2"

    AUTHENTICATION_FAILURE_APPCODES = frozenset({"1"})
    AUTHENTICATION_FAILURE_MESSAGES = (
        "Full authentication is required to access this resource",
    )

    @classmethod
    def is_authentication_failure(
        cls,
        *,
        http_status: int,
        appcode: str,
        message: str,
    ) -> bool:
        """Distinguishes authentication loss from an ordinary appcode=1 error."""
        if http_status in {401, 403}:
            return True
        if appcode not in cls.AUTHENTICATION_FAILURE_APPCODES:
            return False
        normalized_message = message.casefold()
        return any(
            marker.casefold() in normalized_message
            for marker in cls.AUTHENTICATION_FAILURE_MESSAGES
        )
