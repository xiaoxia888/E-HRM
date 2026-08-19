from __future__ import annotations

import json
import logging
from pathlib import Path
from zipfile import ZipFile

import pytest

from ehrm.core.exceptions import ErpQueryFailedError, FileValidationError
from ehrm.core.settings import load_settings
from ehrm.modules.erp.client import ErpApplicationClient, ErpAttachmentClient
from ehrm.modules.erp.file_validation import ErpUploadFileValidator
from ehrm.modules.erp.models import ErpApplicationRecord, ErpAttachmentRecord


class FakeFrame:
    def evaluate(self, expression: str, value: str | None = None):
        if "typeof base64swhere" in expression:
            return True
        return f"encoded:{value}"


class FakePage:
    frames = [FakeFrame()]


class FakeResponse:
    def __init__(self, payload: dict, *, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.url = "https://erp.njncc.com/test"
        self.disposed = False

    def json(self) -> dict:
        return self._payload

    def dispose(self) -> None:
        self.disposed = True


class QueryRequest:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.form: dict | None = None

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.form = kwargs["form"]
        return FakeResponse(
            {
                "success": True,
                "data": {"value": json.dumps(self.records, ensure_ascii=False)},
            }
        )


def _erp_settings(tmp_path: Path):
    return load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path,
    ).erp


def test_application_query_encodes_swhere_and_uses_exact_match(tmp_path: Path) -> None:
    request = QueryRequest(
        [
            {"ID": "wrong", "Code": "RLSQ20260819-00010", "Name": "相似编号"},
            {"ID": "expected", "Code": "RLSQ20260819-0001", "Name": "测试流程"},
        ]
    )
    client = ErpApplicationClient(
        _erp_settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.query"),
    )

    result = client.find_by_code("RLSQ20260819-0001")

    assert result.id == "expected"
    assert result.name == "测试流程"
    assert request.form is not None
    assert request.form["swhere"] == (
        "encoded: 1=1   and Code like '%RLSQ20260819-0001%'"
    )
    assert request.form["sort"] == "Code Desc"


def test_application_query_rejects_condition_injection(tmp_path: Path) -> None:
    request = QueryRequest([])
    client = ErpApplicationClient(
        _erp_settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.query"),
    )

    with pytest.raises(ErpQueryFailedError):
        client.find_by_code("RLSQ%' or 1=1 --")

    assert request.form is None


class UploadRequest:
    def __init__(self, application_id: str) -> None:
        self.application_id = application_id
        self.uploads: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        multipart = kwargs["multipart"]
        self.uploads.append(multipart)
        extension = Path(multipart["_filename"]).suffix
        table = {
            "Id": multipart["_fileid"],
            "FolderId": self.application_id,
            "Name": Path(multipart["_filename"]).stem,
            "FileExt": extension,
            "FileSize": int(multipart["_total"]),
            "FilesHash": multipart["_FilesHash"],
            "ServerUrl": f"/test/file{extension}",
        }
        return FakeResponse({"success": True, "data": {"table": table}})


def test_attachment_upload_uses_two_megabyte_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = ErpApplicationRecord(
        id="record-id",
        code="RLSQ20260819-0001",
        name="测试流程",
    )
    pdf = tmp_path / "权益单.pdf"
    pdf.write_bytes(b"%PDF-" + b"x" * (2 * 1024 * 1024 + 10) + b"%%EOF")
    request = UploadRequest(application.id)
    client = ErpAttachmentClient(
        _erp_settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.upload"),
    )
    verified = ErpAttachmentRecord(
        id="attachment-id",
        folder_id=application.id,
        name=pdf.stem,
        extension=".pdf",
        size=pdf.stat().st_size,
        md5="verified",
        server_url="/test/file.pdf",
    )
    monkeypatch.setattr(client, "_ensure_not_duplicate", lambda *args: None)
    monkeypatch.setattr(client, "_storage_type", lambda **kwargs: "ftp")
    monkeypatch.setattr(
        client,
        "_find_uploaded_attachment",
        lambda *args: verified,
    )

    attachment, chunks = client.upload(application, pdf)

    assert attachment == verified
    assert chunks == 2
    assert [item["_chunk"] for item in request.uploads] == ["1", "2"]
    assert [item["_start"] for item in request.uploads] == ["0", "2097152"]
    assert [item["_end"] for item in request.uploads] == ["2097152", "4194304"]
    assert len(request.uploads[0]["FileData"]["buffer"]) == 2 * 1024 * 1024
    assert request.uploads[0]["FileData"]["mimeType"] == "application/pdf"


