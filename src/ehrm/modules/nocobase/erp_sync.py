"""ERP source synchronization without AI classification or personnel extraction."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ehrm.core.exceptions import EhrmError, TaskCancelledError
from ehrm.modules.erp.models import ErpTaskRecord
from ehrm.modules.nocobase.exceptions import NocoBaseApiKeyInvalidError, NocoBasePermissionDeniedError
from ehrm.modules.nocobase.exceptions import NocoBaseRequestError


class SyncIdentityError(NocoBaseRequestError):
    """Stop scheduling if remote identity rules could defeat idempotency."""


TRANSACTION_TYPES = ("社保咨询", "单位社保权益单")
TYPE_VALUES = {"社保咨询": "social_security_consult", "单位社保权益单": "social_security_rights"}


def source_snapshot(record: ErpTaskRecord) -> dict:
    # 原始响应保留完整字段，同时补上规范化字段用于稳定比较与人工追溯。
    return {**record.raw_data, "ID": record.id, "Code": record.code,
            "Name": record.title, "ProbDescText": record.description,
            "ProposedDate": record.initiated_date, "ProbType": record.transaction_type}


def source_changed(record: ErpTaskRecord, target: dict) -> bool:
    previous = target.get("erp_all_field_value")
    if isinstance(previous, dict):
        values = (previous.get("Name"), previous.get("ProbDescText"),
                  str(previous.get("ProposedDate") or "")[:10])
    else:
        initiation = str(target.get("initiation_date") or "")
        if "T" in initiation:
            try:
                parsed = datetime.fromisoformat(initiation.replace("Z", "+00:00"))
                if parsed.tzinfo:
                    initiation = parsed.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            except ValueError:
                pass
        values = (target.get("title"), target.get("problem_desc"),
                  initiation[:10])
    # 只比较用户约定的三个来源字段，不因办理状态、updatedAt 或人员变更而覆盖。
    return values != (record.title, record.description, record.initiated_date)


class ErpNocoBaseSync:
    def __init__(self, erp, target) -> None:
        self.erp = erp
        self.target = target

    def run(self, *, start_date: str, end_date: str, credentials=None, context=None, dry_run: bool = False) -> dict:
        records = self.fetch_records(start_date=start_date, end_date=end_date, credentials=credentials, context=context)
        return self.sync_records(records, start_date=start_date, end_date=end_date, context=context, dry_run=dry_run)

    def fetch_records(self, *, start_date: str, end_date: str, credentials=None, context=None) -> tuple:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        records = {}
        for transaction_type in TRANSACTION_TYPES:
            if context:
                context.report(f"正在获取 ERP {transaction_type}")
            result = self.erp.query_tasks(transaction_type, start_date=start_date,
                                          end_date=end_date, credentials=credentials)
            for item in result.records:
                # 缺少 ID 的记录也要显示错误，不能降级按编号猜测是否同一申请。
                identity = item.id.strip().casefold() if item.id.strip() else (item.code, item.title)
                records[identity] = item
        return tuple(records.values())

    def sync_records(self, records, *, start_date: str, end_date: str, context=None, dry_run: bool = False) -> dict:
        summary = {"total": len(records), "created": 0, "updated": 0, "unchanged": 0, "failed": 0}
        summary.update(would_create=0, would_update=0)
        items = []
        user_cache = {}
        def save_outcome(outcome, index):
            items.append(outcome)
            if context:
                labels = {"created": "已新增", "updated": "已更新", "unchanged": "未变化，跳过",
                          "would_create": "预计新增（不写入）", "would_update": "预计更新（不写入）", "failed": "失败"}
                detail = outcome.get("error") or outcome.get("warning") or ""
                context.report(f"{outcome['application_code']}：{labels[outcome['action']]}" + (f"；{detail}" if detail else ""),
                               current=index, total=len(records))
        for index, record in enumerate(records, 1):
            if context:
                context.report(f"正在同步 {record.code}", current=index, total=len(records))
            outcome = {"application_code": record.code, "erp_record_id": record.id}
            try:
                if not record.id.strip() or not record.code.strip():
                    raise ValueError("ERP 申请缺少原始 ID 或申请编号，未同步")
                if record.transaction_type not in TYPE_VALUES:
                    raise ValueError("ERP 事务类型不在本次同步范围，未同步")
                initiation = datetime.combine(date.fromisoformat(record.initiated_date), time(), ZoneInfo("Asia/Shanghai"))
                existing = self.target.find_application(record.id)
                if existing is not None and existing.get("key_value") != record.id:
                    raise SyncIdentityError(f"NocoBase 记录 {existing.get('id')} 的 key_value 与 ERP 原始 ID 不一致，自动同步已停止")
                if existing is not None and not source_changed(record, existing) and existing.get("erp_code") == record.code:
                    summary["unchanged"] += 1
                    save_outcome({**outcome, "action": "unchanged", "nocobase_id": existing["id"]}, index)
                    continue
                # 更新绝不带 status、handling_method、人员、附件或 createdBy/updatedBy。
                # code 属于 NocoBase 自动编号；ERP 编号单独存入 erp_code。
                values = {"key_value": record.id, "erp_code": record.code, "title": record.title,
                          "problem_desc": record.description, "initiation_date": initiation.isoformat(),
                          "dept_name": record.department, "prob_type": TYPE_VALUES[record.transaction_type],
                          "erp_all_field_value": source_snapshot(record)}
                if existing is None:
                    if record.originator not in user_cache:
                        user_cache[record.originator] = self.target.find_user(record.originator)
                    user_id, warning = user_cache[record.originator]
                    values.update(estimate_time=0, actual_time=0, initiator_id=user_id)
                    saved = self.target.create(values) if not dry_run else {}
                    action = "created"
                    if warning:
                        outcome["warning"] = warning
                else:
                    saved = self.target.update(int(existing["id"]), values) if not dry_run else {}
                    action = "updated"
                if dry_run:
                    action = "would_create" if existing is None else "would_update"
                    summary[action] += 1
                    save_outcome({**outcome, "action": action}, index)
                    continue
                # 回读持久化字段，避免缺失 ERP 身份字段时误判写入成功。
                if saved.get("erp_code") != record.code or saved.get("key_value") != record.id:
                    raise SyncIdentityError(f"NocoBase 记录 {saved.get('id')} 写入后 erp_code 或 key_value 未保留 ERP 原值；自动同步已停止")
                summary[action] += 1
                outcome.update(action=action, nocobase_id=saved["id"])
            except (TaskCancelledError, NocoBaseApiKeyInvalidError, NocoBasePermissionDeniedError, SyncIdentityError):
                raise
            except (EhrmError, ValueError, KeyError) as exc:
                summary["failed"] += 1
                outcome.update(action="failed", error=exc.message if isinstance(exc, EhrmError) else str(exc))
            save_outcome(outcome, index)
        return {"start_date": start_date, "end_date": end_date, "dry_run": dry_run, "summary": summary, "items": items}


def default_date_range(days: int, *, today: date | None = None) -> tuple[str, str]:
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    return (today - timedelta(days=days - 1)).isoformat(), today.isoformat()
