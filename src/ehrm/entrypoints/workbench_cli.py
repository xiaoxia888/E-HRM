from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.settings import load_settings
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.rights_statement.excel_models import ExcelTaskRequest, ExportMode
from ehrm.workbench import DesktopWorkbench


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="E-HRM 常驻桌面工作台测试入口")
    parser.add_argument("--config", type=Path, default=Path("config/settings.toml"))
    parser.add_argument("--output", type=Path, default=Path("downloads"))
    parser.add_argument("--batch-size", type=int, default=50)
    return parser


def _clean_path(value: str) -> Path:
    return Path(value.strip().strip('"').strip("'")).expanduser().resolve()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        logger = configure_logging()
        loader = RightsStatementExcelLoader()
        with DesktopWorkbench(settings, logger) as workbench:
            print("输入 Excel 路径开始任务；输入 q 彻底退出工作台。")
            while True:
                raw_path = input("\nExcel 路径[q退出]：").strip()
                if raw_path.lower() in {"q", "quit", "exit"}:
                    break
                if not raw_path:
                    continue

                raw_mode = input(
                    "模式[individual每人一份/batch多人合并，默认individual]："
                ).strip().lower()
                mode = ExportMode.BATCH if raw_mode == "batch" else ExportMode.INDIVIDUAL
                try:
                    source_excel = _clean_path(raw_path)
                    records = loader.load(source_excel)
                    groups = loader.plan(records, mode, args.batch_size)
                except EhrmError as exc:
                    message = display_message(exc.code, exc.message)
                    print(message)
                    if exc.message != message:
                        print(exc.message)
                    if exc.details:
                        print(exc.details)
                    continue

                condition_counts = Counter(
                    (
                        record.unit,
                        record.insurance_type,
                        record.start_month,
                        record.end_month,
                    )
                    for record in records
                )
                print("程序从 Excel 读取到的查询条件：")
                for (
                    unit,
                    insurance,
                    start_month,
                    end_month,
                ), count in condition_counts.items():
                    print(
                        f"- {unit}｜{insurance}｜{start_month} 至 {end_month}｜{count} 人"
                    )
                print(f"校验通过：{len(records)} 人，预计生成 {len(groups)} 个 PDF")
                if input("确认执行？[y/N]：").strip().lower() != "y":
                    continue
                result = workbench.run(
                    ExcelTaskRequest(
                        groups=tuple(groups),
                        mode=mode,
                        output_dir=args.output.expanduser().resolve(),
                        source_excel=source_excel,
                    )
                )
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
                print(
                    f"执行完成：成功 {result.succeeded}，失败 {result.failed}\n"
                    f"结果清单：{result.manifest_path}\n"
                    f"结果 Excel：{result.result_workbook_path or '生成失败，请查看日志'}"
                )
    except KeyboardInterrupt:
        print("\n工作台已退出")
        return 130
    except EhrmError as exc:
        message = display_message(exc.code, exc.message)
        print(message)
        if exc.message != message:
            print(exc.message)
        if exc.details:
            print(exc.details)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
