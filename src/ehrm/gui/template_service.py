from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation


class RightsStatementTemplateService:
    HEADERS = ("单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间")
    INSURANCE_OPTIONS = ("养老", "工伤", "失业")

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
        sheet.auto_filter.ref = "A1:G1"
        sheet.row_dimensions[1].height = 26
        widths = {"A": 24, "B": 18, "C": 14, "D": 24, "E": 13, "F": 16, "G": 16}
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width

        for row in range(2, 1002):
            sheet.cell(row=row, column=4).number_format = "@"
            sheet.cell(row=row, column=6).number_format = "yyyy-mm"
            sheet.cell(row=row, column=7).number_format = "yyyy-mm"

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
        insurance_validation.add("E2:E1001")

        invalid_period_fill = PatternFill("solid", fgColor="FDE9E7")
        sheet.conditional_formatting.add(
            "G2:G1001",
            FormulaRule(formula=["AND(F2<>\"\",G2<>\"\",F2>G2)"], fill=invalid_period_fill),
        )

        guide = workbook.create_sheet("填写说明")
        guide_rows = (
            ("字段", "填写要求"),
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

