from pathlib import Path

from ehrm.core.settings import load_settings
from ehrm.modules.rights_statement.excel_models import EmployeeRecord, WorkGroup
from ehrm.modules.rights_statement.page import RightsStatementPage


class FakeLocator:
    def __init__(self, values: dict[str, str], selector: str) -> None:
        self.values = values
        self.selector = selector

    def fill(self, value: str) -> None:
        self.values[self.selector] = value


class FakePage:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.values, selector)


def record(identity: str) -> EmployeeRecord:
    return EmployeeRecord(
        row_number=2,
        unit="测试单位",
        department="测试部门",
        name="测试人员",
        identity_number=identity,
        insurance_type="养老",
        start_month="2025-01",
        end_month="2025-06",
    )


def test_identity_number_is_used_before_name() -> None:
    settings = load_settings(Path("config/settings.example.toml"))
    fake_page = FakePage()
    page = RightsStatementPage(fake_page, settings, object())  # type: ignore[arg-type]

    page._fill_person_query(record("320101199001011234"))

    assert fake_page.values[settings.rights_statement.social_security_number] == "320101199001011234"
    assert fake_page.values[settings.rights_statement.employee_name] == ""


def test_name_is_only_the_empty_identity_fallback() -> None:
    settings = load_settings(Path("config/settings.example.toml"))
    fake_page = FakePage()
    page = RightsStatementPage(fake_page, settings, object())  # type: ignore[arg-type]

    page._fill_person_query(record(""))

    assert fake_page.values[settings.rights_statement.social_security_number] == ""
    assert fake_page.values[settings.rights_statement.employee_name] == "测试人员"


def test_unchanged_group_filters_are_not_selected_again() -> None:
    settings = load_settings(Path("config/settings.example.toml"))
    page = RightsStatementPage(FakePage(), settings, object())  # type: ignore[arg-type]
    calls: list[tuple[str, str]] = []
    actual: dict[str, str | None] = {
        "insurance": None,
        settings.rights_statement.start_month: None,
        settings.rights_statement.end_month: None,
    }

    def select_insurance(value: str) -> None:
        calls.append(("insurance", value))
        actual["insurance"] = value

    def set_month(selector: str, value: str) -> None:
        calls.append((selector, value))
        actual[selector] = value

    page._insurance_matches = lambda value: actual["insurance"] == value  # type: ignore[method-assign]
    page._month_matches = lambda selector, value: actual[selector] == value  # type: ignore[method-assign]
    page._select_insurance = select_insurance  # type: ignore[method-assign]
    page._set_month = set_month  # type: ignore[method-assign]

    first = record("320101199001011234")
    same_start_new_end = EmployeeRecord(
        row_number=3,
        unit=first.unit,
        department=first.department,
        name="第二人",
        identity_number="320101199001015678",
        insurance_type=first.insurance_type,
        start_month=first.start_month,
        end_month="2025-07",
    )

    page.prepare_group(WorkGroup(1, (first,)))
    page.prepare_group(WorkGroup(2, (same_start_new_end,)))
    # Simulates a user manually changing the visible page after the cache was set.
    actual[settings.rights_statement.start_month] = "2024-12"
    page.prepare_group(WorkGroup(3, (same_start_new_end,)))

    assert calls == [
        ("insurance", first.insurance_type),
        (settings.rights_statement.start_month, first.start_month),
        (settings.rights_statement.end_month, first.end_month),
        (settings.rights_statement.end_month, same_start_new_end.end_month),
        (settings.rights_statement.start_month, same_start_new_end.start_month),
    ]
