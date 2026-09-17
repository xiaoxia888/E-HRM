from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from ehrm.core.exceptions import ConfigurationError, ErpQueryFailedError
from ehrm.core.settings import load_settings
from ehrm.modules.erp import person_database
from ehrm.modules.erp.person_database import (
    ErpPersonDatabaseClient,
    _build_connection_string,
    _configure_odbc_driver_registry,
    _configure_openssl_for_legacy_sqlserver,
)
from ehrm.modules.erp.person_service import ErpPersonLookupService


class FakeCursor:
    def __init__(
        self,
        rows: list[tuple[object, ...]],
        *,
        description: list[tuple[str]] | None = None,
    ) -> None:
        self.description = description or [
            ("id",),
            ("employee_code",),
            ("name",),
            ("identity_number",),
            ("department",),
            ("company",),
            ("status",),
            ("is_quit",),
        ]
        self.rows = rows
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def execute(self, sql: str, params: tuple[object, ...]) -> "FakeCursor":
        self.sql = sql
        self.params = params
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class FailingCursor(FakeCursor):
    def execute(self, sql: str, params: tuple[object, ...]) -> "FailingCursor":
        super().execute(sql, params)
        raise RuntimeError("database unavailable")


def _settings(tmp_path: Path):
    return load_settings(Path("config/settings.toml"), data_root=tmp_path)


def test_database_connection_string_disables_sql_server_encryption_by_default(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).erp_database

    connection_string = _build_connection_string(settings)

    assert "Encrypt=no;" in connection_string
    assert "TrustServerCertificate=yes;" in connection_string


def test_configure_openssl_for_legacy_sqlserver_sets_project_tls_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENSSL_CONF", raising=False)

    _configure_openssl_for_legacy_sqlserver()

    configured_path = Path(os.environ["OPENSSL_CONF"])
    assert configured_path.name == "openssl_legacy_sqlserver.cnf"
    assert configured_path.is_file()


def test_configure_odbc_driver_registry_uses_homebrew_ini_when_driver_unlisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_dir = tmp_path / "etc"
    registry_dir.mkdir()
    registry_file = registry_dir / "odbcinst.ini"
    registry_file.write_text(
        "[ODBC Driver 17 for SQL Server]\n"
        "Driver=/opt/homebrew/lib/libmsodbcsql.17.dylib\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ODBCSYSINI", raising=False)

    _configure_odbc_driver_registry(
        "ODBC Driver 17 for SQL Server",
        registered_drivers=(),
        registry_candidates=(registry_file,),
    )

    assert Path(os.environ["ODBCSYSINI"]) == registry_dir


def test_validate_odbc_driver_available_rejects_missing_configured_driver() -> None:
    validator = getattr(
        person_database,
        "validate_odbc_driver_available",
        None,
    )
    assert validator is not None

    with pytest.raises(ConfigurationError, match="ODBC Driver 17 for SQL Server"):
        validator(
            "ODBC Driver 17 for SQL Server",
            registered_drivers=("SQL Server",),
        )


def test_validate_odbc_driver_available_accepts_exact_configured_driver() -> None:
    validator = getattr(
        person_database,
        "validate_odbc_driver_available",
        None,
    )
    assert validator is not None

    validator(
        "ODBC Driver 17 for SQL Server",
        registered_drivers=("ODBC Driver 17 for SQL Server",),
    )


def test_database_person_query_uses_identity_condition_and_default_company(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).erp_database
    cursor = FakeCursor(
        [
            (
                "person-id",
                "2026001",
                "夏国玺",
                "320830199709095235",
                "技术中心",
                "",
                "",
                "在职",
            )
        ]
    )
    connection = FakeConnection(cursor)
    client = ErpPersonDatabaseClient(
        settings,
        logging.getLogger("test.erp.person.database"),
        connection_factory=lambda _settings: connection,
    )

    result = client.query_by_identity_number("320830199709095235")

    assert len(result) == 1
    assert result[0].id == "person-id"
    assert result[0].employee_code == "2026001"
    assert result[0].name == "夏国玺"
    assert result[0].identity_number == "320830199709095235"
    assert result[0].department == "技术中心"
    assert result[0].company == "南京南化建设有限公司"
    assert result[0].is_quit == "在职"
    assert "a.IdCard = ?" in cursor.sql
    assert "WHERE a.IsQuit = 0" in cursor.sql
    assert "b.FormType IN" in cursor.sql
    assert cursor.params == ("320830199709095235",)
    assert connection.closed is True


