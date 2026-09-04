from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.access_token import (
    create_rights_access_token_manager,
)
from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import application_runtime_root, resolve_runtime_path
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.entrypoints.login_e2e_cli import (
    _credential,
    _isolated_settings,
    _print_targets,
    _save_diagnostic,
)
from ehrm.modules.rights_statement.api_client import RightsStatementApiClient
from ehrm.modules.rights_statement.api_contract import RightsApiContract
from ehrm.modules.rights_statement.api_session import RightsStatementApiSession
from ehrm.modules.rights_statement.api_models import (
    InsuranceCode,
    PersonQueryRequest,
    RightsBillPrintRequest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ehrm-rights-api-e2e",
        description=(
            "完整验证登录、Access-Token、人员查询、权益单打印和 PDF 保存流程。"
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_SETTINGS_PATH)
    parser.add_argument("--identity-number", required=True, help="身份证号码")
    parser.add_argument("--name", default="", help="姓名，可不填写")
    parser.add_argument("--start-month", required=True, help="格式 YYYYMM")
    parser.add_argument("--end-month", required=True, help="格式 YYYYMM")
    parser.add_argument(
        "--insurance",
        required=True,
        choices=("养老", "工伤", "失业"),
        help="打印险种",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/rights-api-e2e"),
        help="PDF 保存目录",
    )
    parser.add_argument(
        "--filename",
        default="",
        help="PDF 文件名；不填写时自动生成",
    )
    parser.add_argument(
        "--reuse-profile",
        action="store_true",
        help="复用配置中的浏览器资料；默认使用全新临时资料",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="凭据缺失时直接失败，适用于 CI",
    )
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="仅用于自签名证书的测试环境",
    )
    parser.add_argument(
        "--diagnostic",
        type=Path,
        default=Path("output/rights-api-e2e-failure.png"),
        help="失败时保存页面截图的位置",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="只检查配置和参数，不启动浏览器",
    )
    return parser


