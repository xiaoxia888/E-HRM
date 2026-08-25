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
    task_number: str
    print_group_id: str = ""
    print_group_sequence: int = 0
    source_print_mode: str = ""
    resolved_print_mode: str = ""

    @property
    def group_key(self) -> tuple[str, ...]:
        if self.print_group_id:
            return (
                self.task_number,
                self.print_group_id,
                self.insurance_type,
                self.start_month,
                self.end_month,
            )
        return self.task_number, self.insurance_type, self.start_month, self.end_month


@dataclass(frozen=True, slots=True)
class WorkGroup:
    sequence: int
    records: tuple[EmployeeRecord, ...]
    mode: ExportMode | None = None

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
    erp_success: bool | None = None
    erp_code: str | None = None
    erp_message: str | None = None
    erp_attachment_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExcelRunResult:
    mode: ExportMode
    total: int
    succeeded: int
    failed: int
    manifest_path: Path
    result_workbook_path: Path | None
    items: tuple[ItemResult, ...]
    erp_uploaded: int = 0
    erp_failed: int = 0


@dataclass(frozen=True, slots=True)
class ExcelTaskRequest:
    groups: tuple[WorkGroup, ...]
    mode: ExportMode
    output_dir: Path
    source_excel: Path
    upload_to_erp: bool = False