def test_database_person_query_uses_name_condition(tmp_path: Path) -> None:
    settings = _settings(tmp_path).erp_database
    cursor = FakeCursor(
        [
            (
                "person-id",
                "2026002",
                "王明明",
                "410423199005124058",
                "第十六分公司",
                "南京南化建设有限公司",
                "",
                "离职",
            )
        ]
    )
    client = ErpPersonDatabaseClient(
        settings,
        logging.getLogger("test.erp.person.database.name"),
        connection_factory=lambda _settings: FakeConnection(cursor),
    )

    result = client.query_by_name("王明明")

    assert [item.identity_number for item in result] == ["410423199005124058"]
    assert "a.Name = ?" in cursor.sql
    assert "WHERE a.IsQuit = 0" in cursor.sql
    assert cursor.params == ("王明明",)


def test_database_person_query_keeps_highest_priority_form_type_for_same_identity(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).erp_database
    description = [
        ("id",),
        ("employee_code",),
        ("name",),
        ("identity_number",),
        ("department",),
        ("company",),
        ("status",),
        ("is_quit",),
        ("form_type",),
        ("form_type_priority",),
    ]
    identity = "321281199001014530"
    cursor = FakeCursor(
        [
            (
                "person-id-social",
                "S001",
                "周加慧",
                identity,
                "挂靠部",
                "南京南化建设有限公司",
                "",
                "在职",
                "社保挂靠台账",
                3,
            ),
            (
                "person-id-formal",
                "F001",
                "周加慧",
                identity,
                "技术质量部",
                "南京南化建设有限公司",
                "",
                "在职",
                "正式员工",
                1,
            ),
            (
                "person-id-contractor",
                "W001",
                "周加慧",
                identity,
                "外聘部",
                "南京南化建设有限公司",
                "",
                "在职",
                "外聘员工",
                2,
            ),
        ],
        description=description,
    )
    client = ErpPersonDatabaseClient(
        settings,
        logging.getLogger("test.erp.person.database.priority"),
        connection_factory=lambda _settings: FakeConnection(cursor),
    )

    result = client.query_by_name("周加慧")

    assert len(result) == 1
    assert result[0].id == "person-id-formal"
    assert result[0].employee_code == "F001"
    assert result[0].department == "技术质量部"


def test_database_person_query_wraps_database_errors_and_closes_connection(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).erp_database
    cursor = FailingCursor([])
    connection = FakeConnection(cursor)
    client = ErpPersonDatabaseClient(
        settings,
        logging.getLogger("test.erp.person.database.error"),
        connection_factory=lambda _settings: connection,
    )

    with pytest.raises(ErpQueryFailedError, match="ERP 人员数据库查询失败"):
        client.query_by_identity_number("320830199709095235")

    assert connection.closed is True


def test_person_lookup_service_uses_sql_server_database_without_erp_session(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    cursor = FakeCursor(
        [
            (
                "identity-id",
                "2026003",
                "李四",
                "320124199410222629",
                "第十五分公司",
                None,
                "",
                "在职",
            )
        ]
    )

    service = ErpPersonLookupService(
        settings,
        logging.getLogger("test.erp.person.service.database"),
        database_client_factory=lambda: ErpPersonDatabaseClient(
            settings.erp_database,
            logging.getLogger("test.erp.person.service.database.client"),
            connection_factory=lambda _settings: FakeConnection(cursor),
        ),
    )

    matches_by_identity, matches_by_name = service.lookup_people(
        identity_numbers=["320124199410222629"],
        names=[],
    )

    assert not matches_by_name
    assert matches_by_identity["320124199410222629"][0].company == (
        "南京南化建设有限公司"
    )