@pytest.mark.parametrize(
    ("suffix", "content_prefix", "expected_mime"),
    [
        (
            ".docx",
            "word",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            ".xlsx",
            "xl",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_attachment_upload_uses_office_mime_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    content_prefix: str,
    expected_mime: str,
) -> None:
    application = ErpApplicationRecord(
        id="record-id",
        code="RLSQ20260819-0001",
        name="测试流程",
    )
    path = tmp_path / f"附件{suffix}"
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(f"{content_prefix}/content.xml", "<content />")
    request = UploadRequest(application.id)
    client = ErpAttachmentClient(
        _erp_settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.upload.office"),
    )
    verified = ErpAttachmentRecord(
        id="attachment-id",
        folder_id=application.id,
        name=path.stem,
        extension=suffix,
        size=path.stat().st_size,
        md5="verified",
        server_url=f"/test/file{suffix}",
    )
    monkeypatch.setattr(client, "_ensure_not_duplicate", lambda *args: None)
    monkeypatch.setattr(client, "_storage_type", lambda **kwargs: "ftp")
    monkeypatch.setattr(client, "_find_uploaded_attachment", lambda *args: verified)

    attachment, chunks = client.upload(application, path)

    assert attachment == verified
    assert chunks == 1
    assert request.uploads[0]["FileData"]["mimeType"] == expected_mime


def test_attachment_rejects_damaged_pdf(tmp_path: Path) -> None:
    path = tmp_path / "damaged.pdf"
    path.write_bytes(b"not a pdf")

    with pytest.raises(FileValidationError):
        ErpUploadFileValidator().validate(path)


def test_empty_attachment_value_is_an_empty_list() -> None:
    records = ErpAttachmentClient._records(
        {"data": {"value": ""}},
        operation="验证附件列表",
    )

    assert records == []


class DeleteRequest:
    def __init__(self, attachments: list[ErpAttachmentRecord]) -> None:
        self.attachments = attachments
        self.params: dict | None = None

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.params = kwargs["params"]
        self.attachments.clear()
        return FakeResponse({"success": True, "message": "删除成功", "data": {}})


def test_delete_resolves_exact_filename_and_verifies_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = ErpApplicationRecord(
        id="record-id",
        code="RLSQ20260819-0001",
        name="测试流程",
    )
    target = ErpAttachmentRecord(
        id="attachment-id",
        folder_id=application.id,
        name="单位权益单",
        extension=".pdf",
        size=159410,
        md5="hash",
        server_url="/test/file.pdf",
    )
    request = DeleteRequest([target])
    client = ErpAttachmentClient(
        _erp_settings(tmp_path),
        FakePage(),
        request,
        logging.getLogger("test.erp.delete"),
    )
    monkeypatch.setattr(client, "_storage_type", lambda **kwargs: "ftp")
    monkeypatch.setattr(
        client,
        "_list_attachments",
        lambda *args, **kwargs: list(request.attachments),
    )

    matched = client.find_by_filename(application, "单位权益单.pdf")
    deleted = client.delete(application, matched)

    assert deleted == target
    assert request.params == {
        "_type": "ftp",
        "action": "delete",
        "_fileid": "attachment-id",
    }
