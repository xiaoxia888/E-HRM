from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ehrm.modules.ai.business_classification import BusinessClassification
from ehrm.modules.erp.models import ErpTaskQueryResult, ErpTaskRecord


def _record(code: str, transaction_type: str) -> ErpTaskRecord:
    return ErpTaskRecord(
        id=f"id-{code}",
        code=code,
        initiated_date="2026-09-28",
        title="请停止缴纳社保",
        description="张伟从十月开始停保",
        transaction_type=transaction_type,
        status="50",
        originator="申请人",
        department="部门",
    )


@pytest.mark.parametrize(
    ("arguments", "expected_filters"),
    [
        (["--code", "RLSQ-001"], ("RLSQ-001", "", "")),
        (
            ["--start-date", "2026-09-27", "--end-date", "2026-09-28"],
            ("", "2026-09-27", "2026-09-28"),
        ),
    ],
)
def test_script_queries_both_erp_types_and_outputs_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected_filters: tuple[str, str, str],
) -> None:
    from ehrm.entrypoints import erp_business_classification_cli as cli

    queries: list[tuple[str, str, str, str]] = []

    class FakeQueryService:
        def __init__(self, *args, **kwargs):
            pass

        def query_tasks(
            self,
            transaction_type: str,
            *,
            application_code: str,
            start_date: str,
            end_date: str,
            page_size: int,
        ) -> ErpTaskQueryResult:
            queries.append((transaction_type, application_code, start_date, end_date))
            records = (
                (_record("RLSQ-001", transaction_type),)
                if transaction_type == "社保咨询"
                else ()
            )
            return ErpTaskQueryResult(
                transaction_type=transaction_type,
                records=records,
                total_count=len(records),
                pages_fetched=1,
            )

    class FakeClassifier:
        def __init__(self, *args, **kwargs):
            pass

        def ensure_available(self) -> None:
            pass

        def classify(self, record: ErpTaskRecord, mode: str) -> BusinessClassification:
            return BusinessClassification(
                business_type="退工停保登记",
                source_transaction_type=record.transaction_type,
                classified=True,
                evidence="停止缴纳社保",
                reason="",
            )

    monkeypatch.setattr(cli, "application_runtime_root", lambda config: tmp_path)
    monkeypatch.setattr(cli, "configure_logging", lambda path: logging.getLogger("test"))
    monkeypatch.setattr(cli, "ErpTaskQueryService", FakeQueryService)
    monkeypatch.setattr(cli, "OllamaTaskExtractionClient", FakeClassifier)
    output = tmp_path / "classification.json"

    exit_code = cli.main([*arguments, "--output", str(output)])

    assert exit_code == 0
    assert queries == [
        ("社保咨询", *expected_filters),
        ("单位社保权益单", *expected_filters),
    ]
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"] == {"total": 1, "classified": 1, "unclear": 0, "failed": 0}
    assert report["records"][0]["business_type"] == "退工停保登记"
    assert report["records"][0]["erp_record_id"] == "id-RLSQ-001"


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--start-date", "2026-09-28"],
        ["--code", "RLSQ-001", "--end-date", "2026-09-28"],
        ["--start-date", "2026-09-29", "--end-date", "2026-09-28"],
    ],
)
def test_script_rejects_missing_or_conflicting_query_range(arguments: list[str]) -> None:
    from ehrm.entrypoints.erp_business_classification_cli import _parser

    with pytest.raises(SystemExit):
        _parser().parse_args(arguments)
