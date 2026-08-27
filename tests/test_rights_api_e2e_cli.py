from ehrm.entrypoints.rights_api_e2e_cli import _default_filename, main
from ehrm.modules.rights_statement.api_models import InsuranceCode


def test_rights_api_e2e_check_config_does_not_open_browser(capsys) -> None:
    result = main(
        [
            "--identity-number",
            "test-identity",
            "--start-month",
            "202601",
            "--end-month",
            "202608",
            "--insurance",
            "养老",
            "--check-config",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "配置和参数检查通过" in output
    assert "queryCommon" in output
    assert "affair/case/right/bill" in output
    assert "loadUnitRightsBill" in output


def test_rights_api_e2e_rejects_invalid_month_before_browser(capsys) -> None:
    result = main(
        [
            "--identity-number",
            "test-identity",
            "--start-month",
            "202613",
            "--end-month",
            "202608",
            "--insurance",
            "养老",
            "--check-config",
        ]
    )

    assert result == 2
    assert "月份必须在 01 到 12 之间" in capsys.readouterr().out


def test_rights_api_e2e_default_filename_contains_no_identity_number() -> None:
    filename = _default_filename(
        InsuranceCode.WORK_INJURY,
        "202601",
        "202608",
        3,
    )

    assert filename == "工伤_202601-202608_3人_权益单.pdf"
