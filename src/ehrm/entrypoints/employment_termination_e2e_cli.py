from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import application_runtime_root, resolve_runtime_path
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.employment_termination.excel_loader import (
    EmploymentTerminationExcelLoader,
)
from ehrm.modules.employment_termination.service import (
    EmploymentTerminationService,
)
from ehrm.modules.employment_termination.result_workbook import (
    EmploymentTerminationResultWorkbookWriter,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ehrm-employment-termination-e2e",
        description=(
            "从 Excel 读取退保测试数据，复用 SQLite 智慧人社账号完成登录并"
            "录入表单；不会点击“确定提交”。"
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_SETTINGS_PATH)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="包含“身份证号、退工原因”两列的 .xlsx/.xlsm 文件",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/employment-termination-e2e"),
        help="逐行处理结果 Excel 的输出目录",
    )
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="仅用于自签名证书测试环境",
    )
    parser.add_argument(
        "--pause-after-fill",
        action="store_true",
        help="录入完成后等待按回车，便于人工检查页面；仍不会提交",
    )
    parser.add_argument(
        "--diagnostic",
        type=Path,
        default=Path("output/employment-termination-e2e.png"),
        help="成功或失败时保存的页面截图",
    )
    parser.add_argument(
        "--check-input",
        action="store_true",
        help="只检查配置、SQLite 默认账号和 Excel，不启动浏览器",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runtime_root = application_runtime_root(args.config)
        settings = load_settings(args.config, data_root=runtime_root)
        input_path = args.input.expanduser().resolve()
        output_dir = resolve_runtime_path(args.output, runtime_root)
        diagnostic = resolve_runtime_path(args.diagnostic, runtime_root)
        items = EmploymentTerminationExcelLoader().load(input_path)
        account = AuthenticationRepository(
            settings.auth_database_path
        ).get_default_account(SystemType.JSHRSS)
        if account is None:
            raise ValueError(
                "SQLite 中没有默认的江苏智慧人社账号，请先在系统设置中保存账号"
            )
        if not account.secondary_account or not account.password:
            raise ValueError(
                "SQLite 中的智慧人社登录信息不完整，请先保存单位编号、手机号和密码"
            )
    except (EhrmError, OSError, ValueError) as exc:
        _print_failure("退保 E2E 准备失败", exc)
        return 2

    contract = settings.employment_termination
    print(
        f"执行地区：{contract.city_name}（areaCode={contract.city_code}，运行时强校验）"
    )
    print(f"测试数据：{input_path}，共 {len(items)} 条")
    print("登录凭据：读取应用 SQLite 中的默认智慧人社账号")
    print("安全边界：只录入数据，不点击“确定提交”")
    if args.check_input:
        print("退保 E2E 配置、账号和 Excel 检查通过")
        return 0

    logger = configure_logging(runtime_root / "logs")
    try:
        with BrowserManager(
            settings.browser,
            ignore_https_errors=args.ignore_https_errors,
            stealth_enabled=(
                settings.captcha.stealth_enabled
                and is_allowed_host_url(
                    settings.site.login_url,
                    settings.captcha.allowed_hosts,
                )
            ),
        ) as browser:
            page = browser.page
            try:
                login = LoginService(page, settings, progress_callback=print)
                print("阶段 1/2：正在复用现有智慧人社自动化登录……")
                login.ensure_authenticated()
                page = login.page

                print("阶段 2/2：正在确保南京地区并录入退保数据……")
                result = EmploymentTerminationService(
                    settings,
                    logger,
                    progress_callback=print,
                ).prepare_with_page(page, items)
                result_workbook = EmploymentTerminationResultWorkbookWriter().write(
                    input_path,
                    output_dir,
                    result.results,
                )
                _save_screenshot(page, diagnostic)
                print(
                    "退保数据录入测试完成："
                    f"总计 {result.total_count} 条，"
                    f"录入成功 {result.prepared_count} 条，"
                    f"未查询到 {result.failed_count} 条，"
                    f"地区={result.city_name}，submitted={str(result.submitted).lower()}"
                )
                print(f"结果 Excel：{result_workbook.resolve()}")
                if args.pause_after_fill:
                    input("页面已停在提交前，检查完毕后按回车关闭浏览器：")
                return 0
            except (EhrmError, OSError, PlaywrightError, ValueError):
                # The screenshot must be taken before BrowserManager.__exit__ closes
                # Playwright and its event loop.
                _save_screenshot(page, diagnostic)
                raise
    except (EhrmError, OSError, PlaywrightError, ValueError) as exc:
        _print_failure("完整退保数据录入 E2E 失败", exc)
        return 1


def _save_screenshot(page: object, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True)
        print(f"页面截图：{path.resolve()}")
    except (AttributeError, OSError, PlaywrightError) as exc:
        print(f"页面截图保存失败：{exc}")


def _print_failure(label: str, exc: Exception) -> None:
    message = str(exc)
    details = getattr(exc, "details", None)
    if details and details != message:
        message += f"；{details}"
    print(f"{label}：{message}")


if __name__ == "__main__":
    raise SystemExit(main())
