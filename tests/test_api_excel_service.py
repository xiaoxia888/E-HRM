import logging
from pathlib import Path

from ehrm.core.error_catalog import ErrorCode
from ehrm.core.exceptions import AuthenticationFailedError
from ehrm.core.settings import load_settings
from ehrm.modules.rights_statement.api_excel_service import (
    ApiExcelRightsStatementService,
)
from ehrm.modules.rights_statement.api_models import (
    PersonQueryResult,
    PersonRecord,
    QueryPageInfo,
)
from ehrm.modules.rights_statement.excel_models import (
    EmployeeRecord,
    ExportMode,
    WorkGroup,
)


def _record(row: int, name: str, identity: str) -> EmployeeRecord:
    return EmployeeRecord(
        row_number=row,
        unit="测试单位",
        department="人事部",
        name=name,
        identity_number=identity,
        insurance_type="养老",
        start_month="2026-01",
        end_month="2026-08",
        task_number="RLSQ-TEST",
    )


def _query_result(person: PersonRecord) -> PersonQueryResult:
    return PersonQueryResult(
        page=QueryPageInfo(
            api_code="test",
            page_number=1,
            page_size=100,
            total_page=1,
            total_count=1,
            error_info=None,
        ),
        records=(person,),
    )


def test_api_excel_service_executes_complete_batch_print_flow(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path / "runtime",
    )
    service = ApiExcelRightsStatementService(
        settings,
        logging.getLogger("test.api-excel"),
    )
    first = _record(2, "张三", "320101199001011234")
    second = _record(3, "李四", "320101199002021235")
    people = {
        first.identity_number: PersonRecord(
            "person-1", first.identity_number, first.name
        ),
        second.identity_number: PersonRecord(
            "person-2", second.identity_number, second.name
        ),
    }
    queries = []
    print_calls = []

    def query_people(query):
        queries.append(query)
        return _query_result(people[query.identity_number])

    def download_rights_bill(print_request, output_dir, filename):
        print_calls.append((print_request, output_dir, filename))
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / filename
        destination.write_bytes(b"%PDF-1.4\ntest\n%%EOF")
        return destination

    result = service.execute_with_api(
        [WorkGroup(sequence=1, records=(first, second))],
        ExportMode.BATCH,
        tmp_path / "output",
        None,
        query_people=query_people,
        download_rights_bill=download_rights_bill,
    )

    assert [query.identity_number for query in queries] == [
        first.identity_number,
        second.identity_number,
    ]
    assert all(query.start_month == "202601" for query in queries)
    assert result.succeeded == 2
    assert result.failed == 0
    assert {item.code for item in result.items} == {str(ErrorCode.SUCCESS)}
    assert len(print_calls) == 1
    print_request, output_dir, filename = print_calls[0]
    assert print_request.person_ids == ("person-1", "person-2")
    assert print_request.insurance.value == "110"
    assert output_dir == tmp_path / "output" / "PDF" / "测试单位" / "批量"
    assert filename == "RLSQ-TEST_养老_202601-202608_批次1_2人.pdf"
    assert all(item.file_path == output_dir / filename for item in result.items)


def test_api_excel_service_does_not_print_an_unmatched_person(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path / "runtime",
    )
    service = ApiExcelRightsStatementService(
        settings,
        logging.getLogger("test.api-excel-unmatched"),
    )
    record = _record(2, "张三", "320101199001011234")
    no_match = PersonRecord("other", "320101199001019999", "其他人员")
    download_calls = []

    result = service.execute_with_api(
        [WorkGroup(sequence=1, records=(record,))],
        ExportMode.INDIVIDUAL,
        tmp_path / "output",
        None,
        query_people=lambda _query: _query_result(no_match),
        download_rights_bill=lambda *args: download_calls.append(args),
    )

    assert result.succeeded == 0
    assert result.failed == 1
    assert result.items[0].code == str(ErrorCode.EMPLOYEE_NOT_FOUND)
    assert download_calls == []


def test_api_excel_service_stops_batch_after_login_failure(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path / "runtime",
    )
    service = ApiExcelRightsStatementService(
        settings,
        logging.getLogger("test.api-excel-auth"),
    )
    records = (
        _record(2, "张三", "320101199001011234"),
        _record(3, "李四", "320101199002021235"),
    )
    query_count = 0

    def failed_login(_query):
        nonlocal query_count
        query_count += 1
        raise AuthenticationFailedError("账号密码错误")

    try:
        service.execute_with_api(
            [WorkGroup(sequence=1, records=records)],
            ExportMode.BATCH,
            tmp_path / "output",
            None,
            query_people=failed_login,
            download_rights_bill=lambda *_args: Path("unused.pdf"),
        )
    except AuthenticationFailedError as exc:
        assert exc.message == "账号密码错误"
    else:
        raise AssertionError("登录失败应立即终止整批任务")

    assert query_count == 1
