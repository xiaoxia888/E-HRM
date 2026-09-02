from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import APIRequestContext, APIResponse
from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.access_token import AccessTokenManager
from ehrm.browser.download import DownloadManager
from ehrm.core.exceptions import (
    AuthenticationFailedError,
    RightsApiRequestError,
)
from ehrm.core.settings import AppSettings
from ehrm.modules.rights_statement.api_contract import RightsApiContract
from ehrm.modules.rights_statement.api_models import (
    InsuranceCode,
    PersonQueryRequest,
    PersonQueryResult,
    PersonRecord,
    QueryPageInfo,
    RightsBillPdf,
    RightsBillPrintRequest,
)


class RightsStatementApiClient:
    """Calls authenticated rights-statement APIs without driving page controls."""

    def __init__(
        self,
        settings: AppSettings,
        request: APIRequestContext,
        access_tokens: AccessTokenManager,
        logger: logging.Logger,
        download_manager: DownloadManager | None = None,
        diagnostic_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.request = request
        self.access_tokens = access_tokens
        self.logger = logger
        self.download_manager = download_manager or DownloadManager()
        self.diagnostic_callback = diagnostic_callback

    def query_people(self, query: PersonQueryRequest) -> PersonQueryResult:
        payload = query.to_payload(
            api_code=RightsApiContract.QUERY_COMMON_API_CODE,
            default_page_size=self.settings.rights_api.page_size,
        )
        token = self.access_tokens.get_token()
        if not token:
            raise AuthenticationFailedError(
                "未找到智慧人社 Access-Token",
                details="请重新完成一次账号密码登录和安全验证",
            )

        url = self._url(self.settings.rights_api.query_common_path)
        try:
            response = self.request.post(
                url,
                headers={
                    RightsApiContract.ACCESS_TOKEN_HEADER: token,
                    "Accept": "application/json",
                },
                data=payload,
                timeout=self.settings.rights_api.request_timeout_ms,
            )
        except PlaywrightError as exc:
            raise RightsApiRequestError(
                "人员信息查询请求失败",
                details=str(exc),
            ) from exc

        result = self._parse_query_response(response)
        self.logger.info(
            "智慧人社人员接口查询完成 count=%s page=%s/%s",
            len(result.records),
            result.page.page_number,
            result.page.total_page,
        )
        return result

    def generate_rights_bill(
        self,
        print_request: RightsBillPrintRequest,
    ) -> RightsBillPdf:
        """Generates one PDF for the selected people through the print API."""
        token = self.access_tokens.get_token()
        if not token:
            raise AuthenticationFailedError(
                "未找到智慧人社 Access-Token",
                details="请重新完成一次账号密码登录和安全验证",
            )
        business_no = self._acquire_business_no(token)
        payload = print_request.to_payload(business_no=business_no)
        self.logger.info(
            "准备调用智慧人社权益单打印接口 business_no=%s insurance=%s person_count=%s",
            business_no,
            print_request.insurance.display_name,
            len(payload["personUniqueIdList"]),
        )

        url = self._url(self.settings.rights_api.load_unit_rights_bill_path)
        self._emit_diagnostic(
            "打印接口请求",
            {
                "method": "POST",
                "url": url,
                "headers": {
                    RightsApiContract.ACCESS_TOKEN_HEADER: "<已脱敏>",
                    "Accept": "application/json",
                },
                "body": payload,
            },
        )
        started_at = time.monotonic()
        try:
            response = self.request.post(
                url,
                headers={
                    RightsApiContract.ACCESS_TOKEN_HEADER: token,
                    "Accept": "application/json",
                },
                data=payload,
                timeout=self.settings.rights_api.request_timeout_ms,
            )
        except PlaywrightError as exc:
            elapsed_seconds = time.monotonic() - started_at
            details = str(exc)
            self.logger.error(
                "智慧人社权益单打印请求异常 elapsed=%.3fs path=%s error_type=%s error=%s",
                elapsed_seconds,
                self.settings.rights_api.load_unit_rights_bill_path,
                type(exc).__name__,
                details,
            )
            if "timeout" in details.casefold():
                raise RightsApiRequestError(
                    "权益单打印接口响应超时，请稍后再试",
                    details=(
                        f"请求异常等待 {elapsed_seconds:.1f} 秒后终止；"
                        "请勿立即连续重复提交，以免触发请求频率限制"
                    ),
                ) from exc
            raise RightsApiRequestError(
                "权益单打印请求失败",
                details=details,
            ) from exc

        result = self._parse_print_response(
            response,
            insurance=print_request.insurance,
            person_count=sum(
                bool(person_id.strip())
                for person_id in print_request.person_ids
            ),
        )
        self.logger.info(
            "智慧人社权益单生成完成 insurance=%s person_count=%s bytes=%s",
            result.insurance.display_name,
            result.person_count,
            len(result.content),
        )
        return result

    def download_rights_bill(
        self,
        print_request: RightsBillPrintRequest,
        output_dir: Path,
        filename: str,
    ) -> Path:
        """Generates, validates and saves a rights-statement PDF."""
        result = self.generate_rights_bill(print_request)
        return self.download_manager.save_bytes(
            result.content,
            output_dir,
            filename,
        )

    def _acquire_business_no(self, token: str) -> str:
        payload = {
            "affairCode": RightsApiContract.RIGHTS_BILL_AFFAIR_CODE,
            "businessNo": "",
            "acceptType": RightsApiContract.RIGHTS_BILL_ACCEPT_TYPE,
        }
        url = self._url(self.settings.rights_api.acquire_business_no_path)
        self._emit_diagnostic(
            "流水号接口请求",
            {
                "method": "POST",
                "url": url,
                "headers": {
                    RightsApiContract.ACCESS_TOKEN_HEADER: "<已脱敏>",
                    "Accept": "application/json",
                },
                "body": payload,
            },
        )
        try:
            response = self.request.post(
                url,
                headers={
                    RightsApiContract.ACCESS_TOKEN_HEADER: token,
                    "Accept": "application/json",
                },
                data=payload,
                timeout=self.settings.rights_api.request_timeout_ms,
            )
        except PlaywrightError as exc:
            raise RightsApiRequestError(
                "打印业务流水号请求失败",
                details=str(exc),
            ) from exc
        business_no = self._parse_business_no_response(response)
        self.logger.info(
            "智慧人社打印业务流水号获取成功 business_no=%s",
            business_no,
        )
        return business_no

    def _parse_business_no_response(self, response: APIResponse) -> str:
        try:
            payload: object = {}
            parse_error: Exception | None = None
            try:
                payload = response.json()
            except Exception as exc:
                parse_error = exc

            response_payload = payload if isinstance(payload, dict) else {}
            self._emit_diagnostic(
                "流水号接口响应",
                {
                    "httpStatus": response.status,
                    "body": response_payload,
                    **(
                        {"parseError": type(parse_error).__name__}
                        if parse_error is not None
                        else {}
                    ),
                },
            )
            appcode = str(response_payload.get("appcode") or "").strip()
            message = str(response_payload.get("msg") or "").strip()
            if self._is_authentication_failure(
                response.status,
                appcode,
                message,
            ):
                self._invalidate_token()
                raise AuthenticationFailedError(
                    message or "智慧人社 Access-Token 已失效",
                    details=f"HTTP={response.status}，appcode={appcode or '无'}",
                )
            if not 200 <= response.status < 300:
                raise RightsApiRequestError(
                    message or f"打印业务流水号返回 HTTP {response.status}",
                    details=f"appcode={appcode or '无'}",
                )
            if parse_error is not None:
                raise RightsApiRequestError(
                    "打印业务流水号接口返回了无法解析的数据",
                    details=type(parse_error).__name__,
                ) from parse_error
            if not isinstance(payload, dict):
                raise RightsApiRequestError("打印业务流水号响应结构错误")
            if appcode != "0":
                raise RightsApiRequestError(
                    message or "打印业务流水号获取失败",
                    details=f"appcode={appcode or '无'}",
                )
            if not message.isdigit() or len(message) != 16:
                raise RightsApiRequestError(
                    "打印业务流水号格式错误",
                    details=f"msg={message or '空'}",
                )
            return message
        finally:
            response.dispose()

    def _parse_query_response(self, response: APIResponse) -> PersonQueryResult:
        try:
            payload: object = {}
            parse_error: Exception | None = None
            try:
                payload = response.json()
            except Exception as exc:
                parse_error = exc

            response_payload = payload if isinstance(payload, dict) else {}
            appcode = str(response_payload.get("appcode") or "").strip()
            message = str(response_payload.get("msg") or "").strip()
            authentication_failed = self._is_authentication_failure(
                response.status,
                appcode,
                message,
            )
            if authentication_failed:
                self._invalidate_token()
                raise AuthenticationFailedError(
                    message or "智慧人社 Access-Token 已失效",
                    details=f"HTTP={response.status}，appcode={appcode or '无'}",
                )
            if not 200 <= response.status < 300:
                raise RightsApiRequestError(
                    message or f"人员信息查询返回 HTTP {response.status}",
                    details=f"appcode={appcode or '无'}",
                )
            if parse_error is not None:
                raise RightsApiRequestError(
                    "人员信息查询接口返回了无法解析的数据",
                    details=type(parse_error).__name__,
                ) from parse_error
            if not isinstance(payload, dict):
                raise RightsApiRequestError("人员信息查询响应结构错误")
            if appcode != "0":
                raise RightsApiRequestError(
                    message or "人员信息查询失败",
                    details=f"appcode={appcode or '无'}",
                )
            return self._result(response_payload)
        finally:
            response.dispose()

    def _parse_print_response(
        self,
        response: APIResponse,
        *,
        insurance: InsuranceCode,
        person_count: int,
    ) -> RightsBillPdf:
        try:
            payload: object = {}
            parse_error: Exception | None = None
            try:
                payload = response.json()
            except Exception as exc:
                parse_error = exc

            response_payload = payload if isinstance(payload, dict) else {}
            self._emit_diagnostic(
                "打印接口响应",
                {
                    "httpStatus": response.status,
                    "body": self._summarize_pdf(response_payload),
                    **(
                        {"parseError": type(parse_error).__name__}
                        if parse_error is not None
                        else {}
                    ),
                },
            )
            appcode = str(response_payload.get("appcode") or "").strip()
            message = str(response_payload.get("msg") or "").strip()
            authentication_failed = self._is_authentication_failure(
                response.status,
                appcode,
                message,
            )
            if authentication_failed:
                self._invalidate_token()
                raise AuthenticationFailedError(
                    message or "智慧人社 Access-Token 已失效",
                    details=f"HTTP={response.status}，appcode={appcode or '无'}",
                )
            if not 200 <= response.status < 300:
                raise RightsApiRequestError(
                    message or f"权益单打印返回 HTTP {response.status}",
                    details=f"appcode={appcode or '无'}",
                )
            if parse_error is not None:
                raise RightsApiRequestError(
                    "权益单打印接口返回了无法解析的数据",
                    details=type(parse_error).__name__,
                ) from parse_error
            if not isinstance(payload, dict):
                raise RightsApiRequestError("权益单打印响应结构错误")
            if appcode != "0":
                raise RightsApiRequestError(
                    message or "权益单打印失败",
                    details=f"appcode={appcode or '无'}",
                )

            response_map = payload.get("map")
            if not isinstance(response_map, dict):
                raise RightsApiRequestError("权益单打印响应缺少 map")
            encoded_pdf = response_map.get("pdf")
            if not isinstance(encoded_pdf, str) or not encoded_pdf.strip():
                business_code = str(response_map.get("appCode") or "").strip()
                error_message = str(response_map.get("errorMsg") or "").strip()
                raise RightsApiRequestError(
                    error_message or "权益单打印接口未返回 PDF",
                    details=f"appCode={business_code or '无'}",
                )
            content = self._decode_pdf(encoded_pdf)
            return RightsBillPdf(
                content=content,
                insurance=insurance,
                person_count=person_count,
            )
        finally:
            response.dispose()

    @staticmethod
    def _decode_pdf(encoded_pdf: str) -> bytes:
        try:
            content = base64.b64decode(encoded_pdf.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RightsApiRequestError(
                "权益单打印接口返回的 PDF Base64 无效"
            ) from exc
        if not content.startswith(b"%PDF-"):
            raise RightsApiRequestError(
                "权益单打印接口返回的内容不是 PDF"
            )
        if b"%%EOF" not in content[-4_096:]:
            raise RightsApiRequestError(
                "权益单打印接口返回的 PDF 不完整"
            )
        return content

    @classmethod
    def _result(cls, payload: dict[str, object]) -> PersonQueryResult:
        response_map = payload.get("map")
        result = (
            response_map.get("result")
            if isinstance(response_map, dict)
            else None
        )
        if not isinstance(result, dict):
            raise RightsApiRequestError("人员信息查询响应缺少 map.result")
        api_info = result.get("apiInfo")
        body = result.get("body")
        if not isinstance(api_info, dict):
            raise RightsApiRequestError("人员信息查询响应缺少 apiInfo")
        default_total_count = len(body) if isinstance(body, list) else 0
        total_count = cls._integer(
            api_info,
            "totalCount",
            default=default_total_count,
        )
        if body is None and total_count == 0:
            body = []
        if not isinstance(body, list):
            raise RightsApiRequestError("人员信息查询响应 body 结构错误")

        records: list[PersonRecord] = []
        for index, item in enumerate(body, start=1):
            if not isinstance(item, dict):
                raise RightsApiRequestError(
                    "人员信息查询记录结构错误",
                    details=f"第 {index} 条记录不是对象",
                )
            person_id = str(item.get("bac001") or "").strip()
            if not person_id:
                raise RightsApiRequestError(
                    "人员信息查询记录缺少 bac001",
                    details=f"第 {index} 条记录",
                )
            records.append(
                PersonRecord(
                    person_id=person_id,
                    identity_number=str(item.get("aac002") or "").strip(),
                    name=str(item.get("aac003") or "").strip(),
                )
            )

        page = QueryPageInfo(
            api_code=str(api_info.get("apiCode") or "").strip(),
            page_number=cls._integer(api_info, "pageNumber", default=1),
            page_size=cls._integer(api_info, "pageSize", default=len(records)),
            total_page=cls._integer(api_info, "totalPage", default=1),
            total_count=total_count,
            error_info=(
                str(api_info.get("errorinfo")).strip()
                if api_info.get("errorinfo") is not None
                else None
            ),
        )
        return PersonQueryResult(page=page, records=tuple(records))

    @staticmethod
    def _integer(
        payload: dict[str, object],
        key: str,
        *,
        default: int,
    ) -> int:
        value = payload.get(key)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RightsApiRequestError(
                "人员信息查询分页信息错误",
                details=f"{key}={value!r}",
            ) from exc

    def _url(self, path: str) -> str:
        login = urlsplit(self.settings.site.login_url)
        return urlunsplit((login.scheme, login.netloc, path, "", ""))

    def _emit_diagnostic(
        self,
        label: str,
        payload: dict[str, object],
    ) -> None:
        if self.diagnostic_callback is None:
            return
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        self.diagnostic_callback(f"{label}：\n{rendered}")

    @staticmethod
    def _summarize_pdf(payload: dict[str, object]) -> dict[str, object]:
        summarized = dict(payload)
        response_map = summarized.get("map")
        if not isinstance(response_map, dict):
            return summarized
        summarized_map = dict(response_map)
        encoded_pdf = summarized_map.get("pdf")
        if isinstance(encoded_pdf, str) and encoded_pdf:
            summarized_map["pdf"] = (
                f"<Base64 PDF，长度 {len(encoded_pdf)} 字符>"
            )
        summarized["map"] = summarized_map
        return summarized

    def _is_authentication_failure(
        self,
        status: int,
        appcode: str,
        message: str,
    ) -> bool:
        return RightsApiContract.is_authentication_failure(
            http_status=status,
            appcode=appcode,
            message=message,
        )

    def _invalidate_token(self) -> None:
        try:
            self.access_tokens.invalidate()
        except Exception:
            self.logger.exception("清除失效的智慧人社 Access-Token 失败")
