from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from ehrm.web.tasks import TaskKind, TaskSnapshot, TaskStatus


class TaskResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    task_id: str
    title: str
    operation: str
    kind: TaskKind
    status: TaskStatus
    resource_label: str
    queue_position: int
    message: str
    progress_current: int
    progress_total: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    result: Any | None
    error: str

    @classmethod
    def from_snapshot(cls, snapshot: TaskSnapshot) -> "TaskResponse":
        return cls.model_validate(snapshot.to_dict())


class TaskListResponse(BaseModel):
    revision: int
    tasks: list[TaskResponse]


class AccountSummary(BaseModel):
    id: int
    system_type: str
    display_name: str
    masked_account: str
    is_default: bool
    ready: bool


class AccountEditDetail(BaseModel):
    id: int
    system_type: str
    display_name: str
    account: str
    secondary_account: str
    password_mask: str
    password_saved: bool


class AccountUpdateRequest(BaseModel):
    account_id: int | None = None
    account: str = ""
    secondary_account: str = ""
    password: str = ""
    display_name: str = ""


class PreferencesUpdateRequest(BaseModel):
    output_path: str = ""
    export_mode: str = "individual"
    batch_size: int = 50
    upload_to_erp: bool = False
    open_output_folder: bool = False
    ai_model_profile: str = ""
    ai_reasoning_mode: str = ""
    execution_speed: str = "standard"
    no_result_confirm_seconds: int = 10
    preview_download_delay_ms: int = 1500
    download_timeout_seconds: int = 20


class RightsTaskRequest(BaseModel):
    import_id: str
    account_id: int
    export_mode: str = "individual"
    batch_size: int = 50
    upload_to_erp: bool = False


class ErpRightsExtractionRequest(BaseModel):
    account_id: int
    transaction_type: str
    statuses: list[int] = []
    application_code: str = ""
    start_date: str = ""
    end_date: str = ""
    page_size: int = 50
    reasoning_mode: str = ""


class NocoBasePrintRequest(BaseModel):
    account_id: int
    upload_to_erp: bool = False


class ConcurrencyPolicyItem(BaseModel):
    situation: str
    behavior: str
    explanation: str


class ConcurrencyPolicyResponse(BaseModel):
    mode: str
    server_instances: int
    items: list[ConcurrencyPolicyItem]
