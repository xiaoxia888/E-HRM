from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from openpyxl import Workbook
import pytest

from ehrm.core.exceptions import QueryValidationError
from ehrm.core.settings import load_settings
from ehrm.entrypoints.employment_enrollment_e2e_cli import load_test_excel
from ehrm.modules.employment_enrollment.models import (
    ContractAddReason,
    ContractType,
    EmploymentEnrollmentItem,
    EmploymentEnrollmentRowError,
    InsuredIdentity,
    PositionType,
    normalize_enrollment_items,
)
from ehrm.modules.employment_enrollment.page import EmploymentEnrollmentPage
from ehrm.modules.employment_enrollment.service import EmploymentEnrollmentService


def _item(**changes: object) -> EmploymentEnrollmentItem:
    values = {
        "identity_number": "320101199001011234",
        "contract_add_reason": "新签",
        "contract_type": "固定期限",
        "contract_start_date": "2026-09-01",
        "contract_end_date": "2027-08-31",
        "position_type": "普通员工",
        "insured_identity": "企业职工",
        "monthly_wage": "446.32",
        "source_index": 2,
    }
    values.update(changes)
    return EmploymentEnrollmentItem(**values)


def test_enrollment_enum_names_and_codes_are_both_accepted() -> None:
    item = _item(
        contract_add_reason="string:1",
        contract_type="41",
        position_type="07",
        insured_identity="101",
    ).normalized()

    assert item.contract_add_reason is ContractAddReason.NEW
    assert item.contract_type is ContractType.FIXED_TERM
    assert item.position_type is PositionType.ORDINARY_EMPLOYEE
    assert item.insured_identity is InsuredIdentity.ENTERPRISE_EMPLOYEE
    assert item.monthly_wage == Decimal("446.3")


