from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Download

from ehrm.core.exceptions import FileValidationError


_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class DownloadManager:
    def save(self, download: Download, output_dir: Path, fallback_name: str) -> Path:
        failure = download.failure()
        if failure:
            raise FileValidationError(f"浏览器下载失败：{failure}")
        destination = self.destination(output_dir, fallback_name)
        try:
            download.save_as(destination)
            self.validate(destination)
        except Exception:
            # The destination is always newly reserved by this run, so a failed
            # validation can be removed without touching a pre-existing file.
            destination.unlink(missing_ok=True)
            raise
        return destination

    def save_bytes(
        self,
        content: bytes,
        output_dir: Path,
        fallback_name: str,
    ) -> Path:
        destination = self.destination(output_dir, fallback_name)
        try:
            destination.write_bytes(content)
            self.validate(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination

    def destination(self, output_dir: Path, fallback_name: str) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Business filenames are deterministic; the site's generic suggested name is ignored.
        safe_name = _UNSAFE_FILENAME.sub("_", fallback_name).strip(". ")
        return self._available_path(output_dir / safe_name)

    @staticmethod
    def validate(path: Path) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise FileValidationError(f"下载文件为空或不存在：{path}")
        if path.suffix.lower() == ".pdf":
            with path.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise FileValidationError(f"文件扩展名为 PDF，但内容不是 PDF：{path}")
                stream.seek(max(0, path.stat().st_size - 4_096))
                if b"%%EOF" not in stream.read():
                    raise FileValidationError(f"PDF 下载不完整，缺少结束标志：{path}")

    @staticmethod
    def _available_path(path: Path) -> Path:
        if not path.exists():
            return path
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return path.with_name(f"{path.stem}_{stamp}{path.suffix}")
