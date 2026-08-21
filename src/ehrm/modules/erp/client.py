from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib
import html
import json
import logging
import re
from typing import Callable, Iterable
from pathlib import Path
import uuid

from playwright.sync_api import APIRequestContext, APIResponse, Page

from ehrm.core.exceptions import (
    EhrmError,
    ErpApplicationAmbiguousError,
    ErpApplicationNotFoundError,
    ErpAttachmentAmbiguousError,
    ErpAttachmentNotFoundError,
    ErpAuthenticationFailedError,
    ErpDeleteFailedError,
    ErpDeleteVerificationError,
    ErpDuplicateAttachmentError,
    ErpQueryFailedError,
    ErpUploadFailedError,
    ErpUploadVerificationError,
    TaskCancelledError,
)
from ehrm.core.settings import ErpSettings
from ehrm.modules.erp.codec import ErpQueryCodec
from ehrm.modules.erp.file_validation import ErpUploadFileValidator
from ehrm.modules.erp.models import (
    ErpApplicationRecord,
    ErpAttachmentRecord,
    ErpPersonRecord,
    ErpTaskQueryResult,
    ErpTaskRecord,
    ErpTaskStatus,
)


_APPLICATION_CODE = re.compile(r"[A-Za-z0-9_-]{1,80}")
_PERSON_VIEW_KEYWORD = "View_NCC_HUM_HumanAccountCert"


class _ErpApiBase:
    def __init__(
        self,
        settings: ErpSettings,
        page: Page,
        request: APIRequestContext,
        logger: logging.Logger,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.page = page
        self.request = request
        self.logger = logger
        self.codec = ErpQueryCodec(page)
        self.cancel_check = cancel_check

    def _raise_if_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise TaskCancelledError("用户提前停止任务")

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "text/plain, */*; q=0.01",
            "Origin": self.settings.base_url,
            "Referer": self.settings.application_url,
            "X-Requested-With": "XMLHttpRequest",
        }

    def _json(
        self,
        response: APIResponse,
        *,
        operation: str,
        error_type: type[EhrmError] = ErpQueryFailedError,
    ) -> dict[str, object]:
        try:
            if "/Account/Login" in response.url or response.status in {401, 403}:
                self.logger.info(
                    "ERP 接口登录状态失效 operation=%s status=%s path=%s",
                    operation,
                    response.status,
                    response.url.split("?", 1)[0],
                )
                raise ErpAuthenticationFailedError(
                    f"ERP {operation}时登录状态已失效"
                )
            if not 200 <= response.status < 300:
                raise error_type(
                    f"ERP {operation}返回 HTTP {response.status}"
                )
            try:
                payload = response.json()
            except Exception as exc:
                raise error_type(
                    f"ERP {operation}返回了无法解析的数据",
                    details=type(exc).__name__,
                ) from exc
            if not isinstance(payload, dict):
                raise error_type(f"ERP {operation}响应结构错误")
            if payload.get("success") is False:
                message = payload.get("message")
                raise error_type(
                    str(message) if message else f"ERP {operation}失败"
                )
            return payload
        finally:
            response.dispose()

    @staticmethod
    def _records(
        payload: dict[str, object],
        *,
        operation: str,
        error_type: type[EhrmError] = ErpQueryFailedError,
    ) -> list[dict]:
        data = payload.get("data")
        value = data.get("value") if isinstance(data, dict) else None
        if isinstance(value, str):
            if not value.strip():
                return []
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise error_type(
                    f"ERP {operation}记录解析失败",
                    details=str(exc),
                ) from exc
        if not isinstance(value, list):
            raise error_type(f"ERP {operation}记录结构错误")
        return [item for item in value if isinstance(item, dict)]


