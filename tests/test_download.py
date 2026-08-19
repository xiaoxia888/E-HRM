from pathlib import Path

import pytest

from ehrm.browser.download import DownloadManager
from ehrm.core.exceptions import FileValidationError


def test_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.touch()
    with pytest.raises(FileValidationError):
        DownloadManager.validate(path)


def test_accepts_pdf_signature(tmp_path: Path) -> None:
    path = tmp_path / "statement.pdf"
    path.write_bytes(b"%PDF-1.7\nmock\n%%EOF\n")
    DownloadManager.validate(path)


def test_rejects_truncated_pdf(tmp_path: Path) -> None:
    path = tmp_path / "truncated.pdf"
    path.write_bytes(b"%PDF-1.7\nmock without an eof marker")
    with pytest.raises(FileValidationError, match="下载不完整"):
        DownloadManager.validate(path)
