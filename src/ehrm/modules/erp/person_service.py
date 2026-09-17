from __future__ import annotations

import logging
from typing import Callable, Iterable

from ehrm.core.settings import AppSettings
from ehrm.modules.erp.models import ErpCredentials, ErpPersonRecord
from ehrm.modules.erp.person_database import ErpPersonDatabaseClient


DatabaseClientFactory = Callable[[], ErpPersonDatabaseClient]


class ErpPersonLookupService:
    """Looks up multiple people from ERP/NCC SQL Server personnel data."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        database_client_factory: DatabaseClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check
        self._database_client_factory = database_client_factory

    def lookup_names(
        self,
        names: Iterable[str],
        *,
        credentials: ErpCredentials | None = None,
    ) -> dict[str, tuple[ErpPersonRecord, ...]]:
        _, name_results = self.lookup_people(
            names=names,
            credentials=credentials,
        )
        return name_results

    def lookup_people(
        self,
        *,
        identity_numbers: Iterable[str] = (),
        names: Iterable[str] = (),
        credentials: ErpCredentials | None = None,
    ) -> tuple[
        dict[str, tuple[ErpPersonRecord, ...]],
        dict[str, tuple[ErpPersonRecord, ...]],
    ]:
        _ = credentials
        requested_identities = tuple(
            identity.strip().upper()
            for identity in identity_numbers
            if identity.strip()
        )
        requested_names = tuple(
            name.strip() for name in names if name.strip()
        )
        if not requested_identities and not requested_names:
            return {}, {}
        identity_results: dict[str, tuple[ErpPersonRecord, ...]] = {}
        name_results: dict[str, tuple[ErpPersonRecord, ...]] = {}
        client = self._database_client()
        total = len(requested_identities) + len(requested_names)
        sequence = 0
        for identity in requested_identities:
            sequence += 1
            self._progress(
                f"ERP数据库：正在补全人员信息 {sequence}/{total}（身份证匹配）"
            )
            if identity not in identity_results:
                identity_results[identity] = client.query_by_identity_number(
                    identity
                )
        for name in requested_names:
            sequence += 1
            self._progress(
                f"ERP数据库：正在补全人员信息 {sequence}/{total}：{name}"
            )
            if name not in name_results:
                name_results[name] = client.query_by_name(name)
        return identity_results, name_results

    def _database_client(self) -> ErpPersonDatabaseClient:
        if self._database_client_factory is not None:
            return self._database_client_factory()
        return ErpPersonDatabaseClient(
            self._settings.erp_database,
            self._logger,
        )

    def _progress(self, text: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(text)