class ErpApplicationClient(_ErpApiBase):
    def find_by_code(self, application_code: str) -> ErpApplicationRecord:
        code = application_code.strip()
        if not _APPLICATION_CODE.fullmatch(code):
            raise ErpQueryFailedError("ERP 申请编号格式不正确")

        plain_swhere = f" 1=1   and Code like '%{code}%'"
        encoded_swhere = self.codec.encode_swhere(plain_swhere)
        extparams = base64.b64encode(b'{"encodeswhere":"r4"}').decode("ascii")
        response = self.request.post(
            self._url("/Form/GridPageLoad"),
            form={
                "pageIndex": "0",
                "pageSize": "50",
                "sortField": "Code",
                "sortOrder": "Desc",
                "KeyWord": self.settings.business_keyword,
                "KeyWordType": "BO",
                "select": "",
                "swhere": encoded_swhere,
                "sort": "Code Desc",
                "index": "0",
                "size": "50",
                "extparams": extparams,
            },
            headers=self._headers(),
            timeout=self.settings.request_timeout_ms,
        )
        payload = self._json(response, operation="查询申请记录")
        records = self._records(payload, operation="查询申请记录")
        exact = [item for item in records if str(item.get("Code", "")) == code]
        if not exact:
            raise ErpApplicationNotFoundError(f"ERP 未找到申请编号：{code}")
        if len(exact) > 1:
            raise ErpApplicationAmbiguousError(f"ERP 申请编号不唯一：{code}")

        item = exact[0]
        record_id = str(item.get("ID", "")).strip()
        if not record_id:
            raise ErpQueryFailedError("ERP 查询结果缺少业务记录 ID")
        return ErpApplicationRecord(
            id=record_id,
            code=code,
            name=str(item.get("Name", "")),
            status=item.get("Status"),
        )


