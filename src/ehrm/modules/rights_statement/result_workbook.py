from __future__ import annotations

from copy import copy
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, PatternFill
from openpyxl.utils import get_column_letter, range_boundaries

from ehrm.core.error_catalog import display_message
from ehrm.modules.rights_statement.excel_models import ItemResult


_FAILURE_HEADER = "失败原因"
_FAILURE_FILL = PatternFill(fill_type="solid", fgColor="FDE9E7")


class ResultWorkbookWriter:
    """Copies the source workbook and appends row-level execution failures."""

    def write(
        self,
        source: Path,
        output_dir: Path,
        items: list[ItemResult],
    ) -> Path:
        keep_vba = source.suffix.lower() == ".xlsm"
        workbook = load_workbook(source, keep_vba=keep_vba)
        try:
            sheet = workbook.active
            old_max_column = sheet.max_column
            failure_column = self._failure_column(sheet)
            self._style_header(sheet, failure_column, old_max_column)

            results = {item.row_number: item for item in items}
            for row_number in range(2, sheet.max_row + 1):
                cell = sheet.cell(row=row_number, column=failure_column)
                self._copy_neighbor_style(
                    sheet,
                    row_number,
                    failure_column,
                    old_max_column,
                )
                item = results.get(row_number)
                if item is None or item.success:
                    cell.value = ""
                    continue
                cell.value = display_message(item.code, item.message)
                cell.fill = copy(_FAILURE_FILL)
                cell.alignment = Alignment(
                    horizontal="left",
                    vertical="center",
                    wrap_text=True,
                )

            sheet.column_dimensions[get_column_letter(failure_column)].width = 42
            self._extend_filters_and_tables(
                sheet,
                old_max_column,
                failure_column,
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            destination = self._destination(source, output_dir)
            workbook.save(destination)
            return destination
        finally:
            workbook.close()

    @staticmethod
    def _failure_column(sheet) -> int:
        for column in range(1, sheet.max_column + 1):
            value = sheet.cell(row=1, column=column).value
            if str(value).strip() == _FAILURE_HEADER:
                return column
        return sheet.max_column + 1

    @staticmethod
    def _style_header(sheet, failure_column: int, old_max_column: int) -> None:
        cell = sheet.cell(row=1, column=failure_column)
        if old_max_column > 0 and failure_column > old_max_column:
            source = sheet.cell(row=1, column=old_max_column)
            cell._style = copy(source._style)
            cell.font = copy(source.font)
            cell.fill = copy(source.fill)
            cell.border = copy(source.border)
            cell.alignment = copy(source.alignment)
            cell.protection = copy(source.protection)
        cell.value = _FAILURE_HEADER

    @staticmethod
    def _copy_neighbor_style(
        sheet,
        row_number: int,
        failure_column: int,
        old_max_column: int,
    ) -> None:
        if failure_column <= old_max_column or old_max_column < 1:
            return
        source = sheet.cell(row=row_number, column=old_max_column)
        target = sheet.cell(row=row_number, column=failure_column)
        target._style = copy(source._style)
        target.number_format = "@"

    @staticmethod
    def _extend_filters_and_tables(
        sheet,
        old_max_column: int,
        failure_column: int,
    ) -> None:
        new_letter = get_column_letter(failure_column)
        if sheet.auto_filter.ref:
            min_col, min_row, max_col, max_row = range_boundaries(
                sheet.auto_filter.ref
            )
            if max_col == old_max_column:
                sheet.auto_filter.ref = (
                    f"{get_column_letter(min_col)}{min_row}:{new_letter}{max_row}"
                )
        for table in sheet.tables.values():
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            if max_col == old_max_column:
                table.ref = (
                    f"{get_column_letter(min_col)}{min_row}:{new_letter}{max_row}"
                )

    @staticmethod
    def _destination(source: Path, output_dir: Path) -> Path:
        suffix = source.suffix.lower()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = output_dir / f"{source.stem}_执行结果_{stamp}{suffix}"
        if not candidate.exists():
            return candidate
        return output_dir / (
            f"{source.stem}_执行结果_{datetime.now():%Y%m%d_%H%M%S_%f}{suffix}"
        )
