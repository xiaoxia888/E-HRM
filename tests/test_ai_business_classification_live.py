"""Opt-in real-model checks; no ERP login, browser launch or business submission."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from ehrm.core.settings import load_settings
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.erp.models import ErpTaskRecord


pytestmark = pytest.mark.skipif(
    os.environ.get("EHRM_RUN_LIVE_AI_TESTS") != "1",
    reason="显式设置 EHRM_RUN_LIVE_AI_TESTS=1 才调用真实大模型",
)


@pytest.mark.parametrize(
    ("title", "description", "expected", "classified"),
    [
        pytest.param(
            "投标人员社保开具",
            "1.开下许性平、蔡进、李兰兰、穆家童、孙如、魏楷星、李玉生、冯加东8月份的社保，分开单独开",
            "单位社保权益单",
            True,
            id="reported-colloquial-request",
        ),
        pytest.param(
            "人员材料", "麻烦把甲员工和乙员工过去一年的缴费记录拉出来，放在一张上",
            "单位社保权益单", True, id="historical-records-without-standard-name",
        ),
        pytest.param(
            "项目人员社保", "甲员工下个月起由我公司给他上社保",
            "用工参保登记", True, id="start-coverage-colloquial",
        ),
        pytest.param(
            "员工社保调整", "甲员工以后不要在本单位继续缴了，请办理停缴",
            "退工停保登记", True, id="stop-coverage-colloquial",
        ),
        pytest.param(
            "费用咨询", "甲员工8月份的社保费用怎么算？请解释一下",
            "社保咨询", False, id="cost-question-is-not-proof-request",
        ),
        pytest.param(
            "社保办理", "请开通甲员工的参保关系，从下个月开始缴纳",
            "用工参保登记", True, id="open-is-not-always-proof",
        ),
        pytest.param(
            "合同资料", "甲员工已经离职，请把合同存档",
            "社保咨询", False, id="leaving-without-stopping-request",
        ),
        pytest.param(
            "新员工合同后续事宜", "合同请归档，另外请从八月开始为五位新员工办理参保",
            "用工参保登记", True, id="background-does-not-hide-request",
        ),
    ],
)
def test_real_model_classifies_requested_business_outcome(
    tmp_path: Path,
    title: str,
    description: str,
    expected: str,
    classified: bool,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    record = ErpTaskRecord(
        id="live-regression",
        code="AI-REGRESSION",
        initiated_date="2026-09-22",
        title=title,
        description=description,
        transaction_type="社保咨询",
        status="",
        originator="",
        department="",
    )
    result = OllamaTaskExtractionClient(
        settings.ai, logging.getLogger("test.ai.classification.live")
    ).classify(record, settings.ai.default_reasoning_mode)

    assert result.business_type == expected, result.reason or result.evidence
    assert result.classified is classified
