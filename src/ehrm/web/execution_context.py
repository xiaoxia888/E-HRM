"""Allowlisted, immutable business information captured before a task starts."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from hashlib import sha256

BUSINESS_LABELS = {
    'social_security_rights': '单位社保权益单', 'social_security_termination': '社保退工停保登记',
    'social_security_enrollment': '社保用工参保登记', 'medical_termination': '医保退工停保登记',
    'medical_enrollment': '医保人员参保登记', 'social_security_consult': '社保咨询',
}
OPERATION_LABELS = {
    'rights_statement.acquire': '获取社保权益单', 'erp.rights.upload': '上传权益单至 ERP',
    'application.termination': '社保退工停保', 'application.information_collection': '社保基础信息采集',
    'application.enrollment': '社保参保登记', 'application.medical_termination': '医保停保',
    'application.medical_enrollment': '医保参保',
}
PERSON_FIELDS = ('name', 'identity_number', 'department', 'company', 'phone', 'insurance_type', 'start_month', 'end_month',
                 'termination_reason', 'household_type', 'ethnicity', 'job_type', 'contract_type', 'contract_start_date',
                 'contract_end_date', 'contract_add_reason', 'insurance_identity', 'monthly_contribution_salary',
                 'is_technology', 'med_ins_stop_reason', 'med_stop_date', 'med_ins_stop_month_fee', 'arrive_unit_time',
                 'cert_valid_from', 'cert_valid_to', 'household_address', 'print_group', 'row_number', 'person_key')


def text(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).strip() if isinstance(value, (str, int, float)) else ''


def execution_account(account):
    value = text(getattr(account, 'account', ''))
    profile = getattr(account, 'profile', {})
    return {'id': getattr(account, 'id', None), 'display_name': text(getattr(account, 'display_name', '')),
            'masked_account': value[:2] + '*' * max(4, len(value) - 4) + value[-2:] if len(value) > 4 else '*' * len(value),
            'system_type': text(getattr(account, 'system_type', '')),
            'login_method': text(profile.get('login_method')) if isinstance(profile, dict) else ''}


def person_snapshot(value):
    row = asdict(value) if is_dataclass(value) else dict(value)
    row.update(name=row.get('name') or row.get('user_name'), identity_number=row.get('identity_number') or row.get('id_card_no'),
               phone=row.get('phone') or row.get('mobile'), company=row.get('company') or row.get('unit'),
               person_key=row.get('person_key') or row.get('operation_key'))
    if row.get('identity_number') and not row.get('person_key'):
        row['person_key'] = sha256(text(row['identity_number']).upper().encode()).hexdigest()
    region = row.get('household_region')
    names = []
    for _ in range(6):
        if not isinstance(region, dict):
            break
        name = text(region.get('name'))
        if name and name != '中国':
            names.insert(0, name)
        region = region.get('parent')
    if names:
        row['household_address'] = ' / '.join(names)
    return {key: text(row[key]) for key in PERSON_FIELDS if row.get(key) is not None}


def nocobase_context(detail, account, *, people=None):
    raw = getattr(detail, 'erp_all_field_value', None) or {}
    kind = detail.problem_type
    if people is None:
        field = {'social_security_rights': 'related_persons', 'social_security_termination': 'termination_person',
                 'social_security_enrollment': 'insurance_person', 'medical_termination': 'med_ins_withdrawal_record',
                 'medical_enrollment': 'med_ins_enrollee'}.get(kind, 'related_persons')
        people = getattr(detail, field, ())
    application = {
        'source': 'nocobase', 'application_id': detail.application_id, 'application_code': detail.code,
        'erp_code': text(getattr(detail, 'erp_code', '')) or text(raw.get('Code')),
        'transaction_type': text(raw.get('ProbType')) or BUSINESS_LABELS.get(kind, kind),
        'title': getattr(detail, 'title', '') or detail.code, 'initiator': getattr(detail, 'initiator_name', '') or text(raw.get('Originator') or raw.get('RegHumName')),
        'initiated_at': text(getattr(detail, 'initiation_date', None)) or text(raw.get('ProposedDate')),
        'problem_description': getattr(detail, 'problem_description', ''), 'handling_method': getattr(detail, 'handling_method', ''),
        'department': getattr(detail, 'department', ''), 'people': [person_snapshot(row) for row in people],
        'snapshot_origin': 'captured',
    }
    return {'account': execution_account(account), 'applications': [application]}


def rights_context(records, account, *, erp_state=None, filename=''):
    grouped = defaultdict(list)
    for record in records:
        grouped[record.task_number.strip()].append(person_snapshot(record))
    tasks = {text(row.get('task_number')): row for row in (erp_state or {}).get('tasks', []) if isinstance(row, dict)}
    applications = []
    for code, people in grouped.items():
        task = tasks.get(code, {})
        applications.append({
            'source': 'erp' if erp_state else 'excel', 'application_code': '', 'erp_code': code,
            'transaction_type': text(task.get('transaction_type')) or '单位社保权益单',
            'title': text(task.get('title')) or filename or code or 'Excel 权益单申请',
            'initiator': text(task.get('originator')), 'initiated_at': text(task.get('application_date')),
            'problem_description': text(task.get('description')), 'handling_method': text(task.get('handling_method')),
            'department': text(task.get('department')), 'people': people, 'snapshot_origin': 'captured',
        })
    return {'account': execution_account(account), 'applications': applications}
