from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from ehrm.core.exceptions import AuthenticationFailedError
from ehrm.modules.rights_statement.api_client import RightsStatementApiClient


_Result = TypeVar("_Result")


class RightsStatementApiSession:
    """Runs API operations and refreshes an invalid token exactly once."""

    def __init__(
        self,
        client_factory: Callable[[], RightsStatementApiClient],
        authenticate: Callable[[], None],
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._authenticate = authenticate
        self._logger = logger
        self._progress_callback = progress_callback

    def execute(
        self,
        operation: Callable[[RightsStatementApiClient], _Result],
        *,
        operation_name: str,
    ) -> _Result:
        try:
            return operation(self._client_factory())
        except AuthenticationFailedError as initial_error:
            self._logger.info(
                "智慧人社 Access-Token 不可用，准备重新登录 operation=%s reason=%s",
                operation_name,
                initial_error.message,
            )
            self._progress(
                "认证状态：本地 Access-Token 已失效，正在重新登录刷新 Token……"
            )

        # Login errors are deliberately not caught here. They are the only
        # authentication errors that should be surfaced to the caller directly.
        self._authenticate()
        self._progress("认证状态：Token 已刷新，正在重试原请求……")
        try:
            result = operation(self._client_factory())
        except AuthenticationFailedError:
            self._logger.error(
                "智慧人社 Token 刷新后重试仍认证失败 operation=%s",
                operation_name,
            )
            raise
        self._logger.info(
            "智慧人社 Token 刷新后重试成功 operation=%s",
            operation_name,
        )
        return result

    def _progress(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)
