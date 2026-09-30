from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
import re

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.ai.business_classification import BusinessIntent
from ehrm.modules.ai.business_people import BusinessPeopleExtraction
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.erp.models import ErpTaskRecord
from ehrm.modules.erp.person_service import ErpPersonLookupService


@dataclass(frozen=True, slots=True)
class BusinessPerson:
    name: str
    identity_number: str = ""
    company: str = ""
    department: str = ""
    employee_code: str = ""
    match_status: str = "not_found"


@dataclass(frozen=True, slots=True)
class BusinessPersonIssue:
    code: str
    person_name: str
    message: str


@dataclass(frozen=True, slots=True)
class BusinessPeopleResult:
    application_code: str
    business_type: str
    people: tuple[BusinessPerson, ...]
    issues: tuple[BusinessPersonIssue, ...]

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "needs_review": self.needs_review}


class ErpBusinessPeopleService:
    """Extracts people from one ERP application and enriches only unambiguous matches."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        *,
        ai_client: OllamaTaskExtractionClient | None = None,
        person_lookup: ErpPersonLookupService | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._ai_client = ai_client
        self._person_lookup = person_lookup

    def extract(
        self,
        record: ErpTaskRecord,
        intent: BusinessIntent,
        reasoning_mode: str | ReasoningMode | None = None,
    ) -> BusinessPeopleResult:
        if intent not in (
            BusinessIntent.EMPLOYMENT_ENROLLMENT,
            BusinessIntent.EMPLOYMENT_TERMINATION,
        ):
            raise ValueError("只支持参保和退保人员解析")
        client = self._ai_client or OllamaTaskExtractionClient(
            self._settings.ai, self._logger
        )
        extraction: BusinessPeopleExtraction = client.extract_business_people(
            record,
            intent,
            reasoning_mode or self._settings.ai.default_reasoning_mode,
        )
        if not extraction.people:
            return BusinessPeopleResult(
                record.code,
                intent.value,
                (),
                (
                    BusinessPersonIssue(
                        ErrorCode.AI_NO_PERSON_EXTRACTED.value,
                        "",
                        display_message(ErrorCode.AI_NO_PERSON_EXTRACTED),
                    ),
                ),
            )
        lookup = self._person_lookup or ErpPersonLookupService(
            self._settings, self._logger
        )
        identity_numbers = tuple(dict.fromkeys(
            person.identity_number for person in extraction.people if person.identity_number
        ))
        names = tuple(dict.fromkeys(
            person.name for person in extraction.people if not person.identity_number
        ))
        try:
            by_identity, by_name = lookup.lookup_people(
                identity_numbers=identity_numbers,
                names=names,
            )
        except EhrmError as exc:
            self._logger.error(
                "ERP 人员补全失败 code=%s task=%s details=%s",
                exc.code.value,
                record.code,
                exc.details or exc.message,
            )
            return BusinessPeopleResult(
                record.code,
                intent.value,
                tuple(BusinessPerson(
                    person.name, person.identity_number, match_status="lookup_failed"
                ) for person in extraction.people),
                (BusinessPersonIssue(
                    exc.code.value,
                    "",
                    display_message(exc.code, exc.message),
                ),),
            )
        people: list[BusinessPerson] = []
        issues: list[BusinessPersonIssue] = []
        for extracted in extraction.people:
            source_identity = extracted.identity_number
            matches = (
                by_identity.get(source_identity, ())
                if source_identity
                else by_name.get(extracted.name, ())
            )
            if not matches:
                people.append(BusinessPerson(extracted.name, source_identity))
                issues.append(BusinessPersonIssue(
                    ErrorCode.ERP_PERSON_NOT_FOUND.value,
                    extracted.name,
                    f"ERP 人员库未找到“{extracted.name}”对应的人员，请人工核对",
                ))
                continue
            if len(matches) > 1:
                people.append(BusinessPerson(
                    extracted.name,
                    source_identity if source_identity else "",
                    match_status="ambiguous",
                ))
                issues.append(BusinessPersonIssue(
                    ErrorCode.ERP_PERSON_AMBIGUOUS.value,
                    extracted.name,
                    f"ERP 人员库找到多名“{extracted.name}”，请人工确认",
                ))
                continue
            match = matches[0]
            if source_identity and match.name.strip() != extracted.name:
                people.append(BusinessPerson(
                    extracted.name, source_identity, match_status="name_mismatch"
                ))
                issues.append(BusinessPersonIssue(
                    ErrorCode.ERP_PERSON_IDENTITY_NAME_MISMATCH.value,
                    extracted.name,
                    "申请中的姓名与身份证对应的 ERP 人员不一致，请人工核对",
                ))
                continue
            if not source_identity and not re.fullmatch(
                r"(?:\d{15}|\d{17}[0-9X])", match.identity_number.strip().upper()
            ):
                people.append(BusinessPerson(extracted.name, match_status="invalid_identity"))
                issues.append(BusinessPersonIssue(
                    ErrorCode.ERP_PERSON_IDENTITY_INVALID.value,
                    extracted.name,
                    "ERP 人员库中的身份证号为空或格式不正确，请人工核对",
                ))
                continue
            identity = source_identity or match.identity_number.strip().upper()
            people.append(BusinessPerson(
                name=extracted.name,
                identity_number=identity,
                company=match.company,
                department=match.department,
                employee_code=match.employee_code,
                match_status=(
                    "matched_by_identity" if source_identity else "matched_by_name"
                ),
            ))
        return BusinessPeopleResult(
            record.code,
            intent.value,
            tuple(people),
            tuple(issues),
        )