def test_renewal_drops_identity_and_wage_and_open_ended_drops_end_date() -> None:
    item = _item(
        contract_add_reason="续签",
        contract_type="无固定期限",
        contract_end_date="2099-12-31",
        monthly_wage="not-used",
    ).normalized()

    assert item.contract_add_reason is ContractAddReason.RENEWAL
    assert item.contract_type is ContractType.OPEN_ENDED
    assert item.contract_end_date is None
    assert item.monthly_wage is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5596.86", Decimal("5596.9")),
        ("5596.84", Decimal("5596.8")),
        ("5596.85", Decimal("5596.9")),
        (5596, Decimal("5596.0")),
    ],
)
def test_monthly_wage_is_rounded_half_up_to_one_decimal(
    raw: object,
    expected: Decimal,
) -> None:
    assert _item(monthly_wage=raw).normalized().monthly_wage == expected


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"monthly_wage": "abc"}, "月缴费工资必须是数值"),
        ({"contract_end_date": None}, "劳动合同终止日期"),
        ({"contract_end_date": "2025-01-01"}, "不能早于"),
        ({"position_type": "未知岗位"}, "岗位工种"),
    ],
)
def test_enrollment_rejects_invalid_business_input(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(QueryValidationError, match=message):
        _item(**changes).normalized()


def test_all_seven_position_types_have_recorded_codes() -> None:
    assert [(item.value, item.display_name) for item in PositionType] == [
        ("01", "单位负责人"),
        ("02", "管理人员"),
        ("03", "专业技术人员"),
        ("04", "生产运输操作人员"),
        ("05", "商业和其他服务业"),
        ("06", "农林牧渔从业人员"),
        ("07", "普通员工"),
    ]


def test_excel_adapter_reads_new_and_renewal_rows(tmp_path: Path) -> None:
    path = tmp_path / "参保测试.xlsx"
    workbook = Workbook()
    workbook.active.append(
        [
            "身份证号",
            "合同增加原因",
            "合同类别",
            "劳动合同开始日期",
            "劳动合同终止日期",
            "岗位工种",
            "参保身份",
            "月缴费工资",
        ]
    )
    workbook.active.append(
        [
            "320101199001011234",
            "新签",
            "固定期限",
            date(2026, 9, 1),
            date(2027, 8, 31),
            "普通员工",
            "企业职工",
            446.32,
        ]
    )
    workbook.active.append(
        [
            "320101199002021235",
            "续签",
            "无固定期限",
            date(2026, 9, 1),
            None,
            "管理人员",
            None,
            None,
        ]
    )
    workbook.save(path)
    workbook.close()

    items = load_test_excel(path)

    assert len(items) == 2
    assert items[0].monthly_wage == Decimal("446.3")
    assert items[1].contract_end_date is None
    assert items[1].monthly_wage is None


def test_duplicate_identity_is_rejected_before_browser() -> None:
    with pytest.raises(QueryValidationError, match="身份证号重复"):
        normalize_enrollment_items([_item(), _item(source_index=3)])


def _page(tmp_path: Path) -> EmploymentEnrollmentPage:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = Mock(url="https://rs.jshrss.jiangsu.gov.cn/index/")
    page.wait_for_timeout = lambda _milliseconds: None
    return EmploymentEnrollmentPage(page, settings)


def _frame_with_search() -> tuple[Mock, Mock]:
    frame = Mock()
    search_container = Mock()
    search = search_container.get_by_role.return_value.first
    search.input_value.return_value = "320101199001011234"

    def locator(selector: str):
        if selector == "sipub-person-quick-search":
            return search_container
        return Mock(name=selector)

    frame.locator.side_effect = locator
    return frame, search


def test_new_fixed_term_fills_identity_wage_and_end_date(tmp_path: Path) -> None:
    automation = _page(tmp_path)
    frame, _search = _frame_with_search()
    automation.pacer.perform = Mock(side_effect=lambda action: action())
    automation._wait_for_query_result = Mock()
    automation._select_code = Mock()
    automation._fill_date = Mock()
    automation._fill_value = Mock()
    automation._raise_on_feedback = Mock()
    automation._verify_form = Mock()
    item = _item().normalized()

    automation.fill_item(frame, item)

    selected_labels = [args[2] for args, _kwargs in automation._select_code.call_args_list]
    assert selected_labels == ["合同增加原因", "合同类别", "岗位工种", "参保身份"]
    assert [args[1] for args, _kwargs in automation._fill_date.call_args_list] == [
        "劳动合同开始日期",
        "劳动合同终止日期",
    ]
    automation._fill_value.assert_called_once()


def test_renewal_open_ended_skips_identity_wage_and_end_date(tmp_path: Path) -> None:
    automation = _page(tmp_path)
    frame, _search = _frame_with_search()
    automation.pacer.perform = Mock(side_effect=lambda action: action())
    automation._wait_for_query_result = Mock()
    automation._select_code = Mock()
    automation._fill_date = Mock()
    automation._fill_value = Mock()
    automation._raise_on_feedback = Mock()
    automation._verify_form = Mock()
    item = _item(
        contract_add_reason="续签",
        contract_type="无固定期限",
        contract_end_date=None,
        monthly_wage=None,
    ).normalized()

    automation.fill_item(frame, item)

    selected_labels = [args[2] for args, _kwargs in automation._select_code.call_args_list]
    assert selected_labels == ["合同增加原因", "合同类别", "岗位工种"]
    automation._fill_date.assert_called_once_with(
        frame, "劳动合同开始日期", date(2026, 9, 1)
    )
    automation._fill_value.assert_not_called()


def test_readonly_contract_date_uses_dom_events_instead_of_fill(
    tmp_path: Path,
) -> None:
    automation = _page(tmp_path)
    frame = Mock()
    field = Mock()
    current_value = {"value": ""}
    field.is_enabled.return_value = True
    field.input_value.side_effect = lambda: current_value["value"]

    def evaluate(_script: str, value: str) -> None:
        current_value["value"] = value

    field.evaluate.side_effect = evaluate
    automation._labeled_input = Mock(return_value=field)
    automation.pacer.perform = Mock(side_effect=lambda action: action())

    automation._fill_date(frame, "劳动合同开始日期", date(2026, 9, 18))

    field.evaluate.assert_called_once()
    field.fill.assert_not_called()
    assert current_value["value"] == "2026-09-18"


def test_service_records_business_error_and_continues(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = Mock()
    page.context.new_page.return_value = Mock()
    completed = []
    with patch(
        "ehrm.modules.employment_enrollment.service.EmploymentEnrollmentPage"
    ) as page_class:
        page_class.return_value.fill_item.side_effect = [
            EmploymentEnrollmentRowError(
                "在本单位已存在参保信息，不能办理参保，可以办理续签或者以其他参保身份参保",
                reason_code="BUSINESS_MESSAGE",
            ),
            None,
        ]
        result = EmploymentEnrollmentService(
            settings,
            Mock(),
            result_callback=completed.append,
        ).prepare_with_page(
            page,
            [
                _item(),
                _item(identity_number="320101199002021235", source_index=3),
            ],
        )

    assert [row.success for row in result.results] == [False, True]
    assert result.results[0].code == "BUSINESS_MESSAGE"
    assert completed == list(result.results)
    page.context.new_page.assert_called_once()


def test_recorded_existing_insurance_inline_message_is_detected(tmp_path: Path) -> None:
    automation = _page(tmp_path)
    frame = Mock()
    matches = frame.get_by_text.return_value
    matches.count.return_value = 1
    message = matches.nth.return_value
    message.count.return_value = 1
    message.is_visible.return_value = True
    message.inner_text.return_value = (
        "★在本单位已存在参保信息，不能办理参保，可以办理续签或者以其他参保身份参保;"
    )
    automation._topmost_dialog = Mock(return_value=None)

    assert "不能办理参保" in automation._feedback_text(frame)
