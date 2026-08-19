from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    success: bool
    code: str
    message: str
    file_path: Path | None = None
    diagnostic_path: Path | None = None

