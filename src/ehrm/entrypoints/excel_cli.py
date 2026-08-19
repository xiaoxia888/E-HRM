from __future__ import annotations

import argparse
from pathlib import Path

from ehrm.application import EhrmApplication, RIGHTS_STATEMENT_EXCEL_EXPORT
from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.settings import load_settings
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.rights_statement.excel_models import (
    ExcelRunResult,
    ExcelTaskRequest,
    ExportMode,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Excel 权益单测试前端")
    parser.add_argument("--input", type=Path, required=True, help="人员 Excel")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ExportMode],
        required=True,
        help="individual=每人一份，batch=多人合并",
    )
    parser.add_argument("--output", type=Path, default=Path("downloads"))
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--config", type=Path, default=Path("config/settings.toml"))
    parser.add_argument("--dry-run", action="store_true", help="只校验并显示计划")
    parser.add_argument("--yes", action="store_true", help="跳过执行前确认")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    mode = ExportMode(args.mode)
    loader = RightsStatementExcelLoader()
    try:
        records = loader.load(args.input.expanduser().resolve())
        groups = loader.plan(records, mode, args.batch_size)
    except EhrmError as exc:
        message = display_message(exc.code, exc.message)
        print(message)
        if exc.message != message:
            print(exc.message)
        if exc.details:
            print(exc.details)
        return 2

    units = sorted({record.unit for record in records})
    print(f"校验通过：{len(records)} 人")
    print(f"执行模式：{mode.value}")
    print(f"涉及单位：{len(units)} 个")
    print(f"预计生成：{len(groups)} 个 PDF")
    if len(units) > 1:
        print("注意：包含多个单位，请确保当前账号具备这些单位的查询权限。")
    if args.dry_run:
        return 0
    if not args.yes and input("确认开始执行？[y/N] ").strip().lower() != "y":
        print("已取消")
        return 0

    try:
        settings = load_settings(args.config)
        result = EhrmApplication(settings, configure_logging()).run(
            RIGHTS_STATEMENT_EXCEL_EXPORT,
            ExcelTaskRequest(
                groups=tuple(groups),
                mode=mode,
                output_dir=args.output.expanduser().resolve(),
                source_excel=args.input.expanduser().resolve(),
            ),
        )
        if not isinstance(result, ExcelRunResult):
            raise RuntimeError("Excel 任务返回了错误的结果类型")
    except EhrmError as exc:
        message = display_message(exc.code, exc.message)
        print(message)
        if exc.message != message:
            print(exc.message)
        if exc.details:
            print(exc.details)
        return 2

    print(f"执行完成：成功 {result.succeeded}，失败 {result.failed}")
    records_by_row = {record.row_number: record for record in records}
    for item in result.items:
        if item.success:
            continue
        record = records_by_row.get(item.row_number)
        person = record.name if record else "未知人员"
        print(
            f"失败：Excel 第 {item.row_number} 行 {person} - "
            f"{display_message(item.code, item.message)}"
        )
    print(f"结果清单：{result.manifest_path}")
    print(f"结果 Excel：{result.result_workbook_path or '生成失败，请查看日志'}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
