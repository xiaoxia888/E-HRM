from pathlib import Path
from zipfile import ZipFile

import pytest

from ehrm.core.exceptions import FileValidationError
from ehrm.modules.erp.file_validation import ErpUploadFileValidator


def _write_open_xml(path: Path, content_prefix: str) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(f"{content_prefix}/content.xml", "<content />")


@pytest.mark.parametrize(
    ("suffix", "prefix", "type_label"),
    [
        (".docx", "word", "Word"),
        (".xlsx", "xl", "Excel"),
        (".xlsm", "xl", "Excel"),
    ],
)
def test_validates_open_xml_office_files(
    tmp_path: Path,
    suffix: str,
    prefix: str,
    type_label: str,
) -> None:
    path = tmp_path / f"附件{suffix}"
    _write_open_xml(path, prefix)

    result = ErpUploadFileValidator().validate(path)

    assert result.type_label == type_label
    assert result.size == path.stat().st_size


@pytest.mark.parametrize("suffix", [".doc", ".xls"])
def test_validates_legacy_office_signature(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"附件{suffix}"
    path.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy-office")

    result = ErpUploadFileValidator().validate(path)

    assert result.extension == suffix


def test_rejects_extension_content_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "伪造Word.docx"
    _write_open_xml(path, "xl")

    with pytest.raises(FileValidationError, match="扩展名不匹配"):
        ErpUploadFileValidator().validate(path)


def test_rejects_unsupported_file_type(tmp_path: Path) -> None:
    path = tmp_path / "图片.png"
    path.write_bytes(b"png")

    with pytest.raises(FileValidationError, match="仅支持 PDF、Word"):
        ErpUploadFileValidator().validate(path)
