import logging
from pathlib import Path
from types import SimpleNamespace

from ehrm.core.settings import load_settings
from ehrm.modules.erp import batch_service as batch_module
from ehrm.modules.erp.batch_service import ErpBatchUploadService
from ehrm.modules.rights_statement.excel_models import (
    EmployeeRecord,
    ExcelRunResult,
    ExcelTaskRequest,
    ExportMode,
    ItemResult,
    WorkGroup,
)


def test_shared_batch_pdf_is_uploaded_once_and_written_to_every_row(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path / "runtime",
    )
    monkeypatch.setenv(settings.erp.username_env, "tester")
    monkeypatch.setenv(settings.erp.password_env, "secret")
    pdf = tmp_path / "batch.pdf"
    pdf.write_bytes(b"%PDF-1.7\n%%EOF")
    records = (
        EmployeeRecord(2, "甲单位", "一部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"),
        EmployeeRecord(3, "乙单位", "二部", "李四", "320101199002021235", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"),
    )
    request = ExcelTaskRequest(
        groups=(WorkGroup(1, records),),
        mode=ExportMode.BATCH,
        output_dir=tmp_path,
        source_excel=tmp_path / "input.xlsx",
        upload_to_erp=True,
    )
    result = ExcelRunResult(
        mode=ExportMode.BATCH,
        total=2,
        succeeded=2,
        failed=0,
        manifest_path=tmp_path / "result.json",
        result_workbook_path=None,
        items=(
            ItemResult(2, True, "SUCCESS", "成功", pdf),
            ItemResult(3, True, "SUCCESS", "成功", pdf),
        ),
    )
    calls: list[tuple[str, Path]] = []

    class FakeSession:
        page = object()
        request = object()

        def __init__(self, *args) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def ensure_authenticated(self, credentials) -> None:
            pass

    class FakeApplicationClient:
        def __init__(self, *args) -> None:
            pass

        def find_by_code(self, code: str):
            return SimpleNamespace(id="business-id", code=code)

    class FakeAttachmentClient:
        def __init__(self, *args) -> None:
            pass

        def upload(self, application, file_path: Path):
            calls.append((application.code, file_path))
            return SimpleNamespace(id="attachment-id"), 1

    monkeypatch.setattr(batch_module, "ErpSession", FakeSession)
    monkeypatch.setattr(batch_module, "ErpApplicationClient", FakeApplicationClient)
    monkeypatch.setattr(batch_module, "ErpAttachmentClient", FakeAttachmentClient)

    items = ErpBatchUploadService(
        settings,
        logging.getLogger("test.erp.batch"),
    ).execute(request, result)

    assert calls == [("RLSQ20260819-0001", pdf.resolve())]
    assert all(item.erp_success is True for item in items)
    assert {item.erp_attachment_id for item in items} == {"attachment-id"}
