"""Minimal source-only NocoBase API adapter; never writes associations."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import NocoBaseSettings
from ehrm.modules.nocobase.exceptions import NocoBaseRequestError
from ehrm.modules.nocobase.response import raise_for_nocobase_errors
from ehrm.modules.nocobase.rights_application_client import NocoBaseRightsApplicationClient


class NocoBaseSyncClient:
    def __init__(self, settings: NocoBaseSettings, request, api_key: str) -> None:
        self.settings = settings
        self.request = request
        self._key = api_key

    def _call(self, path: str, *, values: dict | None = None, params: dict | None = None):
        parsed = urlsplit(self.settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise NocoBaseRequestError("NocoBase 服务地址配置错误")
        response = None
        try:
            # 不带 form-submit 业务规则、不带 updateAssociationValues，避免改动关联人员。
            response = self.request.fetch(
                self.settings.base_url.rstrip("/") + "/" + path.lstrip("/"),
                method="GET" if values is None else "POST",
                headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"},
                params=params or {},
                max_redirects=0,
                **({"data": values} if values is not None else {}),
                timeout=self.settings.request_timeout_ms,
            )
            NocoBaseRightsApplicationClient._check_access_status(response)
            payload = response.json()
            raise_for_nocobase_errors(payload)
            if not 200 <= response.status < 300:
                raise NocoBaseRequestError(f"NocoBase 同步请求返回 HTTP {response.status}")
            if not isinstance(payload, dict) or "data" not in payload:
                raise NocoBaseRequestError("NocoBase 同步响应缺少 data")
            return payload
        except EhrmError as exc:
            raise type(exc)(exc.message.replace(self._key, "[已隐藏]")) from None
        except Exception as exc:
            # 不回显服务端响应、授权头或申请原文；网络失败不自动重试写入。
            raise NocoBaseRequestError("NocoBase 同步请求失败", details=type(exc).__name__) from None
        finally:
            if response is not None:
                response.dispose()

    def _list(self, path: str, query_filter: dict) -> list[dict]:
        payload = self._call(path, params={
            "filter": json.dumps(query_filter, ensure_ascii=False),
            "page": "1", "pageSize": "2", "tree": "false",
        })
        records = payload["data"]
        meta = payload.get("meta")
        if not isinstance(records, list) or not isinstance(meta, dict):
            raise NocoBaseRequestError("NocoBase 查重响应结构错误")
        if any(not isinstance(item, dict) for item in records):
            raise NocoBaseRequestError("NocoBase 查重记录格式错误")
        count = NocoBaseRightsApplicationClient._integer(meta.get("count"), "总记录数")
        # 匹配数用于判断重名/重复，不能只看第一页记录数。
        if count > len(records) and len(records) < 2:
            raise NocoBaseRequestError("NocoBase 查重响应记录数不完整")
        return records

    def find_application(self, erp_id: str) -> dict | None:
        matches = self._list(self.settings.rights_application_list_path, {"key_value": {"$eq": erp_id}})
        if len(matches) > 1:
            raise NocoBaseRequestError("同一 ERP 原始 ID 已存在多条申请，请人工处理重复记录")
        return matches[0] if matches else None

    def find_user(self, name: str) -> tuple[int | None, str]:
        if not name:
            return None, "ERP 发起人为空，未关联用户"
        matches = self._list(self.settings.users_list_path, {"nickname": {"$eq": name}})
        if len(matches) != 1:
            return None, "发起人未匹配或存在同名用户，未关联用户"
        return NocoBaseRightsApplicationClient._integer(matches[0].get("id"), "用户 id"), ""

    def create(self, values: dict) -> dict:
        return self._write_result(self._call(self.settings.application_create_path, values=values))

    def update(self, record_id: int, values: dict) -> dict:
        if record_id < 1:
            raise ValueError("NocoBase 申请 ID 无效")
        return self._write_result(self._call(
            self.settings.application_update_path, values=values, params={"filterByTk": str(record_id)}
        ))

    @staticmethod
    def _write_result(payload: dict) -> dict:
        data = payload["data"]
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        if not isinstance(data, dict):
            raise NocoBaseRequestError("NocoBase 写入响应未返回唯一记录")
        NocoBaseRightsApplicationClient._integer(data.get("id"), "记录 id")
        return data
