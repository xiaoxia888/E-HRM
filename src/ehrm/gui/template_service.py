from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from ehrm.modules.rights_statement.excel_models import EmployeeRecord


class RightsStatementTemplateService:
    HEADERS = (
        "ERP申请编号",
        "打印组",
        "单位",
        "部门",
        "姓名",
        "身份证",
        "险种",
        "开始时间",
        "结束时间",
    )
    INSURANCE_OPTIONS = ("养老", "工伤", "失业")
    ERP_HEADERS = HEADERS

    def write(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "人员导入"

        header_fill = PatternFill("solid", fgColor="1677FF")
        for column, header in enumerate(self.HEADERS, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = "A1:I1"
        sheet.row_dimensions[1].height = 26
        widths = {
            "A": 24,
            "B": 18,
            "C": 24,
            "D": 18,
            "E": 14,
            "F": 24,
            "G": 13,
            "H": 16,
            "I": 16,
        }
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width

        for row in range(2, 1002):
            sheet.cell(row=row, column=1).number_format = "@"
            sheet.cell(row=row, column=2).number_format = "@"
            sheet.cell(row=row, column=6).number_format = "@"
            sheet.cell(row=row, column=8).number_format = "yyyy-mm"
            sheet.cell(row=row, column=9).number_format = "yyyy-mm"

        insurance_validation = DataValidation(
            type="list",
            formula1='"养老,工伤,失业"',
            allow_blank=False,
            error="险种只能选择养老、工伤或失业",
            errorTitle="险种填写错误",
        )
        insurance_validation.promptTitle = "请选择险种"
        insurance_validation.prompt = "养老、工伤、失业"
        insurance_validation.showInputMessage = True
        insurance_validation.showErrorMessage = True
        sheet.add_data_validation(insurance_validation)
        insurance_validation.add("G2:G1001")

        invalid_period_fill = PatternFill("solid", fgColor="FDE9E7")
        sheet.conditional_formatting.add(
            "I2:I1001",
            FormulaRule(formula=["AND(H2<>\"\",I2<>\"\",H2>I2)"], fill=invalid_period_fill),
        )

        guide = workbook.create_sheet("填写说明")
        guide_rows = (
            ("字段", "填写要求"),
            (
                "ERP申请编号",
                "可留空；填写后可将生成的权益单上传到对应 ERP 申请",
            ),
            (
                "打印组",
                "可留空；相同内容打印到同一组，不同内容分开打印。所有空白人员打印到同一组",
            ),
            ("单位", "必填，填写参保单位名称"),
            ("部门", "必填，用于结果文件归类"),
            ("姓名", "必填"),
            ("身份证", "必填，15位或18位；本列已设置为文本格式"),
            ("险种", "必填，只能从养老、工伤、失业中选择"),
            ("开始时间", "必填，建议格式 YYYY-MM，例如 2025-05"),
            ("结束时间", "必填，不能早于开始时间"),
        )
        for row in guide_rows:
            guide.append(row)
        for cell in guide[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
        guide.column_dimensions["A"].width = 18
        guide.column_dimensions["B"].width = 58
        guide.freeze_panes = "A2"

        workbook.save(destination)
        workbook.close()
        return destination

    def write_records(
        self,
        destination: Path,
        records: list[EmployeeRecord],
        *,
        include_print_groups: bool = True,
    ) -> Path:
        """Writes current preview records as a compact execution source workbook."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "ERP申请解析数据" if include_print_groups else "人员执行数据"
        header_fill = PatternFill("solid", fgColor="1677FF")
        headers = self.ERP_HEADERS if include_print_groups else self.HEADERS
        for column, header in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for record in records:
            values = [
                record.task_number,
                record.print_group_label,
                record.unit,
                record.department,
                record.name,
                record.identity_number,
                record.insurance_type,
                record.start_month,
                record.end_month,
            ]
            if include_print_groups:
                values[1] = (
                    record.print_group_label
                    or (
                        f"组{record.print_group_sequence}"
                        if record.print_group_sequence
                        else ""
                    )
                )
            sheet.append(values)
            row = sheet.max_row
            sheet.cell(row=row, column=1).number_format = "@"
            identity_column = 6
            start_column = 8
            end_column = 9
            sheet.cell(row=row, column=identity_column).number_format = "@"
            sheet.cell(row=row, column=start_column).number_format = "@"
            sheet.cell(row=row, column=end_column).number_format = "@"
        sheet.freeze_panes = "A2"
        last_column = "I"
        sheet.auto_filter.ref = f"A1:{last_column}{max(1, sheet.max_row)}"
        sheet.row_dimensions[1].height = 26
        widths = {
            "A": 24,
            "B": 18,
            "C": 24,
            "D": 18,
            "E": 14,
            "F": 24,
            "G": 13,
            "H": 16,
            "I": 16,
        }
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width
        workbook.save(destination)
        workbook.close()
        return destination
