from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ehrm.core.exceptions import ErpQueryFailedError
from ehrm.core.settings import load_settings
from ehrm.modules.erp.client import ErpTaskClient
from ehrm.modules.erp.models import ErpTaskStatus


class FakeFrame:
    def evaluate(self, expression: str, value: str | None = None):
        if "typeof base64swhere" in expression:
            return True
        return f"encoded:{value}"


class FakePage:
    frames = [FakeFrame()]


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status = 200
        self.url = "https://erp.njncc.com/Form/GridPageLoad"

    def json(self) -> dict:
        return self._payload

    def dispose(self) -> None:
        pass


class PaginatedRequest:
    def __init__(self, pages: list[list[dict]], total_count: int) -> None:
        self.pages = pages
        self.total_count = total_count
        self.forms: list[dict[str, str]] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        form = kwargs["form"]
        self.forms.append(form)
        page_index = int(form["pageIndex"])
        records = self.pages[page_index] if page_index < len(self.pages) else []
        return FakeResponse(
            {
                "success": True,
                "data": {
                    "value": json.dumps(records, ensure_ascii=False),
                    "totalcount": self.total_count,
                },
            }
        )


def _settings(tmp_path: Path):
    return load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path,
    ).erp


def test_query_tasks_by_transaction_type_fetches_every_page(tmp_path: Path) -> None:
    request = PaginatedRequest(
        [
            [
                {
                    "ID": "id-3",
                    "Code": "RLSQ-003",
                    "Name": "任务三",
                    "ProposedDate": "2026-08-20T00:00:00",
                    "ProbType": "社保咨询",
                    "ProbDesc": "<p>张三<br>近一年</p>",
                    "Status": 0,
                    "Originator": "申请人甲",
                    "DeptName": "第一分公司",
                },
                {
                    "ID": "id-2",
                    "Code": "RLSQ-002",
                    "Name": "任务二",
                    "RegDate": "2026-08-19T08:30:00",
                    "ProbType": "社保咨询",
                    "ProbDescText": "李四近半年",
                    "Status": "1",
                },
            ],
            [
                {
                    "ID": "id-1",
                    "Code": "RLSQ-001",
                    "Name": "任务一",
                    "ProposedDate": "2026-08-18T00:00:00",
                    "ProbType": "社保咨询",
                }
            ],
        ],
        total_count=3,
    )
    client = ErpTaskClient(
        _settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.tasks"),
    )

    result = client.query_by_transaction_type("社保咨询", page_size=2)

    assert result.total_count == 3
    assert result.pages_fetched == 2
    assert [record.code for record in result.records] == [
        "RLSQ-003",
        "RLSQ-002",
        "RLSQ-001",
    ]
    assert result.records[0].initiated_date == "2026-08-20"
    assert result.records[0].description == "张三\n近一年"
    assert result.records[0].status == "0"
    assert request.forms[0]["swhere"] == (
        "encoded: 1=1   and ProbType = '社保咨询'"
    )
    assert request.forms[0]["pageIndex"] == "0"
    assert request.forms[0]["index"] == "0"
    assert request.forms[1]["pageIndex"] == "1"
    assert request.forms[1]["index"] == "2"


def test_transaction_type_is_escaped_as_sql_string_literal(tmp_path: Path) -> None:
    request = PaginatedRequest([[]], total_count=0)
    client = ErpTaskClient(
        _settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.tasks.escape"),
    )

    client.query_by_transaction_type("员工'咨询", page_size=50)

    assert request.forms[0]["swhere"] == (
        "encoded: 1=1   and ProbType = '员工''咨询'"
    )


def test_query_combines_transaction_type_status_and_code(tmp_path: Path) -> None:
    request = PaginatedRequest([[]], total_count=0)
    client = ErpTaskClient(
        _settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.tasks.filters"),
    )

    result = client.query_tasks(
        "社保咨询",
        status=ErpTaskStatus.IN_APPROVAL,
        application_code="RLSQ20260818-0004",
    )

    assert result.status is ErpTaskStatus.IN_APPROVAL
    assert result.application_code == "RLSQ20260818-0004"
    assert request.forms[0]["swhere"] == (
        "encoded: 1=1   and ProbType = '社保咨询'"
        "   and Status = 20"
        "   and Code = 'RLSQ20260818-0004'"
    )


def test_query_rejects_unknown_status(tmp_path: Path) -> None:
    request = PaginatedRequest([[]], total_count=0)
    client = ErpTaskClient(
        _settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.tasks.status"),
    )

    with pytest.raises(ErpQueryFailedError, match="申请状态无效"):
        client.query_tasks("社保咨询", status=99)

    assert request.forms == []


def test_query_combines_multiple_application_statuses(tmp_path: Path) -> None:
    request = PaginatedRequest([[]], total_count=0)
    client = ErpTaskClient(
        _settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.tasks.multiple-statuses"),
    )

    result = client.query_tasks(
        "社保咨询",
        statuses=[50, 0, 20, 50],
    )

    assert result.status is None
    assert result.statuses == (
        ErpTaskStatus.APPROVED,
        ErpTaskStatus.NEW,
        ErpTaskStatus.IN_APPROVAL,
    )
    assert request.forms[0]["swhere"] == (
        "encoded: 1=1   and ProbType = '社保咨询'"
        "   and Status in (50, 0, 20)"
    )


def test_status_display_uses_chinese_enum_label() -> None:
    assert ErpTaskStatus.display("50") == "50（批准）"
    assert ErpTaskStatus.display(0) == "0（新增）"


def test_query_adds_inclusive_application_date_range(tmp_path: Path) -> None:
    request = PaginatedRequest([[]], total_count=0)
    client = ErpTaskClient(
        _settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.tasks.dates"),
    )

    result = client.query_tasks(
        "社保咨询",
        start_date="2026-08-01",
        end_date="2026-08-18",
    )

    assert result.start_date == "2026-08-01"
    assert result.end_date == "2026-08-18"
    assert request.forms[0]["swhere"] == (
        "encoded: 1=1   and ProbType = '社保咨询'"
        "   and ProposedDate >= '2026-08-01 00:00:00'"
        "   and ProposedDate < '2026-08-19 00:00:00'"
    )


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        ("2026/08/01", "", "开始日期格式不正确"),
        ("", "2026-02-30", "结束日期格式不正确"),
        ("2026-08-20", "2026-08-18", "开始日期不能晚于结束日期"),
    ],
)
def test_query_rejects_invalid_application_date_range(
    tmp_path: Path,
    start_date: str,
    end_date: str,
    message: str,
) -> None:
    request = PaginatedRequest([[]], total_count=0)
    client = ErpTaskClient(
        _settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.tasks.invalid-dates"),
    )

    with pytest.raises(ErpQueryFailedError, match=message):
        client.query_tasks(
            "社保咨询",
            start_date=start_date,
            end_date=end_date,
        )

    assert request.forms == []
