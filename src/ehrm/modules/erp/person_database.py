from __future__ import annotations

import logging
import os
from pathlib import Path
import re
from typing import Callable, Mapping, MutableMapping, Protocol, Sequence

from ehrm.core.exceptions import ConfigurationError, ErpQueryFailedError
from ehrm.core.settings import ErpDatabaseSettings
from ehrm.modules.erp.models import ErpPersonRecord


class _Cursor(Protocol):
    description: Sequence[Sequence[object]]

    def execute(self, sql: str, params: tuple[object, ...]) -> object: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...


class _Connection(Protocol):
    def cursor(self) -> _Cursor: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[ErpDatabaseSettings], _Connection]


_IDENTITY_PATTERN = re.compile(r"^(?:\d{15}|\d{17}[0-9X])$")
_DEFAULT_COMPANY = "南京南化建设有限公司"
_ODBC_REGISTRY_CANDIDATES = (
    Path("/opt/homebrew/etc/odbcinst.ini"),
    Path("/usr/local/etc/odbcinst.ini"),
)
_LEGACY_SQLSERVER_OPENSSL_CONFIG = (
    Path(__file__).resolve().parents[4] / "config" / "openssl_legacy_sqlserver.cnf"
)


class ErpPersonDatabaseClient:
    """Queries ERP/NCC personnel data from SQL Server."""

    def __init__(
        self,
        settings: ErpDatabaseSettings,
        logger: logging.Logger,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.settings = settings
        self._logger = logger
        self._connection_factory = connection_factory or _connect

    def query_by_identity_number(
        self,
        identity_number: str,
    ) -> tuple[ErpPersonRecord, ...]:
        normalized_identity = identity_number.strip().upper()
        if not _IDENTITY_PATTERN.fullmatch(normalized_identity):
            raise ErpQueryFailedError("ERP 人员身份证号格式无效")
        return self._query_exact("a.IdCard", normalized_identity)

    def query_by_name(self, name: str) -> tuple[ErpPersonRecord, ...]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ErpQueryFailedError("ERP 人员姓名不能为空")
        if any(ord(character) < 32 for character in normalized_name):
            raise ErpQueryFailedError("ERP 人员姓名包含无效控制字符")
        return self._query_exact("a.Name", normalized_name)

    def _query_exact(
        self,
        field: str,
        value: str,
    ) -> tuple[ErpPersonRecord, ...]:
        sql = _PERSON_QUERY_SQL + f"\n  AND {field} = ?"
        try:
            connection = self._connection_factory(self.settings)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ErpQueryFailedError(
                "ERP 人员数据库连接失败",
                details=str(exc),
            ) from exc
        try:
            try:
                cursor = connection.cursor()
                cursor.execute(sql, (value,))
                columns = [str(column[0]) for column in cursor.description]
                rows = (
                    dict(zip(columns, row, strict=False))
                    for row in cursor.fetchall()
                )
                return tuple(self._record(row) for row in _prioritize_rows(rows))
            except Exception as exc:
                raise ErpQueryFailedError(
                    "ERP 人员数据库查询失败",
                    details=str(exc),
                ) from exc
        finally:
            connection.close()

    @staticmethod
    def _record(row: dict[str, object]) -> ErpPersonRecord:
        return ErpPersonRecord(
            id=_text(row.get("id")),
            employee_code=_text(row.get("employee_code")),
            name=_text(row.get("name")),
            identity_number=_text(row.get("identity_number")).upper(),
            department=_text(row.get("department")),
            company=_text(row.get("company")) or _DEFAULT_COMPANY,
            status=_text(row.get("status")),
            is_quit=_text(row.get("is_quit")),
        )


def _connect(settings: ErpDatabaseSettings) -> _Connection:
    missing = [
        name
        for name, value in (
            ("host", settings.host),
            ("database", settings.database),
            ("username", settings.username),
            ("password", settings.password),
            ("driver", settings.driver),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError(
            "ERP 人员数据库未配置完整",
            details="缺少配置项：" + "、".join(f"erp.database.{name}" for name in missing),
        )
    _configure_openssl_for_legacy_sqlserver()
    _configure_odbc_driver_registry(
        settings.driver,
        registered_drivers=(),
    )
    try:
        import pyodbc
    except ImportError as exc:
        raise ConfigurationError(
            "缺少 SQL Server 数据库驱动 pyodbc",
            details="请安装项目依赖，并确认系统已安装 Microsoft ODBC Driver for SQL Server。",
        ) from exc

    _configure_odbc_driver_registry(
        settings.driver,
        registered_drivers=pyodbc.drivers(),
    )
    validate_odbc_driver_available(
        settings.driver,
        registered_drivers=pyodbc.drivers(),
    )
    connection_string = _build_connection_string(settings)
    connection = pyodbc.connect(
        connection_string,
        timeout=settings.connection_timeout_seconds,
    )
    connection.timeout = settings.query_timeout_seconds
    return connection


def validate_odbc_driver_available(
    driver: str,
    *,
    registered_drivers: Sequence[str],
) -> None:
    configured_driver = driver.strip()
    if Path(configured_driver).is_absolute():
        if Path(configured_driver).is_file():
            return
    elif configured_driver in registered_drivers:
        return
    available = "、".join(registered_drivers) or "未检测到任何 ODBC 驱动"
    raise ConfigurationError(
        f"未安装配置的 SQL Server 驱动：{configured_driver}",
        details=f"当前可用驱动：{available}",
    )


def _build_connection_string(settings: ErpDatabaseSettings) -> str:
    return (
        f"DRIVER={{{settings.driver}}};"
        f"SERVER={settings.host},{settings.port};"
        f"DATABASE={settings.database};"
        f"UID={settings.username};"
        f"PWD={settings.password};"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )


def _configure_openssl_for_legacy_sqlserver(
    *,
    environment: MutableMapping[str, str] | None = None,
    config_path: Path = _LEGACY_SQLSERVER_OPENSSL_CONFIG,
) -> None:
    env = environment if environment is not None else os.environ
    if env.get("OPENSSL_CONF"):
        return
    if config_path.is_file():
        env["OPENSSL_CONF"] = str(config_path)


def _configure_odbc_driver_registry(
    driver: str,
    *,
    registered_drivers: Sequence[str],
    registry_candidates: Sequence[Path] = _ODBC_REGISTRY_CANDIDATES,
    environment: MutableMapping[str, str] | None = None,
) -> None:
    env = environment if environment is not None else os.environ
    if Path(driver).is_absolute():
        return
    if driver in registered_drivers:
        return
    if env.get("ODBCSYSINI"):
        return
    for registry_file in registry_candidates:
        if not registry_file.is_file():
            continue
        if _odbc_registry_contains_driver(registry_file, driver):
            env["ODBCSYSINI"] = str(registry_file.parent)
            return


def _odbc_registry_contains_driver(registry_file: Path, driver: str) -> bool:
    try:
        content = registry_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return f"[{driver}]" in content


def _prioritize_rows(
    rows: Iterable[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    selected: dict[str, tuple[int, int, dict[str, object]]] = {}
    for index, row in enumerate(rows):
        identity_number = _text(row.get("identity_number")).upper()
        identity_key = identity_number or f"__row_{index}"
        priority = _integer_value(row.get("form_type_priority"), default=999)
        current = selected.get(identity_key)
        if current is None or (priority, index) < (current[0], current[1]):
            selected[identity_key] = (priority, index, row)
    return tuple(
        item[2]
        for item in sorted(selected.values(), key=lambda item: (item[1], item[0]))
    )


def _integer_value(value: object, *, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _text(value: object) -> str:
    return str(value if value is not None else "").strip()


_PERSON_QUERY_SQL = """
SELECT
    CAST(a.Id AS NVARCHAR(50)) AS id,
    a.Code AS employee_code,
    a.Name AS name,
    a.IdCard AS identity_number,
    a.DeptName AS department,
    ISNULL(NULLIF(LTRIM(RTRIM(b.ZUnit)), ''), N'南京南化建设有限公司') AS company,
    '' AS status,
    CASE
        WHEN a.IsQuit = 0 THEN N'在职'
        ELSE N'离职'
    END AS is_quit,
    b.FormType AS form_type,
    CASE b.FormType
        WHEN N'正式员工' THEN 1
        WHEN N'外聘员工' THEN 2
        WHEN N'社保挂靠台账' THEN 3
        ELSE 999
    END AS form_type_priority
FROM PB_Human a
LEFT JOIN NCC_HUM_HumanAccount b
    ON a.Id = b.ZHumID
WHERE a.IsQuit = 0
  AND b.FormType IN (N'正式员工', N'外聘员工', N'社保挂靠台账')
""".strip()
