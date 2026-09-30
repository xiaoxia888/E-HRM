"""APScheduler triggers registered business jobs through the existing account queue."""
from datetime import datetime, timedelta
import threading
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED

from ehrm.modules.nocobase.erp_sync import SyncIdentityError, default_date_range
from ehrm.core.cron_schedule import TIMEZONE, cron_trigger, upcoming
from ehrm.web.nocobase_sync import exclusive_file, read_legacy_schedule
from ehrm.web.schedule_repository import ScheduleRepository, OPERATION_PREFIX
from ehrm.web.tasks import TaskKind

TASK_TYPE = "erp_nocobase_sync"
DEFAULT_JOB = "erp-nocobase-sync"


class ScheduledTaskWorkbench:
    def __init__(self, controller):
        self.controller = controller
        self.coordinator = controller.coordinator
        self.repository = ScheduleRepository(controller.root / "scheduled_tasks.sqlite3")
        self._mutex = threading.RLock()
        self._leader = None
        self.scheduler = BackgroundScheduler(
            timezone=TIMEZONE, executors={"default": ThreadPoolExecutor(2)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": None})
        self.scheduler.add_listener(self._engine_skip, EVENT_JOB_MAX_INSTANCES | EVENT_JOB_MISSED)
        self.coordinator.observe(self.repository.observe)
        controller.workbench = self
        if not self.repository.jobs():
            settings = controller.settings_service.base_settings.nocobase
            job = dict(id=DEFAULT_JOB, name="ERP 原始申请同步到 NocoBase", task_type=TASK_TYPE,
                       cron=settings.sync_cron, enabled=settings.sync_enabled,
                       lookback_days=settings.sync_lookback_days, next_run=None, notice="")
            legacy = controller.root / "nocobase_sync.sqlite3"
            if legacy.exists():
                old = read_legacy_schedule(legacy)
                if old:
                    job.update(enabled=False, lookback_days=old["lookback_days"],
                               notice=f"已迁移旧计划（间隔 {old['interval_minutes']} 分钟），请确认 cron 后重新启用。旧任务仍在任务中心。")
            self.repository.save(job)

    def list(self):
        jobs = self.repository.jobs()
        for job in jobs:
            latest = self.repository.runs(job["id"], page_size=1)["items"]
            job["last_run"] = latest[0] if latest else None
        return {"jobs": jobs, "task_types": [{"value": TASK_TYPE, "label": "ERP → NocoBase 原始申请同步"}],
                "scheduler_running": self.scheduler.running, "timezone": "Asia/Shanghai"}

    def save(self, job_id, values):
        with self._mutex:
            old = self.repository.job(job_id) if job_id else {"id": uuid4().hex, "task_type": TASK_TYPE}
            if values.get("task_type", TASK_TYPE) != TASK_TYPE:
                raise ValueError("仅允许执行已注册的业务任务，不支持任意脚本")
            name = values["name"].strip()
            if not name:
                raise ValueError("任务名称不能为空")
            expression = " ".join(values["cron"].split())
            future = upcoming(expression)
            if values["enabled"]:
                self.controller.prepare()
            job = {**old, **values, "name": name, "cron": expression, "notice": "",
                   "next_run": future[0] if values["enabled"] else None}
            self.repository.save(job)
            self._install(job)
            return self.repository.job(job["id"])

    def _install(self, job):
        if not self.scheduler.running:
            return
        if self.scheduler.get_job(job["id"]):
            self.scheduler.remove_job(job["id"])
        if job["enabled"]:
            next_time = datetime.fromisoformat(job["next_run"]) if job.get("next_run") else datetime.fromisoformat(upcoming(job["cron"])[0])
            self.scheduler.add_job(self._fire, trigger=cron_trigger(job["cron"]), id=job["id"],
                                   args=[job["id"]], next_run_time=next_time, replace_existing=True)
            self.repository.next_run(job["id"], next_time.isoformat(), job["cron"])

    def disable(self, job_id, notice):
        with self._mutex:
            job = self.repository.job(job_id)
            job.update(enabled=False, next_run=None, notice=notice)
            self.repository.save(job)
            self._install(job)

    def _fire(self, job_id):
        try:
            self.trigger(job_id, trigger_kind="automatic")
        except Exception:
            self.controller.logger.warning("定时任务未能创建执行任务，请在定时任务工作台查看日志")
        finally:
            job = self.repository.job(job_id)
            if job["enabled"]:
                now = datetime.now(TIMEZONE) + timedelta(microseconds=1)
                self.repository.next_run(job_id, upcoming(job["cron"], count=1, now=now)[0], job["cron"])

    def _engine_skip(self, event):
        # Engine callbacks only persist an attempt: do not acquire the workbench lock
        # or call coordinator, avoiding scheduler-lock/account-queue lock inversion.
        try:
            job = self.repository.job(event.job_id)
            start, end = default_date_range(job["lookback_days"])
            run_id = self.repository.new_run(event.job_id, "automatic", dict(start_date=start, end_date=end, dry_run=False), status="skipped")
            self.repository.finish(run_id, "skipped", "调度触发已跳过：上一轮调度回调尚未结束" if event.code == EVENT_JOB_MAX_INSTANCES else "调度触发已错过执行期限")
            if job["enabled"]:
                self.repository.next_run(job["id"], upcoming(job["cron"], count=1,
                    now=datetime.now(TIMEZONE) + timedelta(microseconds=1))[0], job["cron"])
        except Exception:
            self.controller.logger.warning("未能保存调度跳过记录，请检查定时任务数据库")

    def trigger(self, job_id, *, trigger_kind="manual", start_date="", end_date="", dry_run=False):
        with self._mutex:
            job = self.repository.job(job_id)
            if trigger_kind == "automatic" and (not job["enabled"] or not self.scheduler.running):
                return None
            if bool(start_date) != bool(end_date):
                raise ValueError("开始日期和结束日期必须同时填写")
            if not start_date:
                start_date, end_date = default_date_range(job["lookback_days"])
            start, end = datetime.strptime(start_date, "%Y-%m-%d"), datetime.strptime(end_date, "%Y-%m-%d")
            if start.strftime("%Y-%m-%d") != start_date or end.strftime("%Y-%m-%d") != end_date:
                raise ValueError("同步日期格式必须是 YYYY-MM-DD")
            if start > end:
                raise ValueError("开始日期不能晚于结束日期")
            parameters = dict(start_date=start_date, end_date=end_date, dry_run=dry_run)
            previous = self.repository.active(job["task_type"])
            run_id = self.repository.new_run(job_id, "preview" if dry_run else trigger_kind, parameters)
            if previous:
                self.repository.finish(run_id, "skipped", "已有同类同步任务排队或执行，本次触发已跳过",
                                       task_id=previous["task_id"])
                return self.repository.run(run_id)
            try:
                settings, key, account = self.controller.prepare()
                def runner(context):
                    try:
                        return self.controller._run(context, settings, key, account, start_date, end_date, dry_run)
                    except SyncIdentityError:
                        # 同一目标表的其他计划也必须暂停，否则下个计划可能重复新增。
                        for plan in self.repository.jobs():
                            if plan["task_type"] == job["task_type"]:
                                self.disable(plan["id"], "远端未保留 erp_code 或 key_value，自动执行已暂停；请检查对应记录和字段规则。")
                        raise
                self.coordinator.submit(
                    title=("预览：" if dry_run else "执行：") + job["name"],
                    operation=OPERATION_PREFIX + run_id, kind=TaskKind.ERP_BROWSER,
                    resource_key=str(account.id), resource_label=account.display_name or "ERP", runner=runner)
            except Exception as exc:
                self.repository.finish(run_id, "failed", str(exc), error=str(exc))
                raise
            return self.repository.run(run_id)

    def start(self):
        with self._mutex:
            if self.scheduler.running:
                return
            self._leader = exclusive_file(self.controller.root / "scheduled_tasks_scheduler.lock")
            if not self._leader.__enter__():
                self._leader.__exit__(None, None, None)
                self._leader = None
                raise RuntimeError("定时任务调度器已被另一服务实例占用，请使用单实例、单 worker")
            self.repository.recover()
            self.scheduler.start(paused=True)
            try:
                for job in self.repository.jobs():
                    self._install(job)
                self.scheduler.resume()
            except Exception:
                self.close()
                raise

    def close(self):
        with self._mutex:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            if self._leader:
                self._leader.__exit__(None, None, None)
                self._leader = None
