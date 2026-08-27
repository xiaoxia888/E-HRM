import logging
from unittest.mock import Mock

import pytest

from ehrm.core.exceptions import (
    AuthenticationFailedError,
    RightsApiRequestError,
)
from ehrm.modules.rights_statement.api_session import RightsStatementApiSession


def test_api_session_uses_valid_token_without_login() -> None:
    client = object()
    authenticate = Mock()
    progress = Mock()
    session = RightsStatementApiSession(
        lambda: client,  # type: ignore[arg-type]
        authenticate,
        logging.getLogger("test.api-session"),
        progress,
    )

    result = session.execute(lambda actual: actual, operation_name="测试查询")

    assert result is client
    authenticate.assert_not_called()
    progress.assert_not_called()


def test_api_session_logs_in_and_retries_once_after_token_expiry() -> None:
    first_client = object()
    refreshed_client = object()
    clients = iter((first_client, refreshed_client))
    authenticate = Mock()
    progress_messages: list[str] = []
    calls: list[object] = []
    session = RightsStatementApiSession(
        lambda: next(clients),  # type: ignore[arg-type]
        authenticate,
        logging.getLogger("test.api-session"),
        progress_messages.append,
    )

    def operation(client):
        calls.append(client)
        if client is first_client:
            raise AuthenticationFailedError("Token 已失效")
        return "success"

    result = session.execute(operation, operation_name="人员查询")

    assert result == "success"
    assert calls == [first_client, refreshed_client]
    authenticate.assert_called_once_with()
    assert any("重新登录" in message for message in progress_messages)
    assert any("重试原请求" in message for message in progress_messages)


def test_api_session_surfaces_login_failure_without_second_request() -> None:
    client = object()
    operation = Mock(side_effect=AuthenticationFailedError("Token 已失效"))
    authenticate = Mock(side_effect=AuthenticationFailedError("账号密码错误"))
    session = RightsStatementApiSession(
        lambda: client,  # type: ignore[arg-type]
        authenticate,
        logging.getLogger("test.api-session"),
    )

    with pytest.raises(AuthenticationFailedError, match="账号密码错误"):
        session.execute(operation, operation_name="人员查询")

    assert operation.call_count == 1
    authenticate.assert_called_once_with()


def test_api_session_does_not_login_for_an_ordinary_business_error() -> None:
    authenticate = Mock()
    session = RightsStatementApiSession(
        lambda: object(),  # type: ignore[arg-type]
        authenticate,
        logging.getLogger("test.api-session"),
    )

    with pytest.raises(RightsApiRequestError, match="未查询到信息"):
        session.execute(
            lambda _client: (_ for _ in ()).throw(
                RightsApiRequestError("未查询到信息")
            ),
            operation_name="人员查询",
        )

    authenticate.assert_not_called()