class ErpTaskClient(_ErpApiBase):
    """Queries the ERP human-resource transaction grid with pagination."""

    _MAX_TRANSACTION_TYPE_LENGTH = 50
    _MAX_PAGES = 10_000

    def query_by_transaction_type(
        self,
        transaction_type: str,
        *,
        page_size: int = 50,
    ) -> ErpTaskQueryResult:
        return self.query_tasks(
            transaction_type,
            page_size=page_size,
        )

    def query_tasks(
        self,
        transaction_type: str,
        *,
        status: int | ErpTaskStatus | None = None,
        statuses: Iterable[int | ErpTaskStatus] | None = None,
        application_code: str = "",
        start_date: str = "",
        end_date: str = "",
        page_size: int = 50,
    ) -> ErpTaskQueryResult:
        normalized_type = transaction_type.strip()
        if not normalized_type:
            raise ErpQueryFailedError("ERP 事务类型不能为空")
        if len(normalized_type) > self._MAX_TRANSACTION_TYPE_LENGTH:
            raise ErpQueryFailedError("ERP 事务类型长度不能超过 50 个字符")
        if any(ord(character) < 32 for character in normalized_type):
            raise ErpQueryFailedError("ERP 事务类型包含无效控制字符")
        if not 1 <= page_size <= 500:
            raise ErpQueryFailedError("ERP 分页大小必须在 1 至 500 之间")

        normalized_code = application_code.strip()
        if normalized_code and not _APPLICATION_CODE.fullmatch(normalized_code):
            raise ErpQueryFailedError("ERP 申请编号格式不正确")
        if status is not None and statuses:
            raise ErpQueryFailedError("ERP 单状态和多状态查询条件不能同时使用")
        raw_statuses = list(statuses or ())
        if status is not None:
            raw_statuses = [status]
        normalized_statuses: list[ErpTaskStatus] = []
        try:
            for raw_status in raw_statuses:
                normalized = ErpTaskStatus(raw_status)
                if normalized not in normalized_statuses:
                    normalized_statuses.append(normalized)
        except ValueError as exc:
            allowed = "、".join(str(item.value) for item in ErpTaskStatus)
            raise ErpQueryFailedError(
                f"ERP 申请状态无效，可选值：{allowed}"
            ) from exc
        normalized_status = (
            normalized_statuses[0] if len(normalized_statuses) == 1 else None
        )

        normalized_start, start_value = self._filter_date(
            start_date,
            label="开始日期",
        )
        normalized_end, end_value = self._filter_date(
            end_date,
            label="结束日期",
        )
        if start_value and end_value and start_value > end_value:
            raise ErpQueryFailedError("ERP 申请开始日期不能晚于结束日期")

        escaped_type = normalized_type.replace("'", "''")
        conditions = [f"ProbType = '{escaped_type}'"]
        if len(normalized_statuses) == 1:
            conditions.append(f"Status = {normalized_statuses[0].value}")
        elif normalized_statuses:
            values = ", ".join(str(item.value) for item in normalized_statuses)
            conditions.append(f"Status in ({values})")
        if normalized_code:
            conditions.append(f"Code = '{normalized_code}'")
        if start_value is not None:
            conditions.append(
                f"ProposedDate >= '{start_value.isoformat()} 00:00:00'"
            )
        if end_value is not None:
            if end_value == date.max:
                raise ErpQueryFailedError("ERP 申请结束日期超出支持范围")
            exclusive_end = end_value + timedelta(days=1)
            conditions.append(
                f"ProposedDate < '{exclusive_end.isoformat()} 00:00:00'"
            )
        plain_swhere = " 1=1   and " + "   and ".join(conditions)
        encoded_swhere = self.codec.encode_swhere(plain_swhere)
        extparams = base64.b64encode(b'{"encodeswhere":"r4"}').decode("ascii")

        records: list[ErpTaskRecord] = []
        seen_record_ids: set[str] = set()
        reported_total = 0
        pages_fetched = 0

        for page_index in range(self._MAX_PAGES):
            self._raise_if_cancelled()
            offset = page_index * page_size
            response = self.request.post(
                self._url("/Form/GridPageLoad"),
                form={
                    "pageIndex": str(page_index),
                    "pageSize": str(page_size),
                    "sortField": "Code",
                    "sortOrder": "Desc",
                    "KeyWord": self.settings.business_keyword,
                    "KeyWordType": "BO",
                    "select": "",
                    "swhere": encoded_swhere,
                    "sort": "Code Desc",
                    "index": str(offset),
                    "size": str(page_size),
                    "extparams": extparams,
                },
                headers=self._headers(),
                timeout=self.settings.request_timeout_ms,
            )
            payload = self._json(response, operation="按事务类型查询任务")
            self._raise_if_cancelled()
            page_records = self._records(payload, operation="按事务类型查询任务")
            pages_fetched += 1
            page_total = self._total_count(payload)
            if page_total is not None:
                reported_total = max(reported_total, page_total)

            new_records = 0
            for item in page_records:
                record = self._task_record(item, normalized_type)
                identity = record.id or record.code
                if identity and identity in seen_record_ids:
                    continue
                if identity:
                    seen_record_ids.add(identity)
                records.append(record)
                new_records += 1

            if not page_records:
                break
            if reported_total > 0 and len(records) >= reported_total:
                break
            if len(page_records) < page_size:
                break
            if new_records == 0:
                raise ErpQueryFailedError(
                    "ERP 分页查询没有继续向后翻页，请检查分页参数"
                )
        else:
            raise ErpQueryFailedError("ERP 分页查询超过最大页数限制")

        return ErpTaskQueryResult(
            transaction_type=normalized_type,
            records=tuple(records),
            total_count=max(reported_total, len(records)),
            pages_fetched=pages_fetched,
            status=normalized_status,
            statuses=tuple(normalized_statuses),
            application_code=normalized_code,
            start_date=normalized_start,
            end_date=normalized_end,
        )

    @staticmethod
    def _filter_date(value: str, *, label: str) -> tuple[str, date | None]:
        normalized = value.strip()
        if not normalized:
            return "", None
        try:
            parsed = date.fromisoformat(normalized)
        except ValueError as exc:
            raise ErpQueryFailedError(
                f"ERP 申请{label}格式不正确，请使用 YYYY-MM-DD"
            ) from exc
        return parsed.isoformat(), parsed

    @staticmethod
    def _total_count(payload: dict[str, object]) -> int | None:
        data = payload.get("data")
        raw_total = data.get("totalcount") if isinstance(data, dict) else None
        if raw_total is None:
            return None
        try:
            return max(0, int(raw_total))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _task_record(
        cls,
        item: dict[str, object],
        fallback_transaction_type: str,
    ) -> ErpTaskRecord:
        initiated_date = cls._date_text(
            item.get("ProposedDate") or item.get("RegDate")
        )
        description = cls._plain_text(
            item.get("ProbDescText") or item.get("ProbDesc") or ""
        )
        return ErpTaskRecord(
            id=str(item.get("ID") or item.get("Id") or "").strip(),
            code=str(item.get("Code") or "").strip(),
            initiated_date=initiated_date,
            title=str(item.get("Name") or "").strip(),
            description=description,
            transaction_type=str(
                item.get("ProbType") or fallback_transaction_type
            ).strip(),
            status=str(
                item.get("Status") if item.get("Status") is not None else ""
            ).strip(),
            originator=str(
                item.get("Originator") or item.get("RegHumName") or ""
            ).strip(),
            department=str(item.get("DeptName") or "").strip(),
        )

    @staticmethod
    def _date_text(value: object) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", text):
            return text[:10]
        return text

    @staticmethod
    def _plain_text(value: object) -> str:
        text = str(value or "")
        text = re.sub(r"(?i)<br\s*/?>|</p\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text).replace("\xa0", " ")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)


class ErpPersonClient(_ErpApiBase):
    """Queries the ERP personnel view captured in 查询人员信息.har."""

    _MAX_NAME_LENGTH = 100
    _IDENTITY_PATTERN = re.compile(r"^(?:\d{15}|\d{17}[0-9X])$")

    def query_by_name(self, name: str) -> tuple[ErpPersonRecord, ...]:
        self._raise_if_cancelled()
        normalized_name = name.strip()
        if not normalized_name:
            raise ErpQueryFailedError("ERP 人员姓名不能为空")
        if len(normalized_name) > self._MAX_NAME_LENGTH:
            raise ErpQueryFailedError("ERP 人员姓名长度不能超过 100 个字符")
        if any(ord(character) < 32 for character in normalized_name):
            raise ErpQueryFailedError("ERP 人员姓名包含无效控制字符")

        return self._query_exact(
            field="Name",
            value=normalized_name,
            operation="按姓名查询人员信息",
        )

    def query_by_identity_number(
        self,
        identity_number: str,
    ) -> tuple[ErpPersonRecord, ...]:
        self._raise_if_cancelled()
        normalized_identity = identity_number.strip().upper()
        if not self._IDENTITY_PATTERN.fullmatch(normalized_identity):
            raise ErpQueryFailedError("ERP 人员身份证号格式无效")
        return self._query_exact(
            field="IdCard",
            value=normalized_identity,
            operation="按身份证查询人员信息",
        )

    def _query_exact(
        self,
        *,
        field: str,
        value: str,
        operation: str,
    ) -> tuple[ErpPersonRecord, ...]:
        escaped_value = value.replace("'", "''")
        plain_swhere = f" 1=1   and {field} = '{escaped_value}'"
        encoded_swhere = self.codec.encode_swhere(plain_swhere)
        extparams = base64.b64encode(b'{"encodeswhere":"r4"}').decode("ascii")
        response = self.request.post(
            self._url("/Form/GridPageLoad"),
            form={
                "pageIndex": "0",
                "pageSize": "50",
                "sortField": "Code",
                "sortOrder": "Desc",
                "KeyWord": _PERSON_VIEW_KEYWORD,
                "KeyWordType": "ViewEntity",
                "select": "",
                "swhere": encoded_swhere,
                "sort": "Code Desc",
                "index": "0",
                "size": "50",
                "extparams": extparams,
            },
            headers=self._headers(),
            timeout=self.settings.request_timeout_ms,
        )
        payload = self._json(response, operation=operation)
        self._raise_if_cancelled()
        records = self._records(payload, operation=operation)
        response_field = "Name" if field == "Name" else "IdCard"
        exact = [
            item
            for item in records
            if str(item.get(response_field) or "").strip().upper()
            == value.upper()
        ]
        return tuple(self._person_record(item) for item in exact)

    @staticmethod
    def _person_record(item: dict[str, object]) -> ErpPersonRecord:
        status = item.get("Status")
        is_quit = item.get("IsQuit")
        return ErpPersonRecord(
            id=str(item.get("Id") or item.get("ID") or "").strip(),
            employee_code=str(item.get("Code") or "").strip(),
            name=str(item.get("Name") or "").strip(),
            identity_number=str(item.get("IdCard") or "").strip().upper(),
            department=str(
                item.get("DeptName") or item.get("ZDept") or ""
            ).strip(),
            company=str(
                item.get("ZUnit") or item.get("OwnProjName") or ""
            ).strip(),
            status=str(status if status is not None else "").strip(),
            is_quit=str(is_quit if is_quit is not None else "").strip(),
        )


class ErpAttachmentClient(_ErpApiBase):
    def upload(
        self,
        application: ErpApplicationRecord,
        file_path: Path,
    ) -> tuple[ErpAttachmentRecord, int]:
        validated = ErpUploadFileValidator().validate(file_path)
        path = validated.path
        file_hash = self._md5(path)
        self._ensure_not_duplicate(application, path.name, file_hash)
        storage_type = self._storage_type(error_type=ErpUploadFailedError)
        attachment, chunks = self._upload_chunks(
            application,
            path,
            file_hash,
            storage_type,
            validated.mime_type,
        )
        verified = self._find_uploaded_attachment(
            application,
            file_hash,
            path.stat().st_size,
        )
        if verified is None:
            raise ErpUploadVerificationError(
                f"ERP 未能在附件列表中确认文件：{path.name}"
            )
        resolved = verified if verified.id else attachment
        return resolved, chunks

    def find_by_filename(
        self,
        application: ErpApplicationRecord,
        filename: str,
    ) -> ErpAttachmentRecord:
        target = filename.strip()
        if not target:
            raise ErpAttachmentNotFoundError("待删除附件文件名不能为空")
        attachments = self._list_attachments(
            application,
            error_type=ErpDeleteFailedError,
        )
        matches = [
            item
            for item in attachments
            if self._full_filename(item).casefold() == target.casefold()
        ]
        if not matches:
            raise ErpAttachmentNotFoundError(
                f"申请 {application.code} 中不存在附件：{target}"
            )
        if len(matches) > 1:
            raise ErpAttachmentAmbiguousError(
                f"申请 {application.code} 中存在多个同名附件：{target}"
            )
        return matches[0]

    def delete(
        self,
        application: ErpApplicationRecord,
        attachment: ErpAttachmentRecord,
    ) -> ErpAttachmentRecord:
        if not attachment.id or attachment.folder_id != application.id:
            raise ErpDeleteFailedError("待删除附件与 ERP 申请记录不匹配")
        storage_type = self._storage_type(error_type=ErpDeleteFailedError)
        response = self.request.post(
            self._url("/PowerPlat/Control/File.ashx"),
            params={
                "_type": storage_type,
                "action": "delete",
                "_fileid": attachment.id,
            },
            headers=self._headers(),
            timeout=self.settings.request_timeout_ms,
        )
        self._json(
            response,
            operation="删除附件",
            error_type=ErpDeleteFailedError,
        )
        remaining = self._list_attachments(
            application,
            error_type=ErpDeleteVerificationError,
        )
        if any(item.id == attachment.id for item in remaining):
            raise ErpDeleteVerificationError(
                f"ERP 删除后附件仍然存在：{self._full_filename(attachment)}"
            )
        return attachment

    def _ensure_not_duplicate(
        self,
        application: ErpApplicationRecord,
        filename: str,
        file_hash: str,
    ) -> None:
        filename_payload = self._json(
            self.request.post(
                self._url("/UploadFle/IsExistFileName"),
                form={
                    "keyword": self.settings.business_keyword,
                    "keyvalue": application.id,
                    "filename": filename,
                },
                headers=self._headers(),
                timeout=self.settings.request_timeout_ms,
            ),
            operation="检查附件名称",
            error_type=ErpUploadFailedError,
        )
        if self._duplicate_data(filename_payload):
            raise ErpDuplicateAttachmentError(f"ERP 已存在同名附件：{filename}")

        hash_payload = self._json(
            self.request.post(
                self._url("/UploadFle/IsExistFilesHash"),
                form={"FilesHash": file_hash, "libid": ""},
                headers=self._headers(),
                timeout=self.settings.request_timeout_ms,
            ),
            operation="检查附件内容",
            error_type=ErpUploadFailedError,
        )
        if self._duplicate_data(hash_payload):
            raise ErpDuplicateAttachmentError("ERP 已存在内容相同的附件")

    def _storage_type(self, *, error_type: type[EhrmError]) -> str:
        payload = self._json(
            self.request.post(
                self._url("/UploadFle/GetLibType"),
                form={"LibId": self.settings.library_id},
                headers=self._headers(),
                timeout=self.settings.request_timeout_ms,
            ),
            operation="读取附件存储类型",
            error_type=error_type,
        )
        data = payload.get("data")
        value = data.get("Value") if isinstance(data, dict) else None
        return str(value or self.settings.storage_type)

    def _upload_chunks(
        self,
        application: ErpApplicationRecord,
        path: Path,
        file_hash: str,
        storage_type: str,
        mime_type: str,
    ) -> tuple[ErpAttachmentRecord, int]:
        total = path.stat().st_size
        chunk_size = self.settings.chunk_size_bytes
        if chunk_size <= 0:
            raise ErpUploadFailedError("ERP 上传分片大小配置无效")
        file_id = str(uuid.uuid4())
        last_table: dict[str, object] | None = None
        chunk_number = 0

        with path.open("rb") as stream:
            start = 0
            while start < total:
                buffer = stream.read(chunk_size)
                if not buffer:
                    break
                chunk_number += 1
                end = start + chunk_size
                response = self.request.post(
                    self._url("/PowerPlat/Control/File.ashx"),
                    params={
                        "_type": storage_type,
                        "action": "upload",
                        "serverPath": "",
                    },
                    multipart={
                        "KeyWord": self.settings.business_keyword,
                        "KeyValue": application.id,
                        "_FilesHash": file_hash,
                        "_start": str(start),
                        "_end": str(end),
                        "_fileid": file_id,
                        "FileData": {
                            "name": path.name,
                            "mimeType": mime_type,
                            "buffer": buffer,
                        },
                        "_total": str(total),
                        "_chunk": str(chunk_number),
                        "_filename": path.name,
                    },
                    headers=self._headers(),
                    timeout=self.settings.request_timeout_ms,
                )
                payload = self._json(
                    response,
                    operation=f"上传附件第 {chunk_number} 片",
                    error_type=ErpUploadFailedError,
                )
                data = payload.get("data")
                table = data.get("table") if isinstance(data, dict) else None
                if isinstance(table, dict):
                    last_table = table
                start += len(buffer)

        if chunk_number == 0 or last_table is None:
            raise ErpUploadFailedError("ERP 上传响应缺少附件信息")
        return self._attachment(last_table), chunk_number

    def _find_uploaded_attachment(
        self,
        application: ErpApplicationRecord,
        file_hash: str,
        file_size: int,
    ) -> ErpAttachmentRecord | None:
        attachments = self._list_attachments(
            application,
            error_type=ErpUploadVerificationError,
        )
        for item in attachments:
            if (
                item.folder_id == application.id
                and item.md5.lower() == file_hash.lower()
                and item.size == file_size
            ):
                return item
        return None

    def _list_attachments(
        self,
        application: ErpApplicationRecord,
        *,
        error_type: type[EhrmError],
    ) -> list[ErpAttachmentRecord]:
        encoded_swhere = self.codec.encode_swhere(" 1=1 ")
        response = self.request.get(
            self._url("/Form/GetDocFiles"),
            params={
                "BOKeyWord": self.settings.business_keyword,
                "BOKeyValue": application.id,
                "select": "",
                "swhere": encoded_swhere,
                "sort": "",
                "index": "0",
                "size": "0",
            },
            headers=self._headers(),
            timeout=self.settings.request_timeout_ms,
        )
        payload = self._json(
            response,
            operation="验证附件列表",
            error_type=error_type,
        )
        records = self._records(
            payload,
            operation="验证附件列表",
            error_type=error_type,
        )
        return [self._attachment(item) for item in records]

    @staticmethod
    def _duplicate_data(payload: dict[str, object]) -> bool:
        value = payload.get("data")
        if isinstance(value, dict) and set(value) == {"data"}:
            value = value.get("data")
        return bool(value)

    @staticmethod
    def _md5(path: Path) -> str:
        digest = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _attachment(item: dict[str, object]) -> ErpAttachmentRecord:
        return ErpAttachmentRecord(
            id=str(item.get("Id", "")),
            folder_id=str(item.get("FolderId", "")),
            name=str(item.get("Name", "")),
            extension=str(item.get("FileExt", "")),
            size=int(item.get("FileSize", 0)),
            md5=str(item.get("FilesHash", "")),
            server_url=str(item.get("ServerUrl", "")),
        )

    @staticmethod
    def _full_filename(attachment: ErpAttachmentRecord) -> str:
        if attachment.extension and attachment.name.lower().endswith(
            attachment.extension.lower()
        ):
            return attachment.name
        return f"{attachment.name}{attachment.extension}"
