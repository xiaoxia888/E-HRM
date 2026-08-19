from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ExportMode(str, Enum):
    INDIVIDUAL = "individual"
    BATCH = "batch"


@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    row_number: int
    unit: str
    department: str
    name: str
    identity_number: str
    insurance_type: str
    start_month: str
    end_month: str

    @property
    def group_key(self) -> tuple[str, str, str, str]:
        return self.unit, self.insurance_type, self.start_month, self.end_month


@dataclass(frozen=True, slots=True)
class WorkGroup:
    sequence: int
    records: tuple[EmployeeRecord, ...]

    @property
    def first(self) -> EmployeeRecord:
        return self.records[0]


@dataclass(frozen=True, slots=True)
class ItemResult:
    row_number: int
    success: bool
    code: str
    message: str
    file_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ExcelRunResult:
    mode: ExportMode
    total: int
    succeeded: int
    failed: int
    manifest_path: Path
    result_workbook_path: Path | None
    items: tuple[ItemResult, ...]


@dataclass(frozen=True, slots=True)
class ExcelTaskRequest:
    groups: tuple[WorkGroup, ...]
    mode: ExportMode
    output_dir: Path
    source_excel: Path
