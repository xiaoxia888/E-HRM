from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from ehrm.core.exceptions import FileValidationError


_OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
}
_TYPE_LABELS = {
    ".pdf": "PDF",
    ".doc": "Word",
    ".docx": "Word",
    ".xls": "Excel",
    ".xlsx": "Excel",
    ".xlsm": "Excel",
}


@dataclass(frozen=True, slots=True)
class ValidatedUploadFile:
    path: Path
    extension: str
    mime_type: str
    type_label: str
    size: int


class ErpUploadFileValidator:
    """Validates the supported ERP attachment formats before browser work."""

    SUPPORTED_EXTENSIONS = tuple(_MIME_TYPES)

    def validate(self, file_path: Path) -> ValidatedUploadFile:
        path = file_path.expanduser().resolve()
        if not path.is_file():
            raise FileValidationError(f"待上传文件不存在：{path}")
        extension = path.suffix.lower()
        if extension not in _MIME_TYPES:
            raise FileValidationError(
                "仅支持 PDF、Word（doc/docx）和 Excel（xls/xlsx/xlsm）文件"
            )
        size = path.stat().st_size
        if size <= 0:
            raise FileValidationError(f"待上传文件是空文件：{path.name}")

        if extension == ".pdf":
            self._validate_pdf(path)
        elif extension in {".docx", ".xlsx", ".xlsm"}:
            self._validate_open_xml(path, extension)
        else:
            self._validate_legacy_office(path)

        return ValidatedUploadFile(
            path=path,
            extension=extension,
            mime_type=_MIME_TYPES[extension],
            type_label=_TYPE_LABELS[extension],
            size=size,
        )

    @staticmethod
    def _validate_pdf(path: Path) -> None:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise FileValidationError(f"文件不是有效 PDF：{path.name}")
            stream.seek(max(0, path.stat().st_size - 4096))
            if b"%%EOF" not in stream.read():
                raise FileValidationError(f"PDF 文件不完整：{path.name}")

    @staticmethod
    def _validate_open_xml(path: Path, extension: str) -> None:
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
        except (BadZipFile, OSError) as exc:
            raise FileValidationError(
                f"Office 文件结构无效：{path.name}"
            ) from exc
        required_prefix = "word/" if extension == ".docx" else "xl/"
        if "[Content_Types].xml" not in names or not any(
            name.startswith(required_prefix) for name in names
        ):
            expected = "Word" if extension == ".docx" else "Excel"
            raise FileValidationError(
                f"文件内容与 {expected} 扩展名不匹配：{path.name}"
            )

    @staticmethod
    def _validate_legacy_office(path: Path) -> None:
        with path.open("rb") as stream:
            if stream.read(8) != _OLE_SIGNATURE:
                raise FileValidationError(
                    f"旧版 Office 文件签名无效：{path.name}"
                )
