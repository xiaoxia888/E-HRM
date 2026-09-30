"""Durable, per-person operation ledger; never changes NocoBase business status.

Succeeded and uncertain submissions are blocked even when a different account
is selected. Only the single-server coordinator starts browsers; SQLite admits
one batch per application/operation before it is handed to that coordinator.
"""
from __future__ import annotations

from dataclasses import asdict
from contextlib import contextmanager
from datetime import datetime, UTC
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import HTTPException

from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.auth_repository import SystemType
from ehrm.modules.employment_termination.models import EmploymentTerminationItem, normalize_termination_items
from ehrm.modules.employment_termination.service import EmploymentTerminationService
from ehrm.web.tasks import TaskKind


def person_key(identity: str) -> str:
    return sha256(identity.strip().upper().encode()).hexdigest()


class ApplicationOperationRepository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS application_runs (
                    id TEXT PRIMARY KEY, application_id INTEGER NOT NULL,
                    operation TEXT NOT NULL, active INTEGER NOT NULL,
                    task_id TEXT, account_id INTEGER NOT NULL, account_label TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS application_active_operation
                    ON application_runs(application_id, operation) WHERE active=1;
                CREATE TABLE IF NOT EXISTS application_people_operations (
                    application_id INTEGER NOT NULL, operation TEXT NOT NULL,
                    person_key TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
                    message TEXT NOT NULL, updated_at TEXT NOT NULL, run_id TEXT NOT NULL,
                    PRIMARY KEY(application_id, operation, person_key)
                );
                CREATE TABLE IF NOT EXISTS application_operation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, message TEXT NOT NULL
                );
            """)
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, application_id, operation, people, account):
        run_id = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM application_runs WHERE application_id=? AND operation=? AND active=1",
                          (application_id, operation)).fetchone():
                raise HTTPException(409, "该申请正在排队或执行，请勿重复发起")
            eligible = []
            for item, name in people:
                key = person_key(item.identity_number)
                previous = db.execute("SELECT status FROM application_people_operations WHERE application_id=? AND operation=? AND person_key=?",
                                      (application_id, operation, key)).fetchone()
                if previous and previous['status'] in ('succeeded', 'unknown'):
                    continue
                eligible.append(item)
                db.execute("INSERT OR REPLACE INTO application_people_operations VALUES (?,?,?,?,?,?,?,?)",
                           (application_id, operation, key, name, 'queued', '等待执行', self.now(), run_id))
            if not eligible:
                raise HTTPException(409, "人员均已成功办理或结果待确认，不会再次提交；待确认项请人工核对")
            db.execute("INSERT INTO application_runs VALUES (?,?,?,1,NULL,?,?)",
                       (run_id, application_id, operation, account.id, account.display_name or '智慧人社账号'))
        return run_id, tuple(eligible)

    @staticmethod
    def now():
        return datetime.now(UTC).isoformat()

    def mark(self, run_id, item, status, message):
        with self.connect() as db:
            db.execute("UPDATE application_people_operations SET status=?, message=?, updated_at=? WHERE run_id=? AND person_key=?",
                       (status, message, self.now(), run_id, person_key(item.identity_number)))

    def log(self, run_id, message):
        with self.connect() as db:
            db.execute("INSERT INTO application_operation_logs(run_id,created_at,message) VALUES (?,?,?)",
                       (run_id, self.now(), message))

    def start(self, run_id):
        with self.connect() as db:
            db.execute("UPDATE application_people_operations SET status='running', message='正在执行本批任务，等待轮流录入', updated_at=? WHERE run_id=? AND status='queued'",
                       (self.now(), run_id))

    def finish(self, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # A crash/cancellation after crossing the mutation boundary cannot
            # safely be called a failure and must never cause automatic retry.
            db.execute("UPDATE application_people_operations SET status=CASE WHEN status='submitting' THEN 'unknown' ELSE 'not_processed' END, message=CASE WHEN status='submitting' THEN '提交结果待确认，请人工核对；禁止重复提交' ELSE '本次未完成提交，可重新发起' END, updated_at=? WHERE run_id=? AND status IN ('queued','running','submitting')",
                       (self.now(), run_id))
            db.execute("UPDATE application_runs SET active=0 WHERE id=?", (run_id,))

    def recover(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM application_runs WHERE active=1")]
        for run_id in ids:
            self.finish(run_id)

    def observe(self, snapshot):
        if not snapshot.operation.startswith('application.termination:'):
            return
        run_id = snapshot.operation.split(':', 1)[1]
        with self.connect() as db:
            db.execute("UPDATE application_runs SET task_id=? WHERE id=?", (snapshot.task_id, run_id))
        if snapshot.status.terminal:
            self.finish(run_id)

    def state(self, application_id):
        with self.connect() as db:
            rows = db.execute("SELECT p.*, r.task_id, r.account_label FROM application_people_operations p JOIN application_runs r ON r.id=p.run_id WHERE p.application_id=?", (application_id,)).fetchall()
            runs = db.execute("SELECT * FROM application_runs WHERE application_id=? ORDER BY rowid DESC LIMIT 20", (application_id,)).fetchall()
        return {'people': [dict(row) for row in rows], 'runs': [dict(row) for row in runs]}

    def logs(self, run_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT created_at,message FROM application_operation_logs WHERE run_id=? ORDER BY id", (run_id,))]


class ApplicationOperationService:
    def __init__(self, settings_service, coordinator, logger):
        self.settings_service = settings_service
        self.coordinator = coordinator
        self.logger = logger
        self.repository = ApplicationOperationRepository(settings_service.runtime_root / 'data' / 'application_operations.sqlite3')
        self.repository.recover()
        coordinator.observe(self.repository.observe)

    def submit_termination(self, detail, account_id):
        if detail.problem_type != 'social_security_termination':
            raise ValueError('只有退工停保登记申请可以执行退保')
        if not detail.termination_person:
            raise ValueError('当前申请没有退保人员')
        account = self.settings_service.account(account_id, SystemType.JSHRSS)
        items = normalize_termination_items(tuple(EmploymentTerminationItem(
            identity_number=str(row.get('id_card_no') or ''),
            termination_reason=str(row.get('termination_reason') or ''), source_index=index,
        ) for index, row in enumerate(detail.termination_person, 1)))
        people = tuple((item, str(row.get('user_name') or '')) for item, row in zip(items, detail.termination_person))
        run_id, eligible = self.repository.reserve(detail.application_id, 'termination', people, account)
        try:
            return self.coordinator.submit(
                title=f'退工停保 {detail.code}', operation=f'application.termination:{run_id}',
                kind=TaskKind.JSHRSS_BROWSER, resource_key=str(account.id),
                resource_label=account.display_name or '智慧人社账号',
                runner=lambda context: self._run(context, run_id, account, eligible),
            )
        except Exception:
            self.repository.finish(run_id)
            raise

    def _run(self, context, run_id, account, items):
        settings = self.settings_service.runtime_settings(rights_account=account)
        done = 0

        def progress(message):
            self.repository.log(run_id, message)
            context.report(message, current=done, total=len(items))

        def before_submit(item):
            context.raise_if_cancelled()
            self.repository.mark(run_id, item, 'submitting', '正在提交，请勿重复办理')

        def record(result):
            nonlocal done
            status = 'succeeded' if result.status == 'submitted' else result.status
            self.repository.mark(run_id, result.item, status, result.message)
            done += 1

        try:
            self.repository.start(run_id)
            progress('正在准备所选账号的登录状态')
            with BrowserManager(settings.browser, stealth_enabled=settings.captcha.stealth_enabled and
                                is_allowed_host_url(settings.site.login_url, settings.captcha.allowed_hosts)) as browser:
                login = LoginService(browser.page, settings, progress_callback=progress)
                login.ensure_authenticated()
                context.raise_if_cancelled()
                service = EmploymentTerminationService(settings, self.logger, progress_callback=progress,
                                                       cancel_check=lambda: context.cancelled)
                result = service.submit_with_page(login.page, items, before_submit_callback=before_submit,
                                                  result_callback=record)
            progress(f'处理结束：成功 {result.submitted_count} 人，待确认 {result.unknown_count} 人')
            return {'submitted_count': result.submitted_count, 'unknown_count': result.unknown_count,
                    'total': len(items), 'results': [asdict(row) for row in result.results]}
        finally:
            self.repository.finish(run_id)
