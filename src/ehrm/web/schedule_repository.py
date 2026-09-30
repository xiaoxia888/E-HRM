"""Durable definitions, execution attempts and step logs; never expires history."""
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

ACTIVE = ("queued", "running", "cancelling")
OPERATION_PREFIX = "scheduled:"


def timestamp():
    return datetime.now(UTC).isoformat()


def safe_message(value: str) -> str:
    return re.sub(r"(?i)(bearer\s+|(?:api[_-]?key|password|token)\s*[=:]\s*)[^\s,;]+", r"\1[已隐藏]", value)


class ScheduleRepository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, task_type TEXT NOT NULL,
                    cron TEXT NOT NULL, enabled INTEGER NOT NULL, lookback_days INTEGER NOT NULL,
                    next_run TEXT, notice TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scheduled_runs (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, trigger_kind TEXT NOT NULL,
                    status TEXT NOT NULL, task_id TEXT, created_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, message TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '', result_json TEXT, parameters_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS scheduled_runs_job ON scheduled_runs(job_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS scheduled_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS scheduled_logs_run ON scheduled_logs(run_id,id);
            """)
        path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def jobs(self):
        with self.connect() as db:
            return [self._job(row) for row in db.execute("SELECT * FROM scheduled_jobs ORDER BY name,id")]

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("定时任务不存在")
        return self._job(row)

    @staticmethod
    def _job(row):
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        result["timezone"] = "Asia/Shanghai"
        return result

    def save(self, job):
        with self.connect() as db:
            db.execute("""INSERT INTO scheduled_jobs VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,cron=excluded.cron,
                enabled=excluded.enabled,lookback_days=excluded.lookback_days,
                next_run=excluded.next_run,notice=excluded.notice,updated_at=excluded.updated_at""",
                (job["id"], job["name"], job["task_type"], job["cron"], job["enabled"],
                 job["lookback_days"], job.get("next_run"), job.get("notice", ""), timestamp()))
        return self.job(job["id"])

    def next_run(self, job_id, value, expected_cron=None):
        with self.connect() as db:
            # A late callback must not resurrect a disabled or just-edited plan.
            db.execute("""UPDATE scheduled_jobs SET next_run=? WHERE id=? AND enabled=1
                AND (? IS NULL OR cron=?)""", (value, job_id, expected_cron, expected_cron))

    def new_run(self, job_id, trigger_kind, parameters, *, status="queued"):
        run_id = uuid4().hex
        with self.connect() as db:
            db.execute("""INSERT INTO scheduled_runs(id,job_id,trigger_kind,status,created_at,parameters_json)
                VALUES(?,?,?,?,?,?)""", (run_id, job_id, trigger_kind, status, timestamp(), json.dumps(parameters)))
        self.log(run_id, "info", "已接收触发请求")
        return run_id

    def finish(self, run_id, status, message, *, error="", task_id=None):
        with self.connect() as db:
            db.execute("""UPDATE scheduled_runs SET status=?,message=?,error=?,finished_at=?,
                task_id=COALESCE(?,task_id) WHERE id=?""",
                (status, safe_message(message), safe_message(error), timestamp(), task_id, run_id))
        self.log(run_id, "error" if error else "warning", message)

    def active(self, task_type):
        with self.connect() as db:
            row = db.execute("""SELECT r.* FROM scheduled_runs r JOIN scheduled_jobs j ON j.id=r.job_id
                WHERE j.task_type=? AND r.status IN ('queued','running','cancelling')
                ORDER BY r.created_at DESC LIMIT 1""", (task_type,)).fetchone()
        return self._run(row) if row else None

    def recover(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM scheduled_runs WHERE status IN ('queued','running','cancelling')")]
        for run_id in ids:
            self.finish(run_id, "interrupted", "服务重启，前次执行已中断；不会自动重跑写入")

    def observe(self, snapshot):
        # Called under TaskCoordinator's lock: only writes DB, never calls coordinator/scheduler.
        if not snapshot.operation.startswith(OPERATION_PREFIX):
            return
        run_id = snapshot.operation[len(OPERATION_PREFIX):]
        status = snapshot.status.value
        failures = snapshot.result.get("summary", {}).get("failed", 0) if isinstance(snapshot.result, dict) else 0
        if status == "succeeded" and failures:
            status = "partial_failed"
        message = safe_message(f"同步完成，{failures} 条记录失败，请查看逐条结果" if status == "partial_failed" else snapshot.error or snapshot.message)
        result = json.dumps(snapshot.result, ensure_ascii=False, default=str) if snapshot.result is not None else None
        with self.connect() as db:
            old = db.execute("SELECT status,message FROM scheduled_runs WHERE id=?", (run_id,)).fetchone()
            if old is None:
                return
            db.execute("""UPDATE scheduled_runs SET task_id=?,status=?,started_at=?,finished_at=?,
                message=?,error=?,result_json=? WHERE id=?""", (snapshot.task_id, status, snapshot.started_at,
                snapshot.finished_at, message, safe_message(snapshot.error), result, run_id))
            if old["status"] != status or old["message"] != message:
                db.execute("INSERT INTO scheduled_logs(run_id,created_at,level,message) VALUES(?,?,?,?)",
                           (run_id, timestamp(), "error" if status in ("failed", "partial_failed") else "info", message))

    def log(self, run_id, level, message):
        with self.connect() as db:
            db.execute("INSERT INTO scheduled_logs(run_id,created_at,level,message) VALUES(?,?,?,?)",
                       (run_id, timestamp(), level, safe_message(message)))

    @staticmethod
    def _run(row):
        result = dict(row)
        raw_result = result.pop("result_json")
        result["result"] = json.loads(raw_result) if raw_result else None
        result["parameters"] = json.loads(result.pop("parameters_json"))
        return result

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM scheduled_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("执行记录不存在")
        return self._run(row)

    def runs(self, job_id=None, page=1, page_size=20):
        where, args = ("WHERE job_id=?", [job_id]) if job_id else ("", [])
        with self.connect() as db:
            total = db.execute(f"SELECT count(*) FROM scheduled_runs {where}", args).fetchone()[0]
            rows = db.execute(f"SELECT * FROM scheduled_runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                              [*args, page_size, (page-1)*page_size]).fetchall()
        return {"items": [self._run(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def logs(self, run_id, page=1, page_size=50):
        self.run(run_id)
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM scheduled_logs WHERE run_id=?", (run_id,)).fetchone()[0]
            rows = db.execute("SELECT * FROM scheduled_logs WHERE run_id=? ORDER BY id LIMIT ? OFFSET ?",
                              (run_id, page_size, (page-1)*page_size)).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}
