from pathlib import Path
from unittest.mock import Mock, patch

from openpyxl import Workbook

from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.exceptions import EmployeeNotFoundError
from ehrm.core.settings import load_settings
from ehrm.entrypoints.employment_termination_e2e_cli import main


def test_check_input_reads_saved_sqlite_account_without_prompt(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    AuthenticationRepository(settings.auth_database_path).save_account(
        SystemType.JSHRSS,
        "test-unit-code",
        "test-password",
        secondary_account="test-mobile",
    )
    workbook_path = tmp_path / "退保测试.xlsx"
    workbook = Workbook()
    workbook.active.append(["身份证号", "退工原因"])
    workbook.active.append(["320101199001011234", "6304"])
    workbook.save(workbook_path)
    workbook.close()

    with (
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.application_runtime_root",
            return_value=tmp_path,
        ),
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.load_settings",
            return_value=settings,
        ),
    ):
        status = main(["--input", str(workbook_path), "--check-input"])

    assert status == 0


def test_failure_screenshot_is_saved_before_browser_closes(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    AuthenticationRepository(settings.auth_database_path).save_account(
        SystemType.JSHRSS,
        "test-unit-code",
        "test-password",
        secondary_account="test-mobile",
    )
    workbook_path = tmp_path / "退保测试.xlsx"
    workbook = Workbook()
    workbook.active.append(["身份证号", "退工原因"])
    workbook.active.append(["320101199001011234", "6304"])
    workbook.save(workbook_path)
    workbook.close()

    class FakeBrowserManager:
        def __init__(self) -> None:
            self.page = Mock()
            self.active = False

        def __enter__(self) -> "FakeBrowserManager":
            self.active = True
            return self

        def __exit__(self, *_args: object) -> None:
            self.active = False

    browser = FakeBrowserManager()

    class FakeLoginService:
        def __init__(self, page: object, *_args: object, **_kwargs: object) -> None:
            self.page = page

        def ensure_authenticated(self) -> None:
            return None

    service = Mock()
    service.prepare_with_page.side_effect = EmployeeNotFoundError("人员不存在")

    def assert_browser_is_active(*_args: object, **_kwargs: object) -> None:
        assert browser.active is True

    with (
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.application_runtime_root",
            return_value=tmp_path,
        ),
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.load_settings",
            return_value=settings,
        ),
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.BrowserManager",
            return_value=browser,
        ),
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.LoginService",
            FakeLoginService,
        ),
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.EmploymentTerminationService",
            return_value=service,
        ),
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli.configure_logging",
            return_value=Mock(),
        ),
        patch(
            "ehrm.entrypoints.employment_termination_e2e_cli._save_screenshot",
            side_effect=assert_browser_is_active,
        ) as save_screenshot,
    ):
        status = main(["--input", str(workbook_path)])

    assert status == 1
    save_screenshot.assert_called_once()
    assert browser.active is False
