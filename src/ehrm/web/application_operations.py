"""Durable, per-person operation ledger; never changes NocoBase business status.

Succeeded and uncertain submissions are blocked even when a different account
is selected. Only the single-server coordinator starts browsers; SQLite admits
one batch per application/operation before it is handed to that coordinator.
"""
from __future__ import annotations

from dataclasses import asdict
from contextlib import contextmanager
from datetime import date, datetime, UTC
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import HTTPException
from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.auth_repository import SystemType
from ehrm.core.exceptions import EhrmError, EmployeeNotFoundError, TaskCancelledError
from ehrm.modules.employment_termination.models import EmploymentTerminationItem, normalize_termination_items
from ehrm.modules.employment_termination.service import EmploymentTerminationService
from ehrm.modules.medical_enrollment.models import MedicalPreSubmitItem, MedicalStage
from ehrm.modules.medical_enrollment.page import MedicalPreSubmitBlockedError
from ehrm.modules.medical_enrollment.submission import (
    MedicalEnrollmentSubmissionPage, MedicalEnrollmentSubmissionUncertainError,
)
from ehrm.modules.medical_termination.models import MedicalTerminationItem
from ehrm.modules.medical_termination.page import (
    MEDICAL_LOGIN_URL, MedicalSubmissionUncertainError, MedicalTerminationPage,
    is_medical_portal_ready, is_medical_portal_url, verify_existing_medical_session,
)
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
            db.execute("UPDATE application_people_operations SET status=?, message=?, updated_at=? WHERE run_id=? AND person_key=? AND operation=(SELECT operation FROM application_runs WHERE id=?)",
                       (status, message, self.now(), run_id, person_key(item.identity_number), run_id))

    def mark_stage(self, run_id, item, name, operation, status, message):
        with self.connect() as db:
            run = db.execute("SELECT application_id FROM application_runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise ValueError("医保参保执行记录不存在")
            db.execute("INSERT OR REPLACE INTO application_people_operations VALUES (?,?,?,?,?,?,?,?)",
                       (run['application_id'], operation, person_key(item.identity_number), name,
                        status, message, self.now(), run_id))

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
        if not snapshot.operation.startswith(('application.termination:', 'application.medical_termination:',
                                              'application.medical_enrollment:')):
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

    def submit_medical_termination(self, detail, account_id):
        if detail.problem_type != 'medical_termination':
            raise ValueError('只有医保退工停保登记申请可以执行医保停保')
        if not detail.med_ins_withdrawal_record:
            raise ValueError('当前申请没有医保停保人员')
        account = self.settings_service.account(account_id, SystemType.MEDICAL)
        people = []
        identities = set()
        already_handled = {
            row['person_key'] for row in self.repository.state(detail.application_id)['people']
            if row['operation'] == 'medical_termination' and row['status'] in {'succeeded', 'unknown'}
        }
        for index, row in enumerate(detail.med_ins_withdrawal_record, 1):
            identity = str(row.get('id_card_no') or '').strip().upper()
            if identity in identities:
                raise ValueError('同一申请含重复身份证号，已停止以避免重复提交')
            identities.add(identity)
            if person_key(identity) in already_handled:
                continue
            raw_date = row.get('med_stop_date')
            try:
                stop_date = date.fromisoformat(str(raw_date or '').strip()[:10])
            except ValueError as exc:
                raise ValueError(f'第 {index} 人停保时间缺失或格式错误，请先在 NocoBase 核对') from exc
            month_fee = str(row.get('med_ins_stop_month_fee') or '').strip()
            if month_fee not in {'是', '否'}:
                raise ValueError(f'第 {index} 人停保当月是否缴费必须为“是”或“否”')
            item = MedicalTerminationItem(
                identity_number=identity,
                reason=str(row.get('med_ins_stop_reason') or ''),
                termination_date=stop_date,
                pay_current_month=month_fee == '是',
                source_index=index,
            ).normalized()
            people.append((item, str(row.get('user_name') or '')))
        run_id, eligible = self.repository.reserve(
            detail.application_id, 'medical_termination', tuple(people), account,
        )
        try:
            return self.coordinator.submit(
                title=f'医保停保 {detail.code}',
                operation=f'application.medical_termination:{run_id}',
                kind=TaskKind.MEDICAL_BROWSER, resource_key=str(account.id),
                resource_label=account.display_name or '医保政务平台账号',
                runner=lambda context: self._run_medical(context, run_id, account, eligible),
            )
        except Exception:
            self.repository.finish(run_id)
            raise

    def submit_medical_enrollment(self, detail, account_id):
        if detail.problem_type != 'medical_enrollment':
            raise ValueError('只有医保人员参保登记申请可以执行医保参保')
        if not detail.med_ins_enrollee:
            raise ValueError('当前申请没有医保参保人员')
        account = self.settings_service.account(account_id, SystemType.MEDICAL)
        people = []
        identities = set()
        already_handled = {
            row['person_key'] for row in self.repository.state(detail.application_id)['people']
            if row['operation'] == 'medical_enrollment' and row['status'] in {'succeeded', 'unknown'}
        }
        for index, row in enumerate(detail.med_ins_enrollee, 1):
            identity = str(row.get('id_card_no') or '').strip().upper()
            if identity in identities:
                raise ValueError('同一申请含重复身份证号，已停止以避免重复提交')
            identities.add(identity)
            if person_key(identity) in already_handled:
                continue
            raw_date = row.get('arrive_unit_time')
            try:
                enrollment_date = date.fromisoformat(str(raw_date or '').strip()[:10])
            except ValueError as exc:
                raise ValueError(f'第 {index} 人到单位时间缺失或格式错误，请先在 NocoBase 核对') from exc
            def optional_date(field):
                value = str(row.get(field) or '').strip()
                if not value:
                    return None
                try:
                    return date.fromisoformat(value[:10])
                except ValueError as exc:
                    raise ValueError(f'第 {index} 人{field}日期格式错误，请先在 NocoBase 核对') from exc
            item = MedicalPreSubmitItem(
                identity_number=identity, name=str(row.get('user_name') or ''),
                mobile=str(row.get('phone') or ''), nation=str(row.get('ethnicity') or ''),
                document_start_date=optional_date('cert_valid_from'),
                document_end_date=optional_date('cert_valid_to'),
                enrollment_date=enrollment_date, source_index=index,
            ).normalized(MedicalStage.ENROLLMENT)
            people.append((item, item.name))
        run_id, eligible = self.repository.reserve(
            detail.application_id, 'medical_enrollment', tuple(people), account,
        )
        try:
            return self.coordinator.submit(
                title=f'医保参保 {detail.code}', operation=f'application.medical_enrollment:{run_id}',
                kind=TaskKind.MEDICAL_BROWSER, resource_key=str(account.id),
                resource_label=account.display_name or '医保政务平台账号',
                runner=lambda context: self._run_medical_enrollment(context, run_id, account, eligible),
            )
        except Exception:
            self.repository.finish(run_id)
            raise

    def _run_medical_enrollment(self, context, run_id, account, items):
        settings = self.settings_service.runtime_settings(rights_account=account)
        results = []
        done = 0
        existing_count = 0

        def progress(message):
            self.repository.log(run_id, message)
            context.report(message, current=done, total=len(items))

        def record(item, status, message):
            nonlocal done
            self.repository.mark(run_id, item, status, message)
            results.append({'status': status, 'message': message})
            done += 1

        def skip_remaining(start):
            for item in items[start:]:
                record(item, 'not_processed', '前一条处理中断，本条未执行提交')

        def prepare_next(index, page, enrollment):
            if index >= len(items) - 1:
                return True
            try:
                context.raise_if_cancelled()
                # A full session verification reloads the portal and can close
                # the current enrollment tab. The next person's query will
                # validate the live session through its actual API response.
                if not (enrollment._enrollment_form_is_active() or is_medical_portal_ready(page)):
                    raise ValueError('医保单位大厅已不在可操作状态')
                enrollment.open()
                identity = enrollment._enrollment_identity()
                current = identity.input_value().strip().upper()
                if current == items[index].identity_number:
                    enrollment._perform(lambda: identity.fill(''))
                    current = identity.input_value().strip().upper()
                if current:
                    raise ValueError('下一人表单仍保留其他人员身份证号')
                return True
            except TaskCancelledError:
                raise
            except (EhrmError, PlaywrightError, ValueError) as exc:
                progress(f'医保参保：已记录前面人员结果，但下一人空白表单未就绪：{exc}')
                skip_remaining(index + 1)
                return False

        try:
            self.repository.start(run_id)
            progress('正在检查所选医保账号会话，必要时通过政务平台登录')
            with BrowserManager(
                settings.browser,
                stealth_enabled=settings.captcha.stealth_enabled and
                is_allowed_host_url(settings.site.login_url, settings.captcha.allowed_hosts),
            ) as browser:
                login = LoginService(browser.page, settings, progress_callback=progress)
                page = login.ensure_external_government_authenticated(
                    entry_url=MEDICAL_LOGIN_URL, username=account.account,
                    password=account.password, target_matches=is_medical_portal_url,
                    target_ready=is_medical_portal_ready,
                    existing_session_ready=verify_existing_medical_session,
                )
                enrollment = MedicalEnrollmentSubmissionPage(
                    page, MedicalStage.ENROLLMENT, timeout_ms=settings.browser.action_timeout_ms,
                    pacing=settings.browser.pacing, progress_callback=progress,
                )
                collection = MedicalEnrollmentSubmissionPage(
                    page, MedicalStage.COLLECTION, timeout_ms=settings.browser.action_timeout_ms,
                    pacing=settings.browser.pacing, progress_callback=progress,
                )
                for index, item in enumerate(items):
                    started = False
                    name = item.name or f'第 {item.source_index} 人'
                    try:
                        context.raise_if_cancelled()
                        progress(f'医保参保：开始办理第 {index + 1}/{len(items)} 人，先查询参保')
                        try:
                            enrollment.fill_item(item)
                        except MedicalPreSubmitBlockedError as exc:
                            if exc.outcome == '已参保':
                                existing_count += 1
                                record(item, 'succeeded', f'医保平台提示已参保；本次未重复提交：{exc}')
                                progress(f'医保参保：第 {index + 1} 人平台提示已参保，跳过提交')
                                if not prepare_next(index, page, enrollment):
                                    break
                                continue
                            if exc.outcome != '需先建档':
                                raise
                            stage_rows = self.repository.state(
                                self._run_application_id(run_id)
                            )['people']
                            prior = next((row for row in stage_rows if row['operation'] == 'medical_information_collection'
                                          and row['person_key'] == person_key(item.identity_number)), None)
                            if prior and prior['status'] in {'succeeded', 'unknown'}:
                                raise MedicalEnrollmentSubmissionUncertainError(
                                    '医保提示需先建档，但本系统已有建档成功或待确认记录；请核对，勿自动重复建档'
                                )
                            if not item.name.strip() or not item.nation.strip():
                                raise ValueError('医保提示需先建档，但 NocoBase 姓名或民族缺失，未执行采集提交')
                            context.raise_if_cancelled()
                            enrollment.dismiss_archive_notice('请先给该人员建档')
                            progress(f'医保参保：第 {index + 1} 人需先建档，正在填写基础信息')
                            try:
                                collection.fill_item(item)
                            except MedicalPreSubmitBlockedError as archive_exc:
                                if archive_exc.outcome != '已建档':
                                    raise
                                collection.dismiss_archive_notice('已经建档')
                                collection_result = 'existing'
                            else:

                                def before_collection():
                                    nonlocal started
                                    context.raise_if_cancelled()
                                    self.repository.mark(run_id, item, 'submitting', '正在向医保平台提交基础信息采集；勿重复办理')
                                    self.repository.mark_stage(run_id, item, name, 'medical_information_collection',
                                                               'submitting', '正在向医保平台提交基础信息采集')
                                    started = True

                                collection_result = collection.submit_collection(item, before_submit=before_collection)
                            stage_message = ('医保平台确认建档成功' if collection_result == 'saved'
                                             else '医保平台提示该人员已经建档；本次未重复建档')
                            self.repository.mark_stage(run_id, item, name, 'medical_information_collection',
                                                       'succeeded', stage_message)
                            self.repository.mark(run_id, item, 'running', '建档步骤已确认，继续参保查询')
                            started = False
                            progress(f'医保参保：第 {index + 1} 人{stage_message}，重新查询参保')
                            try:
                                enrollment.fill_item(item)
                            except MedicalPreSubmitBlockedError as retry_exc:
                                if retry_exc.outcome == '需先建档':
                                    raise MedicalEnrollmentSubmissionUncertainError(
                                        '建档步骤后医保仍提示需先建档；请核对，勿重复提交'
                                    ) from retry_exc
                                raise

                        def before_enrollment():
                            nonlocal started
                            context.raise_if_cancelled()
                            self.repository.mark(run_id, item, 'submitting', '正在向医保平台提交参保；勿重复办理')
                            started = True

                        context.raise_if_cancelled()
                        message = enrollment.submit_enrollment(item, before_submit=before_enrollment)
                    except TaskCancelledError:
                        raise
                    except (EhrmError, PlaywrightError, ValueError) as exc:
                        status = 'unknown' if started or isinstance(exc, MedicalEnrollmentSubmissionUncertainError) else 'failed'
                        record(item, status, str(exc))
                        progress(f'医保参保：第 {index + 1} 人{"结果待确认" if status == "unknown" else "提交前失败"}：{exc}')
                        skip_remaining(index + 1)
                        break
                    else:
                        record(item, 'succeeded', message)
                        progress(f'医保参保：第 {index + 1}/{len(items)} 人平台确认办理成功')

                    if not prepare_next(index, page, enrollment):
                        break
            return {
                'submitted_count': sum(row['status'] == 'succeeded' for row in results) - existing_count,
                'existing_count': existing_count,
                'unknown_count': sum(row['status'] == 'unknown' for row in results),
                'total': len(items), 'results': results,
            }
        finally:
            self.repository.finish(run_id)

    def _run_application_id(self, run_id):
        with self.repository.connect() as db:
            row = db.execute('SELECT application_id FROM application_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('医保参保执行记录不存在')
        return row['application_id']

    def _run_medical(self, context, run_id, account, items):
        settings = self.settings_service.runtime_settings(rights_account=account)
        done = 0
        results = []

        def progress(message):
            self.repository.log(run_id, message)
            context.report(message, current=done, total=len(items))

        def record(item, status, message):
            nonlocal done
            self.repository.mark(run_id, item, status, message)
            results.append({'status': status, 'message': message})
            done += 1

        def skip_remaining(start):
            for item in items[start:]:
                record(item, 'not_processed', '前一条处理中断，本条未执行提交')

        try:
            self.repository.start(run_id)
            progress('正在检查所选医保账号会话，必要时通过政务平台登录')
            with BrowserManager(
                settings.browser,
                stealth_enabled=settings.captcha.stealth_enabled and
                is_allowed_host_url(settings.site.login_url, settings.captcha.allowed_hosts),
            ) as browser:
                login = LoginService(browser.page, settings, progress_callback=progress)
                page = login.ensure_external_government_authenticated(
                    entry_url=MEDICAL_LOGIN_URL, username=account.account,
                    password=account.password, target_matches=is_medical_portal_url,
                    target_ready=is_medical_portal_ready,
                    existing_session_ready=verify_existing_medical_session,
                )
                context.raise_if_cancelled()
                operation = MedicalTerminationPage(
                    page, timeout_ms=settings.browser.action_timeout_ms,
                    pacing=settings.browser.pacing, progress_callback=progress,
                )
                for index, item in enumerate(items):
                    submission_started = False

                    def before_submit():
                        nonlocal submission_started
                        context.raise_if_cancelled()
                        self.repository.mark(run_id, item, 'submitting', '正在向医保平台提交；请勿重复办理')
                        submission_started = True

                    try:
                        context.raise_if_cancelled()
                        progress(f'医保停保：开始办理第 {index + 1}/{len(items)} 人')
                        operation.fill_item(item)
                        context.raise_if_cancelled()
                        message = operation.submit_item(item, before_submit=before_submit)
                    except TaskCancelledError:
                        raise
                    except (EhrmError, PlaywrightError, ValueError) as exc:
                        status = 'unknown' if submission_started or isinstance(exc, MedicalSubmissionUncertainError) else 'failed'
                        message = str(exc)
                        if status == 'unknown' and '请勿重复提交' not in message:
                            message += '；结果待人工核对，请勿重复提交'
                        record(item, status, message)
                        progress(f'医保停保：第 {index + 1} 人{"结果待确认" if status == "unknown" else "提交前失败"}：{message}')
                        if status == 'unknown' or not isinstance(exc, EmployeeNotFoundError):
                            skip_remaining(index + 1)
                            break
                    else:
                        # Persist this person's success before any page reset or
                        # cancellation can interrupt the remaining batch.
                        record(item, 'succeeded', message)
                        progress(f'医保停保：第 {index + 1}/{len(items)} 人平台提示提交成功')

                    if index < len(items) - 1:
                        try:
                            context.raise_if_cancelled()
                            operation.prepare_next()
                        except TaskCancelledError:
                            raise
                        except (EhrmError, PlaywrightError, ValueError) as exc:
                            progress(f'医保停保：已记录前面人员结果，但无法打开下一人空白表单：{exc}；停止后续处理')
                            skip_remaining(index + 1)
                            break
            progress(f'医保停保结束：成功 {sum(row["status"] == "succeeded" for row in results)} 人，'
                     f'待确认 {sum(row["status"] == "unknown" for row in results)} 人')
            return {'submitted_count': sum(row['status'] == 'succeeded' for row in results),
                    'unknown_count': sum(row['status'] == 'unknown' for row in results),
                    'total': len(items), 'results': results}
        finally:
            self.repository.finish(run_id)

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
