import base64
import logging
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.access_token import AccessTokenManager, MemoryAccessTokenStore
from ehrm.core.exceptions import (
    AuthenticationFailedError,
    QueryValidationError,
    RightsApiRequestError,
)
from ehrm.core.settings import load_settings
from ehrm.modules.rights_statement.api_client import RightsStatementApiClient
from ehrm.modules.rights_statement.api_contract import RightsApiContract
from ehrm.modules.rights_statement.api_models import (
    InsuranceCode,
    PersonQueryRequest,
    RightsBillPrintRequest,
)


_TEST_BUSINESS_NO = "2608271334000221"


class FakeResponse:
    def __init__(self, *, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload
        self.disposed = False

    def json(self) -> object:
        return self._payload

    def dispose(self) -> None:
        self.disposed = True


class FakeRequestContext:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("测试响应数量不足")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _success_payload() -> dict[str, object]:
    return {
        "appcode": "0",
        "msg": "",
        "map": {
            "result": {
                "apiInfo": {
                    "apiCode": "test-api-code",
                    "pageNumber": "1",
                    "pageSize": "100",
                    "totalPage": 1,
                    "totalCount": 1,
                    "errorinfo": None,
                },
                "body": [
                    {
                        "bac001": "test-person-id",
                        "aac002": "test-identity",
                        "aac003": "测试人员",
                    }
                ],
            }
        },
    }


def _print_success_payload(content: bytes | None = None) -> dict[str, object]:
    pdf = content or b"%PDF-1.4\ntest rights bill\n%%EOF"
    return {
        "appcode": "0",
        "msg": None,
        "map": {"pdf": base64.b64encode(pdf).decode("ascii")},
    }


def _business_no_response(
    business_no: str = _TEST_BUSINESS_NO,
) -> FakeResponse:
    return FakeResponse(
        status=200,
        payload={"appcode": "0", "msg": business_no, "map": {}},
    )


def _client(
    tmp_path: Path,
    responses: FakeResponse | list[FakeResponse | Exception],
):
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    store = MemoryAccessTokenStore()
    tokens = AccessTokenManager("test-account", store)
    tokens.save_token("test-secret-token")
    response_queue = responses if isinstance(responses, list) else [responses]
    request = FakeRequestContext(response_queue)
    client = RightsStatementApiClient(
        settings,
        request,  # type: ignore[arg-type]
        tokens,
        logging.getLogger("test.rights-api"),
    )
    return settings, store, tokens, request, client


def test_query_people_posts_expected_payload_and_maps_result(
    tmp_path: Path,
) -> None:
    response = FakeResponse(status=200, payload=_success_payload())
    settings, _, _, request, client = _client(tmp_path, response)

    result = client.query_people(
        PersonQueryRequest(
            identity_number="test-identity",
            name="",
            start_month="202601",
            end_month="202608",
        )
    )

    assert len(request.calls) == 1
    call = request.calls[0]
    url = urlsplit(str(call["url"]))
    login_url = urlsplit(settings.site.login_url)
    assert (url.scheme, url.netloc) == (login_url.scheme, login_url.netloc)
    assert url.path == settings.rights_api.query_common_path
    assert call["headers"] == {
        RightsApiContract.ACCESS_TOKEN_HEADER: "test-secret-token",
        "Accept": "application/json",
    }
    assert call["data"] == {
        "aac002": "TEST-IDENTITY",
        "aac003": "",
        "apiCode": RightsApiContract.QUERY_COMMON_API_CODE,
        "aaf001": None,
        "pageNumber": 1,
        "pageSize": settings.rights_api.page_size,
        "aae003s": "202601",
        "aae003e": "202608",
    }
    assert call["timeout"] == settings.rights_api.request_timeout_ms
    assert result.records[0].person_id == "test-person-id"
    assert result.records[0].identity_number == "test-identity"
    assert result.records[0].name == "测试人员"
    assert result.page.total_count == 1
    assert response.disposed is True


def test_generate_rights_bill_posts_expected_payload_and_decodes_pdf(
    tmp_path: Path,
) -> None:
    expected_pdf = b"%PDF-1.4\nunit test\n%%EOF"
    response = FakeResponse(
        status=200,
        payload=_print_success_payload(expected_pdf),
    )
    business_response = _business_no_response()
    settings, _, _, request, client = _client(
        tmp_path,
        [business_response, response],
    )
    print_request = RightsBillPrintRequest(
        start_month="202601",
        end_month="202608",
        insurance=InsuranceCode.UNEMPLOYMENT,
        person_ids=("person-1", "person-2"),
    )

    result = client.generate_rights_bill(print_request)

    assert result.content == expected_pdf
    assert result.insurance is InsuranceCode.UNEMPLOYMENT
    assert result.person_count == 2
    assert len(request.calls) == 2
    business_call = request.calls[0]
    business_url = urlsplit(str(business_call["url"]))
    assert business_url.path == settings.rights_api.acquire_business_no_path
    assert business_call["headers"] == {
        RightsApiContract.ACCESS_TOKEN_HEADER: "test-secret-token",
        "Accept": "application/json",
    }
    assert business_call["data"] == {
        "affairCode": RightsApiContract.RIGHTS_BILL_AFFAIR_CODE,
        "businessNo": "",
        "acceptType": RightsApiContract.RIGHTS_BILL_ACCEPT_TYPE,
    }
    assert business_call["timeout"] == settings.rights_api.request_timeout_ms
    call = request.calls[1]
    url = urlsplit(str(call["url"]))
    login_url = urlsplit(settings.site.login_url)
    assert (url.scheme, url.netloc) == (login_url.scheme, login_url.netloc)
    assert url.path == settings.rights_api.load_unit_rights_bill_path
    assert call["headers"] == {
        RightsApiContract.ACCESS_TOKEN_HEADER: "test-secret-token",
        "Accept": "application/json",
    }
    assert call["data"] == {
        "businessNo": _TEST_BUSINESS_NO,
        "queryStartYMprint": "202601",
        "queryEndYMprint": "202608",
        "insuranceCode": "210",
        "aab365": None,
        "personUniqueIdList": ["person-1", "person-2"],
    }
    assert call["timeout"] == settings.rights_api.request_timeout_ms
    assert business_response.disposed is True
    assert response.disposed is True


def test_print_timeout_returns_actionable_message(tmp_path: Path) -> None:
    settings, _, _, _, client = _client(
        tmp_path,
        [
            _business_no_response(),
            PlaywrightError("APIRequestContext.post: Timeout exceeded"),
        ],
    )

    with pytest.raises(RightsApiRequestError) as error:
        client.generate_rights_bill(
            RightsBillPrintRequest(
                "202601",
                "202608",
                InsuranceCode.PENSION,
                ("person-1",),
            )
        )

    assert settings.rights_api.request_timeout_ms == 30_000
    assert error.value.message == "权益单打印接口响应超时，请稍后再试"
    assert error.value.details is not None
    assert "请勿立即连续重复提交" in error.value.details


def test_print_diagnostic_exposes_request_and_response_without_token(
    tmp_path: Path,
) -> None:
    response = FakeResponse(
        status=200,
        payload={"appcode": "test-error", "msg": "非法操作", "map": {}},
    )
    settings, _, _, _, client = _client(
        tmp_path,
        [_business_no_response(), response],
    )
    diagnostics: list[str] = []
    client.diagnostic_callback = diagnostics.append

    with pytest.raises(RightsApiRequestError, match="非法操作"):
        client.generate_rights_bill(
            RightsBillPrintRequest(
                "202601",
                "202608",
                InsuranceCode.PENSION,
                ("person-1",),
            )
        )

    rendered = "\n".join(diagnostics)
    assert "流水号接口请求" in rendered
    assert settings.rights_api.acquire_business_no_path in rendered
    assert "流水号接口响应" in rendered
    assert "打印接口请求" in rendered
    assert settings.rights_api.load_unit_rights_bill_path in rendered
    assert _TEST_BUSINESS_NO in rendered
    assert '"insuranceCode": "110"' in rendered
    assert '"personUniqueIdList"' in rendered
    assert "<已脱敏>" in rendered
    assert "test-secret-token" not in rendered
    assert "打印接口响应" in rendered
    assert '"httpStatus": 200' in rendered
    assert "非法操作" in rendered


def test_download_rights_bill_saves_a_valid_pdf(tmp_path: Path) -> None:
    response = FakeResponse(status=200, payload=_print_success_payload())
    _, _, _, _, client = _client(
        tmp_path,
        [_business_no_response(), response],
    )

    destination = client.download_rights_bill(
        RightsBillPrintRequest(
            "202601",
            "202608",
            InsuranceCode.PENSION,
            ("person-1",),
        ),
        tmp_path / "downloads",
        "测试权益单.pdf",
    )

    assert destination.name == "测试权益单.pdf"
    assert destination.read_bytes().startswith(b"%PDF-")
    assert destination.read_bytes().endswith(b"%%EOF")


@pytest.mark.parametrize(
    ("insurance", "code"),
    [
        (InsuranceCode.PENSION, "110"),
        (InsuranceCode.WORK_INJURY, "410"),
        (InsuranceCode.UNEMPLOYMENT, "210"),
    ],
)
def test_insurance_enum_uses_platform_codes(
    insurance: InsuranceCode,
    code: str,
) -> None:
    assert insurance.value == code
    assert InsuranceCode.from_display_name(insurance.display_name) is insurance


def test_generate_rights_bill_rejects_print_business_error(
    tmp_path: Path,
) -> None:
    response = FakeResponse(
        status=200,
        payload={
            "appcode": "0",
            "msg": None,
            "map": {
                "pdf": None,
                "appCode": "-1",
                "errorMsg": "个人编号不能为空",
            },
        },
    )
    _, _, _, _, client = _client(
        tmp_path,
        [_business_no_response(), response],
    )

    with pytest.raises(RightsApiRequestError, match="个人编号不能为空"):
        client.generate_rights_bill(
            RightsBillPrintRequest(
                "202601",
                "202608",
                InsuranceCode.WORK_INJURY,
                ("invalid-person",),
            )
        )

    assert response.disposed is True


def test_generate_rights_bill_surfaces_business_no_api_error(
    tmp_path: Path,
) -> None:
    response = FakeResponse(
        status=200,
        payload={
            "appcode": "1",
            "msg": "您的请求出现错误,请稍后再试",
            "map": {},
        },
    )
    _, _, tokens, request, client = _client(tmp_path, response)

    with pytest.raises(RightsApiRequestError, match="请求出现错误"):
        client.generate_rights_bill(
            RightsBillPrintRequest(
                "202601",
                "202608",
                InsuranceCode.PENSION,
                ("person-1",),
            )
        )

    assert len(request.calls) == 1
    assert tokens.get_token() == "test-secret-token"
    assert response.disposed is True


@pytest.mark.parametrize("business_no", ["", "not-a-number", "123"])
def test_generate_rights_bill_rejects_invalid_business_no_response(
    tmp_path: Path,
    business_no: str,
) -> None:
    response = _business_no_response(business_no)
    _, _, _, request, client = _client(tmp_path, response)

    with pytest.raises(RightsApiRequestError, match="流水号格式错误"):
        client.generate_rights_bill(
            RightsBillPrintRequest(
                "202601",
                "202608",
                InsuranceCode.PENSION,
                ("person-1",),
            )
        )

    assert len(request.calls) == 1
    assert response.disposed is True


def test_print_request_structure_error_does_not_invalidate_token(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = FakeResponse(
        status=200,
        payload={
            "appcode": next(
                iter(RightsApiContract.AUTHENTICATION_FAILURE_APPCODES)
            ),
            "msg": "您的请求出现错误,请稍后再试",
            "map": {},
        },
    )
    _, _, tokens, _, client = _client(
        tmp_path,
        [_business_no_response(), response],
    )

    with pytest.raises(RightsApiRequestError, match="请求出现错误"):
        client.generate_rights_bill(
            RightsBillPrintRequest(
                "202601",
                "202608",
                InsuranceCode.PENSION,
                ("person-1",),
            )
        )

    assert tokens.get_token() == "test-secret-token"
    assert response.disposed is True


@pytest.mark.parametrize(
    ("encoded_pdf", "message"),
    [
        ("not-base64!", "Base64"),
        (base64.b64encode(b"not a pdf").decode("ascii"), "不是 PDF"),
        (base64.b64encode(b"%PDF-1.4 incomplete").decode("ascii"), "不完整"),
    ],
)
def test_generate_rights_bill_rejects_invalid_pdf_data(
    tmp_path: Path,
    encoded_pdf: str,
    message: str,
) -> None:
    response = FakeResponse(
        status=200,
        payload={"appcode": "0", "msg": None, "map": {"pdf": encoded_pdf}},
    )
    _, _, _, _, client = _client(
        tmp_path,
        [_business_no_response(), response],
    )

    with pytest.raises(RightsApiRequestError, match=message):
        client.generate_rights_bill(
            RightsBillPrintRequest(
                "202601",
                "202608",
                InsuranceCode.PENSION,
                ("person-1",),
            )
        )

    assert response.disposed is True


def test_print_request_rejects_empty_or_duplicate_person_ids() -> None:
    with pytest.raises(QueryValidationError, match="不能为空"):
        RightsBillPrintRequest(
            "202601",
            "202608",
            InsuranceCode.PENSION,
            (),
        ).to_payload(business_no=_TEST_BUSINESS_NO)

    with pytest.raises(QueryValidationError, match="不能重复"):
        RightsBillPrintRequest(
            "202601",
            "202608",
            InsuranceCode.PENSION,
            ("person-1", "person-1"),
        ).to_payload(business_no=_TEST_BUSINESS_NO)


def test_query_people_rejects_missing_access_token(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    request = FakeRequestContext(FakeResponse(status=200, payload={}))
    client = RightsStatementApiClient(
        settings,
        request,  # type: ignore[arg-type]
        AccessTokenManager("test-account", MemoryAccessTokenStore()),
        logging.getLogger("test.rights-api"),
    )

    with pytest.raises(AuthenticationFailedError, match="Access-Token"):
        client.query_people(
            PersonQueryRequest("test-identity", "202601", "202608")
        )

    assert request.calls == []


def test_query_people_invalidates_token_on_unauthorized(tmp_path: Path) -> None:
    response = FakeResponse(
        status=401,
        payload={"appcode": "test-auth-error", "msg": "登录状态失效"},
    )
    _, store, tokens, _, client = _client(tmp_path, response)

    with pytest.raises(AuthenticationFailedError, match="登录状态失效"):
        client.query_people(
            PersonQueryRequest("test-identity", "202601", "202608")
        )

    assert tokens.get_token() is None
    assert AccessTokenManager("test-account", store).get_token() is None
    assert response.disposed is True


def test_query_people_invalidates_token_on_authentication_appcode(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    response = FakeResponse(
        status=200,
        payload={
            "appcode": next(
                iter(RightsApiContract.AUTHENTICATION_FAILURE_APPCODES)
            ),
            "msg": RightsApiContract.AUTHENTICATION_FAILURE_MESSAGES[0],
            "map": {"path": settings.rights_api.query_common_path},
        },
    )
    _, store, tokens, _, client = _client(tmp_path, response)

    with pytest.raises(AuthenticationFailedError, match="Full authentication"):
        client.query_people(
            PersonQueryRequest("test-identity", "202601", "202608")
        )

    assert tokens.get_token() is None
    assert AccessTokenManager("test-account", store).get_token() is None
    assert response.disposed is True


def test_query_people_accepts_null_body_as_empty_result(tmp_path: Path) -> None:
    response = FakeResponse(
        status=200,
        payload={
            "appcode": "0",
            "msg": "",
            "map": {
                "result": {
                    "apiInfo": {
                        "apiCode": "test-api-code",
                        "pageNumber": "1",
                        "pageSize": "900",
                        "totalPage": 0,
                        "totalCount": 0,
                        "errorinfo": "未查询到信息",
                    },
                    "body": None,
                }
            },
        },
    )
    _, _, _, _, client = _client(tmp_path, response)

    result = client.query_people(
        PersonQueryRequest("test-identity", "202601", "202608")
    )

    assert result.records == ()
    assert result.page.page_size == 900
    assert result.page.total_page == 0
    assert result.page.total_count == 0
    assert result.page.error_info == "未查询到信息"
    assert response.disposed is True


def test_query_people_rejects_business_error(tmp_path: Path) -> None:
    response = FakeResponse(
        status=200,
        payload={"appcode": "test-error", "msg": "查询失败"},
    )
    _, _, _, _, client = _client(tmp_path, response)

    with pytest.raises(RightsApiRequestError, match="查询失败"):
        client.query_people(
            PersonQueryRequest("test-identity", "202601", "202608")
        )

    assert response.disposed is True


@pytest.mark.parametrize(
    ("start_month", "end_month", "message"),
    [
        ("20261", "202608", "YYYYMM"),
        ("202613", "202608", "01 到 12"),
        ("202609", "202608", "不能晚于"),
    ],
)
def test_person_query_validates_months(
    tmp_path: Path,
    start_month: str,
    end_month: str,
    message: str,
) -> None:
    _, _, _, request, client = _client(
        tmp_path,
        FakeResponse(status=200, payload=_success_payload()),
    )

    with pytest.raises(QueryValidationError, match=message):
        client.query_people(
            PersonQueryRequest(
                "test-identity",
                start_month,
                end_month,
            )
        )

    assert request.calls == []
