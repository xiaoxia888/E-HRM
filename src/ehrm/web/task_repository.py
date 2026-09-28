from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from ehrm.web.tasks import TaskKind, TaskSnapshot, TaskStatus


class TaskRepository:
    """SQLite storage for task history and task result file indexes."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_records (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resource_label TEXT NOT NULL DEFAULT '',
                    queue_position INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    progress_current INTEGER NOT NULL DEFAULT 0,
                    progress_total INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result_json TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_records_created_at
                    ON task_records(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_records_status
                    ON task_records(status);

                CREATE TABLE IF NOT EXISTS task_artifacts (
                    token TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
        try:
            self.database_path.chmod(0o600)
        except OSError:
            pass

    def save(self, snapshot: TaskSnapshot) -> None:
        result_json = (
            json.dumps(
                snapshot.result,
                ensure_ascii=False,
                separators=(",", ":"),
                default=_json_default,
            )
            if snapshot.result is not None
            else None
        )
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_records (
                    task_id, title, operation, kind, status, resource_label,
                    queue_position, message, progress_current, progress_total,
                    created_at, started_at, finished_at, result_json, error,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    title = excluded.title,
                    operation = excluded.operation,
                    kind = excluded.kind,
                    status = excluded.status,
                    resource_label = excluded.resource_label,
                    queue_position = excluded.queue_position,
                    message = excluded.message,
                    progress_current = excluded.progress_current,
                    progress_total = excluded.progress_total,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    result_json = excluded.result_json,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (
                    snapshot.task_id,
                    snapshot.title,
                    snapshot.operation,
                    snapshot.kind.value,
                    snapshot.status.value,
                    snapshot.resource_label,
                    snapshot.queue_position,
                    snapshot.message,
                    snapshot.progress_current,
                    snapshot.progress_total,
                    snapshot.created_at,
                    snapshot.started_at,
                    snapshot.finished_at,
                    result_json,
                    snapshot.error,
                    now,
                ),
            )

    def get(self, task_id: str) -> TaskSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_records WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return self._snapshot(row) if row is not None else None

    def list(self, *, limit: int) -> tuple[TaskSnapshot, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_records
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (max(int(limit), 1),),
            ).fetchall()
        return tuple(self._snapshot(row) for row in rows)

    def mark_unfinished_interrupted(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE task_records
                SET status = ?,
                    queue_position = 0,
                    message = ?,
                    error = CASE WHEN error = '' THEN ? ELSE error END,
                    finished_at = ?,
                    updated_at = ?
                WHERE status IN (?, ?, ?)
                """,
                (
                    TaskStatus.INTERRUPTED.value,
                    "服务曾停止，任务未继续执行；请核对业务结果后重新发起",
                    "服务器重启或进程退出导致任务中断",
                    now,
                    now,
                    TaskStatus.QUEUED.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.CANCELLING.value,
                ),
            )
            return max(cursor.rowcount, 0)

    def save_artifact(self, token: str, path: Path) -> None:
        resolved = path.expanduser().resolve()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_artifacts (token, name, path, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    name = excluded.name,
                    path = excluded.path
                """,
                (token, resolved.name, str(resolved), datetime.now(UTC).isoformat()),
            )

    def resolve_artifact(self, token: str) -> Path | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path FROM task_artifacts WHERE token = ?",
                (token,),
            ).fetchone()
        if row is None:
            return None
        path = Path(str(row["path"])).expanduser().resolve()
        return path if path.is_file() else None

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> TaskSnapshot:
        result: object | None = None
        if row["result_json"]:
            try:
                result = json.loads(str(row["result_json"]))
            except (TypeError, ValueError):
                result = None
        return TaskSnapshot(
            task_id=str(row["task_id"]),
            title=str(row["title"]),
            operation=str(row["operation"]),
            kind=TaskKind(str(row["kind"])),
            status=TaskStatus(str(row["status"])),
            resource_label=str(row["resource_label"]),
            queue_position=int(row["queue_position"]),
            message=str(row["message"]),
            progress_current=int(row["progress_current"]),
            progress_total=int(row["progress_total"]),
            created_at=str(row["created_at"]),
            started_at=str(row["started_at"]) if row["started_at"] else None,
            finished_at=str(row["finished_at"]) if row["finished_at"] else None,
            result=result,
            error=str(row["error"]),
        )


def _json_default(value: Any) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"无法序列化任务结果类型：{type(value).__name__}")
