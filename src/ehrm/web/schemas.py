from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ehrm.core.preferences import (
    DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    DEFAULT_NO_RESULT_CONFIRM_SECONDS,
    DEFAULT_PREVIEW_DOWNLOAD_DELAY_MS,
)
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
    login_method: str = "direct"


class AccountEditDetail(BaseModel):
    id: int
    system_type: str
    display_name: str
    account: str
    secondary_account: str
    password_mask: str
    password_saved: bool
    login_method: str = "direct"
    api_key_saved: bool = False
    api_key_mask: str = ""


class AccountUpdateRequest(BaseModel):
    account_id: int | None = None
    account: str = ""
    secondary_account: str = ""
    password: str = ""
    display_name: str = ""
    login_method: str = "direct"
    api_key: str = ""


class NocoBaseConnectionTestRequest(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    api_key: str = ""


class ScheduledJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    task_type: str = "erp_nocobase_sync"
    cron: str = Field(min_length=1, max_length=150)
    enabled: bool = Field(default=False, strict=True)
    lookback_days: int = Field(default=2, ge=1, le=366, strict=True)


class NocoBaseSyncRequest(BaseModel):
    start_date: str = ""
    end_date: str = ""
    dry_run: bool = Field(default=False, strict=True)


class PreferencesUpdateRequest(BaseModel):
    output_path: str = ""
    export_mode: str = "individual"
    batch_size: int = 50
    upload_to_erp: bool = False
    open_output_folder: bool = False
    ai_model_profile: str = ""
    ai_reasoning_mode: str = ""
    execution_speed: str = "standard"
    no_result_confirm_seconds: int = DEFAULT_NO_RESULT_CONFIRM_SECONDS
    preview_download_delay_ms: int = DEFAULT_PREVIEW_DOWNLOAD_DELAY_MS
    download_timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS


class RightsTaskRequest(BaseModel):
    import_id: str
    account_id: int
    export_mode: str = "individual"
    batch_size: int = 50
    upload_to_erp: bool = False


class RightsManualRecordRequest(BaseModel):
    task_number: str = ""
    print_group: str = ""
    unit: str
    department: str
    name: str
    identity_number: str
    insurance_type: str
    start_month: str
    end_month: str


class RightsCandidateSelectionRequest(BaseModel):
    candidate_id: str


class RightsPrintGroupResolutionRequest(BaseModel):
    task_number: str
    group_id: str
    mode: str


class RightsPrintGroupConditionsRequest(BaseModel):
    task_number: str
    group_id: str
    insurance_type: str
    start_month: str
    end_month: str
    overwrite: bool = False


class ErpRightsExtractionRequest(BaseModel):
    account_id: int
    transaction_type: str
    statuses: list[int] = []
    application_code: str = ""
    start_date: str = ""
    end_date: str = ""
    page_size: int = 50
    reasoning_mode: str = ""


class ErpBusinessPeopleRequest(BaseModel):
    application_code: str
    application_date: str = ""
    title: str = ""
    description: str = ""
    erp_transaction_type: str = ""
    reasoning_mode: str = ""


class NocoBasePrintRequest(BaseModel):
    account_id: int
    upload_to_erp: bool = False


class NocoBaseTerminationRequest(BaseModel):
    account_id: int = Field(ge=1)
    confirmed: bool = False


class ConcurrencyPolicyItem(BaseModel):
    situation: str
    behavior: str
    explanation: str


class ConcurrencyPolicyResponse(BaseModel):
    mode: str
    server_instances: int
    items: list[ConcurrencyPolicyItem]
