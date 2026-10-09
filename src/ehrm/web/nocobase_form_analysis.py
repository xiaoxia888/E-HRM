from __future__ import annotations

from dataclasses import asdict
from datetime import date
import logging
from typing import Callable

from ehrm.core.settings import AppSettings
from ehrm.modules.ai.business_classification import BusinessIntent
from ehrm.modules.ai.business_people import BusinessPeopleExtraction, ExtractedBusinessPerson
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.erp.business_people_service import ErpBusinessPeopleService
from ehrm.modules.erp.extraction_service import ErpTaskExtractionService
from ehrm.modules.erp.models import ErpTaskRecord


_TYPES = {
    "单位社保权益单": (BusinessIntent.RIGHTS_STATEMENT, "social_security_rights"),
    "用工参保登记": (BusinessIntent.EMPLOYMENT_ENROLLMENT, "social_security_enrollment"),
    "退工停保登记": (BusinessIntent.EMPLOYMENT_TERMINATION, "social_security_termination"),
}
_INSURANCE_TYPES = {"养老": "elderly_care", "工伤": "work_injury", "失业": "unemployment"}


class NocoBaseFormAnalysisService:
    """Analyzes current form text and returns unsaved NocoBase field values."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        *,
        ai_client: OllamaTaskExtractionClient | None = None,
        people_service: ErpBusinessPeopleService | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._ai_client = ai_client or OllamaTaskExtractionClient(settings.ai, logger)
        self._people_service = people_service or ErpBusinessPeopleService(
            settings, logger, ai_client=self._ai_client
        )
        self._today = today

    def analyze(
        self,
        record: ErpTaskRecord,
        reasoning_mode: str | None = None,
    ) -> dict[str, object]:
        mode = reasoning_mode or self._settings.ai.default_reasoning_mode
        decision = self._ai_client.classify(record, mode)
        classification = asdict(decision)
        if not decision.classified or decision.business_type not in _TYPES:
            return {
                "classification": classification,
                "business_type": decision.business_type,
                "prob_type": "",
                "people": [],
                "issues": [{
                    "code": "BUSINESS_TYPE_UNCLEAR",
                    "person_name": "",
                    "message": decision.reason or "无法明确判断业务类型，请人工核对",
                }],
                "needs_review": True,
                "form_values": {},
            }

        intent, prob_type = _TYPES[decision.business_type]
        issues: list[dict[str, str]] = []
        if intent is BusinessIntent.RIGHTS_STATEMENT:
            extraction = self._ai_client.extract(record, mode).extraction
            groups = extraction.groups
            source_helper = ErpTaskExtractionService(self._settings, self._logger)
            extracted_people = BusinessPeopleExtraction(tuple(
                ExtractedBusinessPerson(
                    name=person.name,
                    identity_number=(
                        source_helper._identity_from_application_text(
                            record, person.name, person.social_security_number
                        ) or ""
                    ),
                    evidence=person.evidence,
                )
                for group in groups for person in group.people
            ))
            resolved = self._people_service.resolve_people(record, extracted_people, intent)
            rows = []
            person_index = 0
            group_sequence = 0
            for group in groups:
                if group.print_mode != "individual" and group.people:
                    group_sequence += 1
                insurance_type = _INSURANCE_TYPES.get(group.insurance_type, "")
                if not insurance_type:
                    issues.append({
                        "code": "INSURANCE_TYPE_UNSUPPORTED", "person_name": "",
                        "message": f"险种“{group.insurance_type}”未能映射到 NocoBase，请人工选择",
                    })
                for reason in group.review_reasons:
                    issues.append({
                        "code": "AI_REVIEW_REQUIRED", "person_name": "",
                        "message": reason,
                    })
                for _ in group.people:
                    person = resolved.people[person_index]
                    person_index += 1
                    if group.print_mode == "individual":
                        group_sequence += 1
                    rows.append({
                        "user_name": person.name,
                        "id_card_no": _safe_identity(person),
                        "company": person.company,
                        "dept_name": person.department,
                        "print_group": f"组{group_sequence}",
                        "insurance_type": insurance_type,
                        "start_month": _month_date(group.start_month),
                        "end_month": _month_date(group.end_month),
                    })
            for reason in extraction.review_reasons:
                if not any(item["message"] == reason for item in issues):
                    issues.append({
                        "code": "AI_REVIEW_REQUIRED", "person_name": "",
                        "message": reason,
                    })
            if (extraction.needs_review or any(group.needs_review for group in groups)) and not issues:
                issues.append({
                    "code": "AI_REVIEW_REQUIRED", "person_name": "",
                    "message": "权益单解析结果需要人工核对",
                })
            association = "related_persons"
        else:
            resolved = self._people_service.extract(record, intent, mode)
            if intent is BusinessIntent.EMPLOYMENT_TERMINATION:
                association = "termination_person"
                rows = [
                    {"user_name": person.name, "id_card_no": _safe_identity(person)}
                    for person in resolved.people
                ]
            else:
                association = "insurance_person"
                start = self._today()
                try:
                    end = start.replace(year=start.year + 3)
                except ValueError:
                    end = start.replace(year=start.year + 3, day=28)
                rows = [{
                    "user_name": person.name,
                    "id_card_no": _safe_identity(person),
                    "phone": person.phone,
                    "contract_add_reason": "新签",
                    "contract_start_date": start.isoformat(),
                    "contract_end_date": end.isoformat(),
                    "insurance_identity": "企业职工",
                } for person in resolved.people]

        issues.extend(asdict(issue) for issue in resolved.issues)
        return {
            "classification": classification,
            "business_type": decision.business_type,
            "prob_type": prob_type,
            "people": [asdict(person) for person in resolved.people],
            "issues": issues,
            "needs_review": bool(issues),
            "form_values": {"prob_type": prob_type, association: rows},
        }


def _month_date(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value}-01"


def _safe_identity(person) -> str:
    if person.match_status in {"ambiguous", "name_mismatch", "invalid_identity"}:
        return ""
    return person.identity_number
