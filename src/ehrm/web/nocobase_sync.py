"""ERP sync executor, plus read-only migration support for old interval plans."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from playwright.sync_api import sync_playwright

from ehrm.core.auth_repository import SystemType
from ehrm.modules.erp.models import ErpCredentials
from ehrm.modules.erp.task_service import ErpTaskQueryService
from ehrm.modules.nocobase.application_query_service import NocoBaseApplicationQueryService
from ehrm.modules.nocobase.erp_sync import ErpNocoBaseSync
from ehrm.modules.nocobase.sync_client import NocoBaseSyncClient


def read_legacy_schedule(path: Path):
    """Read the old singleton without modifying it or restarting its timer."""
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT interval_minutes,lookback_days FROM sync_schedule WHERE id=1").fetchone()
        return dict(row) if row else None


@contextmanager
def exclusive_file(path: Path):
    """Nonblocking OS lock; released automatically after crash (macOS/Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if __import__("os").name == "nt":
            import msvcrt
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError:
            yield False
        else:
            try:
                yield True
            finally:
                handle.seek(0)
                release()


class NocoBaseSyncController:
    """Business executor only. The workbench owns scheduling and run persistence."""
    def __init__(self, settings_service, coordinator, logger) -> None:
        self.settings_service = settings_service
        self.coordinator = coordinator
        self.logger = logger
        self.root = settings_service.runtime_root / "data"
        self.workbench = None

    def _erp_account(self):
        account = self.settings_service.repository.get_default_account(SystemType.ERP)
        if account is None or not account.password:
            raise ValueError("请先配置 ERP 账号和密码")
        return account

    def prepare(self):
        account = self._erp_account()
        key = NocoBaseApplicationQueryService(self.settings_service.base_settings, self.logger)._configured_key()
        return self.settings_service.runtime_settings(erp_account=account), key, account

    def submit(self, *, start_date="", end_date="", dry_run=False):
        run = self.workbench.trigger("erp-nocobase-sync", start_date=start_date, end_date=end_date, dry_run=dry_run)
        return self.coordinator.get(run["task_id"])

    def _run(self, context, settings, key, account, start_date, end_date, dry_run):
        with exclusive_file(self.root / "nocobase_sync_run.lock") as acquired:
            if not acquired:
                raise ValueError("已有 ERP 同步正在执行，请勿重复启动服务实例")
            # ERP 会话结束后才创建请求上下文，避免嵌套同步 Playwright。
            worker = ErpNocoBaseSync(
                ErpTaskQueryService(settings, self.logger, context.report, lambda: context.cancelled), None)
            records = worker.fetch_records(start_date=start_date, end_date=end_date,
                                           credentials=ErpCredentials(account.account, account.password), context=context)
            with sync_playwright() as playwright:
                request = playwright.request.new_context()
                try:
                    worker.target = NocoBaseSyncClient(settings.nocobase, request, key)
                    result = worker.sync_records(records, start_date=start_date, end_date=end_date, context=context, dry_run=dry_run)
                    counts = result["summary"]
                    context.report(f"预览结束：预计新增 {counts['would_create']}，预计更新 {counts['would_update']}，"
                                   f"未变化 {counts['unchanged']}，失败 {counts['failed']}" if dry_run else
                                   f"同步结束：新增 {counts['created']}，更新 {counts['updated']}，"
                                   f"未变化 {counts['unchanged']}，失败 {counts['failed']}")
                    return result
                finally:
                    request.dispose()
