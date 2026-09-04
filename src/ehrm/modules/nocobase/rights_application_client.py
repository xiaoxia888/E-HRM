from __future__ import annotations

from datetime import datetime
import json
import logging
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import APIRequestContext, APIResponse
from playwright.sync_api import Error as PlaywrightError

from ehrm.core.settings import NocoBaseSettings
from ehrm.modules.nocobase.exceptions import NocoBaseRequestError
from ehrm.modules.nocobase.models import (
    NocoBasePageMeta,
    NocoBaseProblemType,
    NocoBaseRelatedPerson,
    NocoBaseRightsApplication,
    NocoBaseRightsApplicationDetail,
    NocoBaseRightsApplicationPage,
)
from ehrm.modules.nocobase.response import raise_for_nocobase_errors


class NocoBaseRightsApplicationClient:
    """Queries NocoBase social-security rights applications."""

    def __init__(
        self,
        settings: NocoBaseSettings,
        request: APIRequestContext,
        logger: logging.Logger,
    ) -> None:
        self.settings = settings
        self.request = request
        self.logger = logger

    def list_applications(
        self,
        authorization_token: str,
        *,
        page: int,
        page_size: int,
    ) -> NocoBaseRightsApplicationPage:
        if page < 1:
            raise ValueError("分页页码必须大于 0")
        if page_size < 1:
            raise ValueError("每页数量必须大于 0")
        token = authorization_token.strip()
        if not token:
            raise ValueError("NocoBase Authorization Token 不能为空")

        query_filter = {
            "$and": [
                {
                    "$and": [
                        {
                            "prob_type": {
                                "$eq": NocoBaseProblemType.SOCIAL_SECURITY_RIGHTS.value
                            }
                        }
                    ]
                }
            ]
        }
        try:
            response = self.request.get(
                self._url(self.settings.rights_application_list_path),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                params={
                    "filter": json.dumps(
                        query_filter,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "appends[]": "initiator_name",
                    "page": str(page),
                    "pageSize": str(page_size),
                    "tree": "false",
                },
                timeout=self.settings.request_timeout_ms,
            )
        except PlaywrightError as exc:
            raise NocoBaseRequestError(
                "NocoBase 权益申请分页查询失败",
                details=str(exc),
            ) from exc
        result = self._parse_response(response)
        self.logger.info(
            "NocoBase 权益申请查询成功 page=%s page_size=%s count=%s returned=%s",
            result.meta.page,
            result.meta.page_size,
            result.meta.count,
            len(result.records),
        )
        return result

    def get_application(
        self,
        authorization_token: str,
        application_id: int,
    ) -> NocoBaseRightsApplicationDetail:
        token = authorization_token.strip()
        if not token:
            raise ValueError("NocoBase Authorization Token 不能为空")
        if application_id < 1:
            raise ValueError("权益申请记录编号无效")
        query = urlencode(
            [
                ("appends[]", "createdBy"),
                ("appends[]", "initiator_name"),
                ("appends[]", "related_persons"),
                ("appends[]", "attachments"),
                ("filterByTk", str(application_id)),
            ]
        )
        url = f"{self._url(self.settings.rights_application_detail_path)}?{query}"
        try:
            response = self.request.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=self.settings.request_timeout_ms,
            )
        except PlaywrightError as exc:
            raise NocoBaseRequestError(
                "NocoBase 权益申请详情查询失败",
                details=str(exc),
            ) from exc
        result = self._parse_detail_response(response)
        self.logger.info(
            "NocoBase 权益申请详情查询成功 application_id=%s persons=%s",
            result.application_id,
            len(result.related_persons),
        )
        return result

    def _parse_response(
        self,
        response: APIResponse,
    ) -> NocoBaseRightsApplicationPage:
        try:
            try:
                payload: object = response.json()
            except Exception as exc:
                raise NocoBaseRequestError(
                    "NocoBase 权益申请接口返回了无法解析的数据",
                    details=type(exc).__name__,
                ) from exc
            raise_for_nocobase_errors(payload)
            if not 200 <= response.status < 300:
                raise NocoBaseRequestError(
                    f"NocoBase 权益申请接口返回 HTTP {response.status}"
                )
            if not isinstance(payload, dict):
                raise NocoBaseRequestError("NocoBase 权益申请响应结构错误")
            raw_records = payload.get("data")
            raw_meta = payload.get("meta")
            if not isinstance(raw_records, list) or not isinstance(raw_meta, dict):
                raise NocoBaseRequestError("NocoBase 权益申请响应缺少分页数据")
            records = tuple(
                self._record(item)
                for item in raw_records
                if isinstance(item, dict)
            )
            return NocoBaseRightsApplicationPage(
                records=records,
                meta=self._meta(raw_meta),
            )
        finally:
            response.dispose()

    def _parse_detail_response(
        self,
        response: APIResponse,
    ) -> NocoBaseRightsApplicationDetail:
        try:
            try:
                payload: object = response.json()
            except Exception as exc:
                raise NocoBaseRequestError(
                    "NocoBase 权益申请详情接口返回了无法解析的数据",
                    details=type(exc).__name__,
                ) from exc
            raise_for_nocobase_errors(payload)
            if not 200 <= response.status < 300:
                raise NocoBaseRequestError(
                    f"NocoBase 权益申请详情接口返回 HTTP {response.status}"
                )
            if not isinstance(payload, dict):
                raise NocoBaseRequestError("NocoBase 权益申请详情响应结构错误")
            raw_detail = payload.get("data")
            raw_meta = payload.get("meta")
            if not isinstance(raw_detail, dict):
                raise NocoBaseRequestError("NocoBase 权益申请详情响应缺少 data")
            allowed_actions: dict[str, tuple[int, ...]] = {}
            if isinstance(raw_meta, dict):
                allowed_actions = self._allowed_actions(
                    raw_meta.get("allowedActions")
                )
            return self._detail(raw_detail, allowed_actions)
        finally:
            response.dispose()

    @classmethod
    def _record(cls, payload: dict[str, object]) -> NocoBaseRightsApplication:
        application_id = cls._integer(payload.get("id"), "记录 id")
        initiator = payload.get("initiator_name")
        initiator_id = cls._optional_integer(payload.get("initiator_id"))
        initiator_label = ""
        if isinstance(initiator, dict):
            initiator_label = str(
                initiator.get("nickname") or initiator.get("username") or ""
            ).strip()
        return NocoBaseRightsApplication(
            application_id=application_id,
            code=str(payload.get("code") or "").strip(),
            status=str(payload.get("status") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            problem_type=str(payload.get("prob_type") or "").strip(),
            initiator_id=initiator_id,
            initiator_name=initiator_label,
            initiation_date=cls._date(payload.get("initiation_date")),
            estimate_time=cls._number(payload.get("estimate_time")),
            actual_time=cls._number(payload.get("actual_time")),
            estimate_date=cls._date(payload.get("estimate_date")),
            actual_date=cls._date(payload.get("actual_date")),
        )

    @classmethod
    def _meta(cls, payload: dict[str, object]) -> NocoBasePageMeta:
        return NocoBasePageMeta(
            count=cls._integer(payload.get("count", 0), "总记录数"),
            page=cls._integer(payload.get("page", 1), "当前页码"),
            page_size=cls._integer(payload.get("pageSize", 20), "每页数量"),
            total_page=cls._integer(payload.get("totalPage", 0), "总页数"),
            allowed_actions=cls._allowed_actions(payload.get("allowedActions")),
        )

    @classmethod
    def _detail(
        cls,
        payload: dict[str, object],
        allowed_actions: dict[str, tuple[int, ...]],
    ) -> NocoBaseRightsApplicationDetail:
        raw_people = payload.get("related_persons")
        people = tuple(
            cls._related_person(item)
            for item in (raw_people if isinstance(raw_people, list) else [])
            if isinstance(item, dict)
        )
        created_by = payload.get("createdBy")
        initiator = payload.get("initiator_name")
        attachments = payload.get("attachments")
        return NocoBaseRightsApplicationDetail(
            application_id=cls._integer(payload.get("id"), "记录 id"),
            code=str(payload.get("code") or "").strip(),
            status=str(payload.get("status") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            problem_type=str(payload.get("prob_type") or "").strip(),
            created_at=cls._date(payload.get("createdAt")),
            initiation_date=cls._date(payload.get("initiation_date")),
            estimate_time=cls._number(payload.get("estimate_time")),
            actual_time=cls._number(payload.get("actual_time")),
            estimate_date=cls._date(payload.get("estimate_date")),
            actual_date=cls._date(payload.get("actual_date")),
            created_by_name=cls._user_label(created_by),
            initiator_name=cls._user_label(initiator),
            problem_description=str(payload.get("problem_desc") or "").strip(),
            handling_method=str(payload.get("handling_method") or "").strip(),
            related_persons=people,
            attachment_names=tuple(
                name
                for item in (attachments if isinstance(attachments, list) else [])
                if (name := cls._attachment_name(item))
            ),
            allowed_actions=allowed_actions,
        )

    @classmethod
    def _related_person(cls, payload: dict[str, object]) -> NocoBaseRelatedPerson:
        return NocoBaseRelatedPerson(
            person_id=cls._integer(payload.get("id"), "申请人员 id"),
            status=str(payload.get("status") or "").strip(),
            insurance_type=str(payload.get("insurance_type") or "").strip(),
            start_month=cls._date(payload.get("start_month")),
            end_month=cls._date(payload.get("end_month")),
            identity_number=str(payload.get("id_card_no") or "").strip(),
            department=str(payload.get("department") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            company=str(payload.get("company") or "").strip(),
            print_group=str(payload.get("print_group") or "").strip(),
        )

    @classmethod
    def _allowed_actions(cls, value: object) -> dict[str, tuple[int, ...]]:
        actions: dict[str, tuple[int, ...]] = {}
        if not isinstance(value, dict):
            return actions
        for name, raw_ids in value.items():
            if not isinstance(raw_ids, list):
                continue
            actions[str(name)] = tuple(
                parsed
                for item in raw_ids
                if (parsed := cls._optional_integer(item)) is not None
            )
        return actions

    @staticmethod
    def _user_label(value: object) -> str:
        if not isinstance(value, dict):
            return ""
        return str(value.get("nickname") or value.get("username") or "").strip()

    @staticmethod
    def _attachment_name(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if not isinstance(value, dict):
            return ""
        return str(
            value.get("filename")
            or value.get("name")
            or value.get("title")
            or ""
        ).strip()

    @staticmethod
    def _date(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, bool):
            return 0.0
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _integer(cls, value: object, field_name: str) -> int:
        parsed = cls._optional_integer(value)
        if parsed is None:
            raise NocoBaseRequestError(f"NocoBase 权益申请{field_name}无效")
        return parsed

    def _url(self, path: str) -> str:
        parsed = urlsplit(self.settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise NocoBaseRequestError("NocoBase 服务地址配置错误")
        return f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"
