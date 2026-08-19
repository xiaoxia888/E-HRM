from pathlib import Path

import pytest

from ehrm.core.exceptions import QueryValidationError
from ehrm.modules.rights_statement.models import RightsStatementQuery


def make_query(**overrides: object) -> RightsStatementQuery:
    values = {
        "start_month": "2026-01",
        "end_month": "2026-06",
        "insurance_type": "养老保险",
        "employee_name": "测试人员",
        "output_dir": Path("downloads"),
    }
    values.update(overrides)
    return RightsStatementQuery(**values)


def test_valid_query() -> None:
    make_query().validate()


@pytest.mark.parametrize("month", ["2026-1", "26-01", "2026-13", ""])
def test_invalid_month(month: str) -> None:
    with pytest.raises(QueryValidationError):
        make_query(start_month=month).validate()


def test_start_must_not_be_after_end() -> None:
    with pytest.raises(QueryValidationError):
        make_query(start_month="2026-07", end_month="2026-06").validate()

