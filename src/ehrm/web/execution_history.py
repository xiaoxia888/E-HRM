"""Searchable execution history; full application snapshots stay out of task WS."""
from __future__ import annotations

import json
import re
from threading import Lock
from types import SimpleNamespace

from ehrm.web.execution_context import OPERATION_LABELS, rights_context


def scoped_result(task, application):
    result = dict(task.result) if isinstance(task.result, dict) else {}
    if task.operation in {'rights_statement.acquire', 'erp.rights.upload'}:
        rows = {str(person.get('row_number')) for person in application.get('people', []) if person.get('row_number')}
        raw_items = result.get('items')
        items = [item for item in (raw_items if isinstance(raw_items, list) else []) if isinstance(item, dict) and (not rows or str(item.get('row_number')) in rows)]
        result['items'] = items
        field = 'erp_success' if task.operation == 'erp.rights.upload' else 'success'
        result['succeeded'] = sum(item.get(field) is True for item in items)
        result['failed'] = sum(item.get(field) is False for item in items)
    return result


def outcome(task, result):
    if task.status.value not in {'succeeded', 'failed'}:
        return task.status.value
    if task.operation in {'rights_statement.acquire', 'erp.rights.upload'}:
        good, bad = result.get('succeeded', 0), result.get('failed', 0)
        if bad:
            return 'partial' if good else 'failed'
        if good:
            return 'succeeded'
    if result.get('unknown_count'):
        return 'unknown'
    rows = result.get('results')
    if isinstance(rows, list) and rows:
        statuses = [row.get('status') for row in rows if isinstance(row, dict)]
        if any(status in {'unknown', 'submitting'} for status in statuses):
            return 'unknown'
        if any(status in {'failed', 'not_processed'} for status in statuses):
            return 'partial' if any(status in {'succeeded', 'submitted', 'existing'} for status in statuses) else 'failed'
        if statuses and all(status == 'existing' for status in statuses):
            return 'existing'
    return task.status.value


def person_results(task, application, result):
    people = application.get('people', [])
    rights_items = {str(item.get('row_number')): item for item in result.get('items', []) if isinstance(item, dict)}
    rows = result.get('results')
    rows = rows if isinstance(rows, list) else []
    keys = {row.get('person_key'): row for row in rows if isinstance(row, dict) and row.get('person_key')}
    normalized = []
    for index, person in enumerate(people):
        row = rights_items.get(str(person.get('row_number')))
        if row is not None:
            field = 'erp_success' if task.operation == 'erp.rights.upload' else 'success'
            row = {**row, 'status': 'succeeded' if row.get(field) is True else 'failed' if row.get(field) is False else task.status.value,
                   'message': row.get('erp_message') if field == 'erp_success' else row.get('message')}
        elif person.get('person_key') in keys:
            row = keys[person['person_key']]
        elif index < len(rows) and isinstance(rows[index], dict):
            row = rows[index]
        else:
            row = {}
        normalized.append({**person, 'status': row.get('status') or ('not_processed' if task.status.terminal else task.status.value),
                           'message': row.get('message') or '', 'file_name': row.get('file_name'),
                           'erp_success': row.get('erp_success'), 'erp_message': row.get('erp_message') or ''})
    return normalized


class ExecutionHistoryService:
    def __init__(self, repository, coordinator, rights_service, operation_repository, logger):
        self.repository, self.coordinator = repository, coordinator
        self.rights_service, self.operation_repository, self.logger = rights_service, operation_repository, logger
        self._restore_lock = Lock()

    def restore_history(self):
        # Only trusted local evidence is used. Never query today's live NocoBase
        # application and present it as an immutable past application snapshot.
        with self._restore_lock:
            for task in self.repository.missing_execution_records():
                context = self._legacy_context(task)
                self.repository.save_submission(task, context, preserve_task=True)

    def _legacy_context(self, task):
        context = {'account': {'display_name': task.resource_label}, 'applications': [{
            'source': 'legacy', 'transaction_type': '', 'title': task.title,
            'erp_code': '', 'application_code': '', 'initiator': '', 'initiated_at': '',
            'problem_description': '', 'handling_method': '', 'people': [], 'snapshot_origin': 'unavailable',
        }]}
        result = task.result if isinstance(task.result, dict) else {}
        if task.operation in {'rights_statement.acquire', 'erp.rights.upload'}:
            for artifact in result.get('artifacts', []):
                if not isinstance(artifact, dict) or not str(artifact.get('name', '')).endswith('.xlsx'):
                    continue
                token = str(artifact.get('url') or '').rsplit('/', 1)[-1]
                path = self.rights_service.artifacts.resolve(token)
                if path is None:
                    continue
                try:
                    records = self.rights_service.loader.load(path)
                    match = re.match(r'([0-9a-f]{32})_', path.name)
                    state_path = self.rights_service.import_root / f'{match[1]}.json' if match else None
                    state = json.loads(state_path.read_text()) if state_path and state_path.is_file() else None
                    restored = rights_context(records, SimpleNamespace(account='', display_name=task.resource_label), erp_state=state)
                    for application in restored['applications']:
                        application['snapshot_origin'] = 'recovered'
                        if task.title.startswith('打印权益申请 '):
                            application.update(source='nocobase', application_code=application['erp_code'], erp_code='', title=task.title)
                    return restored
                except Exception:
                    self.logger.warning('历史申请资料无法还原 task_id=%s', task.task_id)
        elif task.operation.startswith('application.') and ':' in task.operation:
            run_id = task.operation.split(':', 1)[1]
            with self.operation_repository.connect() as db:
                run = db.execute('SELECT application_id FROM application_runs WHERE id=?', (run_id,)).fetchone()
                people = db.execute('SELECT name,person_key FROM application_people_operations WHERE run_id=?', (run_id,)).fetchall()
            if run:
                context['applications'][0].update(application_id=run['application_id'], source='nocobase',
                                                   people=[dict(row) for row in people])
        return context

    def list(self, **filters):
        self.restore_history()
        response = self.repository.execution_records(**filters)
        records = []
        for row in response['records']:
            context = json.loads(row.pop('context_json'))
            application = context['application']
            result = json.loads(row.pop('result_json') or '{}')
            task = SimpleNamespace(operation=row['operation'], result=result,
                                   status=SimpleNamespace(value=row['status']))
            scoped = scoped_result(task, application)
            row.update(operation_label=OPERATION_LABELS.get(row['operation'].split(':', 1)[0], row['operation']),
                       outcome=outcome(task, scoped), snapshot_origin=application.get('snapshot_origin', 'unavailable'))
            # List responses contain only summary fields. Personnel and the full
            # result are read only when the user opens a specific record.
            row.pop('error', None)
            row.pop('message', None)
            records.append(row)
        return {**response, 'records': records}

    def detail(self, task_id, application_index):
        self.restore_history()
        context = self.repository.execution_record(task_id, application_index)
        task = self.coordinator.get(task_id) or self.repository.get(task_id)
        if not context or not task:
            return None
        application = context['application']
        result = scoped_result(task, application)
        task_payload = task.to_dict()
        task_payload['result'] = result
        return {**context, 'task': task_payload, 'operation_label': OPERATION_LABELS.get(task.operation.split(':', 1)[0], task.operation),
                'outcome': outcome(task, result), 'people': person_results(task, application, result)}