def _default_filename(
    insurance: InsuranceCode,
    start_month: str,
    end_month: str,
    person_count: int,
) -> str:
    return (
        f"{insurance.display_name}_{start_month}-{end_month}_"
        f"{person_count}人_权益单.pdf"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runtime_root = application_runtime_root(args.config)
        settings = load_settings(args.config, data_root=runtime_root)
        diagnostic_path = resolve_runtime_path(args.diagnostic, runtime_root)
        output_dir = resolve_runtime_path(args.output_dir, runtime_root)
        insurance = InsuranceCode.from_display_name(args.insurance)
        query = PersonQueryRequest(
            identity_number=args.identity_number,
            name=args.name,
            start_month=args.start_month,
            end_month=args.end_month,
        )
        # Validate query parameters before opening the browser.
        query.to_payload(
            api_code=RightsApiContract.QUERY_COMMON_API_CODE,
            default_page_size=settings.rights_api.page_size,
        )
    except (EhrmError, ValueError) as exc:
        _print_failure("参数或配置检查失败", exc)
        return 2

    _print_targets(settings)
    print(f"人员查询接口：{settings.rights_api.query_common_path}")
    print(f"流水号接口：{settings.rights_api.acquire_business_no_path}")
    print(f"权益单打印接口：{settings.rights_api.load_unit_rights_bill_path}")
    print(
        "测试条件："
        f"险种={insurance.display_name}({insurance.value})，"
        f"期间={args.start_month}-{args.end_month}"
    )
    if args.check_config:
        print("权益单 API E2E 配置和参数检查通过")
        return 0

    credentials = settings.rights_credentials
    try:
        credit_code = _credential(
            configured=credentials.credit_code,
            environment_name=credentials.credit_code_env,
            prompt="统一信用代码：",
            secret=False,
            no_prompt=args.no_prompt,
        )
        mobile = _credential(
            configured=credentials.mobile,
            environment_name=credentials.mobile_env,
            prompt="证件号码/移动电话：",
            secret=False,
            no_prompt=args.no_prompt,
        )
        password = _credential(
            configured=credentials.password,
            environment_name=credentials.password_env,
            prompt="登录密码：",
            secret=True,
            no_prompt=args.no_prompt,
        )
    except ValueError as exc:
        _print_failure("凭据准备失败", exc)
        return 2

    settings = replace(
        settings,
        rights_credentials=replace(
            credentials,
            credit_code=credit_code,
            mobile=mobile,
            password=password,
        ),
    )
    logger = configure_logging(runtime_root / "logs")
    try:
        with _isolated_settings(
            settings,
            reuse_profile=args.reuse_profile,
        ) as runtime_settings:
            access_tokens = create_rights_access_token_manager(
                runtime_settings.auth_database_path,
                credit_code,
                mobile,
                password=password,
            )
            with BrowserManager(
                runtime_settings.browser,
                ignore_https_errors=args.ignore_https_errors,
                stealth_enabled=(
                    runtime_settings.captcha.stealth_enabled
                    and is_allowed_host_url(
                        runtime_settings.site.login_url,
                        runtime_settings.captcha.allowed_hosts,
                    )
                ),
            ) as browser:
                login = LoginService(
                    browser.page,
                    runtime_settings,
                    access_token_manager=access_tokens,
                )

                def client_factory() -> RightsStatementApiClient:
                    return RightsStatementApiClient(
                        runtime_settings,
                        login.page.request,
                        access_tokens,
                        logger,
                        diagnostic_callback=print,
                    )

                def authenticate() -> None:
                    try:
                        login.ensure_authenticated(
                            username=credit_code,
                            mobile=mobile,
                            password=password,
                        )
                    except (
                        EhrmError,
                        OSError,
                        PlaywrightError,
                        ValueError,
                    ):
                        _save_diagnostic(login.page, diagnostic_path)
                        raise

                api_session = RightsStatementApiSession(
                    client_factory,
                    authenticate,
                    logger,
                    print,
                )
                try:
                    cached_token = access_tokens.get_token()
                    print(
                        "认证状态："
                        + (
                            "已读取本地 Access-Token，优先直接调用查询接口"
                            if cached_token
                            else "本地没有 Access-Token，首次请求后将进入登录流程"
                        )
                    )
                    print("阶段 1/3：正在查询人员并校验 Token……")
                    query_result = api_session.execute(
                        lambda client: client.query_people(query),
                        operation_name="人员查询",
                    )
                    if not query_result.records:
                        reason = query_result.page.error_info or "未查询到人员"
                        raise ValueError(reason)
                    print(
                        "人员查询成功："
                        f"返回 {len(query_result.records)} 人，"
                        "已提取全部 bac001"
                    )

                    print("阶段 2/3：正在调用打印接口生成权益单……")
                    print_request = RightsBillPrintRequest(
                        start_month=args.start_month,
                        end_month=args.end_month,
                        insurance=insurance,
                        person_ids=tuple(
                            record.person_id
                            for record in query_result.records
                        ),
                    )
                    filename = args.filename.strip() or _default_filename(
                        insurance,
                        args.start_month,
                        args.end_month,
                        len(query_result.records),
                    )
                    destination = api_session.execute(
                        lambda client: client.download_rights_bill(
                            print_request,
                            output_dir,
                            filename,
                        ),
                        operation_name="权益单打印",
                    )
                    print("阶段 3/3：PDF 完整性校验和保存完成")
                except (EhrmError, OSError, PlaywrightError, ValueError):
                    raise

                print("完整权益单 API E2E 验证通过")
                print(f"PDF 文件：{destination}")
                print(f"PDF 大小：{destination.stat().st_size} 字节")
                print("日志文件：" + str(runtime_root / "logs/ehrm.log"))
                return 0
    except (EhrmError, OSError, PlaywrightError, ValueError) as exc:
        _print_failure("完整权益单 API E2E 验证失败", exc)
        return 1


def _print_failure(label: str, exc: Exception) -> None:
    failure = str(exc)
    details = getattr(exc, "details", None)
    if details and details != failure:
        failure += f"；{details}"
    print(f"{label}：{failure}")


if __name__ == "__main__":
    raise SystemExit(main())
