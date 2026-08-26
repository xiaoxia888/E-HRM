from __future__ import annotations

from ehrm.core.exceptions import (
    AiResponseInvalidError,
    MedicalInsuranceUnsupportedError,
)
from ehrm.modules.ai.models import (
    DateBasis,
    ExtractedPerson,
    ExtractedPrintGroup,
    ExtractedRequirement,
    RequirementType,
    TaskExtraction,
    resolve_relative_month_ranges,
)
from ehrm.modules.ai.v2_models import (
    SemanticExtraction,
    SemanticPrintPlan,
    SemanticRequest,
    SemanticTimeType,
)
from ehrm.modules.erp.models import ErpTaskRecord


_PRINT_MODE_REVIEW_REASON = "原文未说明多人合并打印还是每人单独打印"


def normalize_semantic_extraction(
    extraction: SemanticExtraction,
    record: ErpTaskRecord,
) -> TaskExtraction:
    """Converts the compact V2 semantic result into the existing domain model."""

    _validate_people_exist_in_application(extraction, record)
    selected_requests = _remove_summary_duplicates(extraction.requests, record)
    requirements: list[ExtractedRequirement] = []
    groups: list[ExtractedPrintGroup] = []
    task_warnings: list[str] = []

    for sequence, request in enumerate(selected_requests, start=1):
        supported = request.request_type == RequirementType.RIGHTS_STATEMENT.value
        requirements.append(
            ExtractedRequirement(
                sequence=sequence,
                source_text=request.source_text,
                requirement_type=request.request_type,
                supported=supported,
                reason=request.reason,
            )
        )
        if not supported:
            task_warnings.append(
                f"申请还包含未生成权益单的内容：{request.source_text}；"
                f"{request.reason}"
            )
            continue
        assert request.print_plan is not None
        groups.append(_to_domain_group(request, request.print_plan, sequence))

    if not groups:
        review_reasons = ("未识别到可执行的具体人员权益单需求",)
        needs_review = True
    else:
        review_reasons = tuple(
            dict.fromkeys(
                reason
                for group in groups
                for reason in group.review_reasons
            )
        )
        needs_review = bool(review_reasons)

    normalized = TaskExtraction(
        requirements=tuple(requirements),
        groups=tuple(groups),
        needs_review=needs_review,
        review_reasons=review_reasons,
        warnings=tuple(dict.fromkeys(task_warnings)),
    )
    return resolve_relative_month_ranges(normalized, record.initiated_date)


def _to_domain_group(
    request: SemanticRequest,
    plan: SemanticPrintPlan,
    requirement_sequence: int,
) -> ExtractedPrintGroup:
    if plan.benefit_category == "医保":
        raise MedicalInsuranceUnsupportedError(
            "当前版本暂不支持医保权益单",
            details=(
                f"申请“{request.source_text}”属于医保业务，"
                "当前仅支持社保权益单，请等待后续医保功能接入"
            ),
        )
    time = plan.time
    date_basis = (
        DateBasis.EXPLICIT_RANGE.value
        if time.time_type
        in {
            SemanticTimeType.EXPLICIT_RANGE.value,
            SemanticTimeType.EXPLICIT_MONTH.value,
        }
        else time.time_type
    )
    reasons: list[str] = []
    if time.time_type == SemanticTimeType.MISSING.value:
        reasons.append("模型未能确定开始月份和结束月份")
    elif time.time_type == SemanticTimeType.AMBIGUOUS.value:
        reasons.append("原文中的时间条件存在多种解释")
    elif (
        time.time_type == SemanticTimeType.UNTIL_NOW.value
        and not time.start_month
    ):
        reasons.append("原文使用“至今”，但未能确定开始月份")
    if len(plan.people) > 1 and plan.print_mode is None:
        reasons.append(_PRINT_MODE_REVIEW_REASON)
    reasons = list(dict.fromkeys(reason for reason in reasons if reason.strip()))
    people = tuple(
        ExtractedPerson(
            name=person.name,
            evidence=request.source_text,
            confidence=1.0,
            social_security_number=person.social_security_number,
            birth_year_hint=person.birth_year_hint,
        )
        for person in plan.people
    )
    return ExtractedPrintGroup(
        requirement_sequence=requirement_sequence,
        print_mode=plan.print_mode,
        insurance_type="养老",
        start_month=time.start_month,
        end_month=time.end_month,
        time_expression=time.expression,
        date_basis=date_basis,
        relative_month_count=time.month_count,
        evidence=request.source_text,
        people=people,
        needs_review=bool(reasons),
        review_reasons=tuple(reasons),
        warnings=(),
    )


def _remove_summary_duplicates(
    requests: tuple[SemanticRequest, ...],
    record: ErpTaskRecord,
) -> tuple[SemanticRequest, ...]:
    """Removes exact duplicates and a title-only incomplete summary request."""

    result: list[SemanticRequest] = []
    seen: set[tuple[object, ...]] = set()
    title = _normalized_text(record.title)
    detail = _normalized_text(record.description)
    for request in requests:
        signature = _request_signature(request)
        if signature in seen:
            continue
        if _is_incomplete_title_summary(request, title, detail, requests):
            continue
        seen.add(signature)
        result.append(request)
    return tuple(result)


def _is_incomplete_title_summary(
    request: SemanticRequest,
    title: str,
    detail: str,
    all_requests: tuple[SemanticRequest, ...],
) -> bool:
    plan = request.print_plan
    if (
        request.request_type != RequirementType.RIGHTS_STATEMENT.value
        or plan is None
        or plan.time.time_type != SemanticTimeType.MISSING.value
        or not title
        or _normalized_text(request.source_text) != title
    ):
        return False
    people = _people_signature(plan)
    for candidate in all_requests:
        candidate_plan = candidate.print_plan
        if candidate is request or candidate_plan is None:
            continue
        if candidate.request_type != RequirementType.RIGHTS_STATEMENT.value:
            continue
        if candidate_plan.time.time_type in {
            SemanticTimeType.MISSING.value,
            SemanticTimeType.AMBIGUOUS.value,
        }:
            continue
        if _people_signature(candidate_plan) != people:
            continue
        if candidate_plan.benefit_category != plan.benefit_category:
            continue
        candidate_source = _normalized_text(candidate.source_text)
        if detail and candidate_source and candidate_source in detail:
            return True
    return False


def _request_signature(request: SemanticRequest) -> tuple[object, ...]:
    if request.print_plan is None:
        return (
            request.request_type,
            _normalized_text(request.source_text),
            request.reason,
        )
    plan = request.print_plan
    return (
        request.request_type,
        _people_signature(plan),
        plan.benefit_category,
        plan.print_mode,
        plan.time.time_type,
        plan.time.start_month,
        plan.time.end_month,
        plan.time.month_count,
    )


def _people_signature(plan: SemanticPrintPlan) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                person.name,
                person.social_security_number or "",
                person.birth_year_hint,
            )
            for person in plan.people
        )
    )


def _normalized_text(value: str) -> str:
    return "".join(str(value or "").split())


def _validate_people_exist_in_application(
    extraction: SemanticExtraction,
    record: ErpTaskRecord,
) -> None:
    source = f"{record.title}\n{record.description}"
    for request in extraction.requests:
        if request.print_plan is None:
            continue
        for person in request.print_plan.people:
            if person.name not in source:
                raise AiResponseInvalidError(
                    f"模型提取的人员“{person.name}”未出现在申请标题或详细描述中"
                )
