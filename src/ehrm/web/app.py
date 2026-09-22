from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from ehrm import __version__
from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.preferences import UserPreferences
from ehrm.core.runtime import application_runtime_root
from ehrm.core.settings import (
    DEFAULT_SETTINGS_PATH,
    AppSettings,
    load_settings,
)
from ehrm.modules.nocobase.application_query_service import (
    NocoBaseApplicationQueryService,
)
from ehrm.gui.template_service import RightsStatementTemplateService
from ehrm.modules.rights_statement.excel_models import ExportMode
from ehrm.web.schemas import (
    AccountSummary,
    AccountEditDetail,
    AccountUpdateRequest,
    ConcurrencyPolicyItem,
    ConcurrencyPolicyResponse,
    ErpRightsExtractionRequest,
    NocoBasePrintRequest,
    TaskListResponse,
    TaskResponse,
    PreferencesUpdateRequest,
    RightsTaskRequest,
    RightsManualRecordRequest,
    RightsPrintGroupResolutionRequest,
    RightsPrintGroupConditionsRequest,
    RightsCandidateSelectionRequest,
)
from ehrm.web.rights_service import ArtifactRegistry, RightsWebService
from ehrm.web.settings_service import WebSettingsService
from ehrm.web.tasks import TaskCoordinator


def create_app(
    *,
    settings: AppSettings | None = None,
    logger: logging.Logger | None = None,
    coordinator: TaskCoordinator | None = None,
) -> FastAPI:
    runtime_root = (
        settings.auth_database_path.parent.parent
        if settings is not None
        else application_runtime_root(DEFAULT_SETTINGS_PATH)
    )
    resolved_settings = settings or load_settings(
        DEFAULT_SETTINGS_PATH,
        data_root=runtime_root,
    )
    resolved_logger = logger or configure_logging(runtime_root / "logs")
    task_coordinator = coordinator or TaskCoordinator(max_workers=8)
    owns_coordinator = coordinator is None
    query_service = NocoBaseApplicationQueryService(
        resolved_settings,
        resolved_logger,
    )
    settings_service = WebSettingsService(resolved_settings, runtime_root)
    artifact_registry = ArtifactRegistry()
    rights_service = RightsWebService(
        settings_service,
        task_coordinator,
        resolved_logger,
        artifact_registry,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if owns_coordinator:
            task_coordinator.close(wait=False)

    app = FastAPI(
        title="信息化人力工作台 Web API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.runtime_root = runtime_root
    app.state.logger = resolved_logger
    app.state.task_coordinator = task_coordinator
    app.state.web_settings_service = settings_service
    app.state.rights_service = rights_service
    app.state.nocobase_query_service = query_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(EhrmError)
    async def ehrm_error_handler(_request: Request, exc: EhrmError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "message": exc.message,
                "details": exc.details or "",
                "code": str(exc.code),
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"message": str(exc), "details": "", "code": "INVALID_INPUT"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "message": "请求参数不完整或格式不正确，请检查后重试",
                "details": jsonable_encoder(exc.errors()),
                "code": "REQUEST_VALIDATION_FAILED",
            },
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "deployment": "single-server",
            "scheduler": "single-authority",
        }

    @app.get(
        "/api/v1/concurrency-policy",
        response_model=ConcurrencyPolicyResponse,
    )
    def concurrency_policy() -> ConcurrencyPolicyResponse:
        return ConcurrencyPolicyResponse(
            mode="单服务器任务协调",
            server_instances=1,
            items=[
                ConcurrencyPolicyItem(
                    situation="同一智慧人社账号",
                    behavior="串行排队",
                    explanation="避免页面、登录会话和验证码互相干扰",
                ),
                ConcurrencyPolicyItem(
                    situation="不同智慧人社账号",
                    behavior="独立浏览器并行",
                    explanation="每个账号使用独立浏览器目录和任务锁",
                ),
                ConcurrencyPolicyItem(
                    situation="普通数据库/API 查询",
                    behavior="直接并行",
                    explanation="查询不占用浏览器自动化队列",
                ),
                ConcurrencyPolicyItem(
                    situation="ERP 写入或批量提交",
                    behavior="按账号或单位串行",
                    explanation="避免同一业务资源被重复写入",
                ),
            ],
        )

    @app.get("/api/v1/accounts", response_model=list[AccountSummary])
    def accounts() -> list[AccountSummary]:
        records = AuthenticationRepository(
            resolved_settings.auth_database_path
        ).list_accounts()
        return [
            AccountSummary(
                id=record.id,
                system_type=record.system_type.value,
                display_name=record.display_name or record.system_type.value,
                masked_account=_mask_account(record.account),
                is_default=record.is_default,
                ready=_account_ready(record.system_type, record.account, record.secondary_account, record.password),
            )
            for record in records
        ]

    @app.get("/api/v1/settings")
    def web_settings() -> dict[str, object]:
        return {**settings_service.preference_payload(), "version": __version__}

    @app.get(
        "/api/v1/settings/accounts/{system_type}",
        response_model=AccountEditDetail,
    )
    def account_edit_detail(
        system_type: SystemType,
        account_id: int | None = Query(default=None, ge=1),
    ) -> AccountEditDetail:
        records = settings_service.repository.list_accounts(system_type)
        selected = next(
            (
                item
                for item in records
                if account_id is not None and item.id == account_id
            ),
            None,
        )
        if selected is None and account_id is None:
            selected = next((item for item in records if item.is_default), None)
        if selected is None:
            raise HTTPException(status_code=404, detail="账号不存在或已被删除")
        return AccountEditDetail(
            id=selected.id,
            system_type=selected.system_type.value,
            display_name=selected.display_name or selected.system_type.value,
            account=selected.account,
            secondary_account=selected.secondary_account,
            password_mask="******" if selected.password else "",
            password_saved=bool(selected.password),
        )

    @app.put("/api/v1/settings/preferences")
    def update_preferences(request: PreferencesUpdateRequest) -> dict[str, object]:
        if request.export_mode not in {"individual", "batch"}:
            raise ValueError("默认导出方式只能是每人一份或合并打印")
        if request.execution_speed not in {"fast", "standard", "stable"}:
            raise ValueError("执行节奏只能选择快速、标准或稳定")
        if request.batch_size < 1:
            raise ValueError("单批人数必须大于 0")
        if not 3 <= request.no_result_confirm_seconds <= 60:
            raise ValueError("无结果确认时间必须在 3–60 秒之间")
        if not 0 <= request.preview_download_delay_ms <= 5000:
            raise ValueError("预览等待时间必须在 0–5000 毫秒之间")
        if not 5 <= request.download_timeout_seconds <= 180:
            raise ValueError("下载超时时间必须在 5–180 秒之间")
        preferences = UserPreferences(**request.model_dump())
        saved = settings_service.save_preferences(preferences)
        return {"message": "系统设置已保存", "preferences": asdict(saved)}

    @app.post("/api/v1/settings/maintenance/clear-temporary")
    def clear_temporary_files() -> dict[str, object]:
        removed = settings_service.clear_temporary_files()
        return {
            "message": f"临时文件清理完成，共移除 {removed} 个文件",
            "removed": removed,
        }

    @app.put(
        "/api/v1/settings/accounts/{system_type}",
        response_model=AccountSummary,
    )
    def update_account(
        system_type: SystemType,
        request: AccountUpdateRequest,
    ) -> AccountSummary:
        saved = settings_service.save_account(
            system_type,
            account_id=request.account_id,
            account=request.account,
            secondary_account=request.secondary_account,
            password=request.password,
            display_name=request.display_name,
        )
        return AccountSummary(
            id=saved.id,
            system_type=saved.system_type.value,
            display_name=saved.display_name or saved.system_type.value,
            masked_account=_mask_account(saved.account),
            is_default=saved.is_default,
            ready=_account_ready(saved.system_type, saved.account, saved.secondary_account, saved.password),
        )

    @app.get("/api/v1/tasks", response_model=TaskListResponse)
    def tasks(limit: int = Query(default=100, ge=1, le=500)) -> TaskListResponse:
        return _task_list(task_coordinator, limit=limit)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
    def task_detail(task_id: str) -> TaskResponse:
        snapshot = task_coordinator.get(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="任务不存在或已清理")
        return TaskResponse.from_snapshot(snapshot)

    @app.post("/api/v1/tasks/{task_id}/cancel", response_model=TaskResponse)
    def cancel_task(task_id: str) -> TaskResponse:
        snapshot = task_coordinator.cancel(task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="任务不存在或已清理")
        return TaskResponse.from_snapshot(snapshot)

    @app.websocket("/api/v1/tasks/ws")
    async def task_events(websocket: WebSocket) -> None:
        await websocket.accept()
        revision = -1
        try:
            while True:
                current = task_coordinator.revision
                if current != revision:
                    revision = current
                    payload = _task_list(task_coordinator, limit=100)
                    await websocket.send_json(payload.model_dump(mode="json"))
                try:
                    event = await asyncio.wait_for(
                        websocket.receive(),
                        timeout=0.5,
                    )
                except TimeoutError:
                    continue
                if event["type"] == "websocket.disconnect":
                    return
        except WebSocketDisconnect:
            return

    @app.get("/api/v1/nocobase/applications")
    def list_applications(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> object:
        result = query_service.list_applications(page=page, page_size=page_size)
        return jsonable_encoder(asdict(result))

    @app.get("/api/v1/nocobase/applications/{application_id}")
    def get_application(application_id: int) -> object:
        result = query_service.get_application(application_id)
        return jsonable_encoder(asdict(result))

    @app.post("/api/v1/rights/import")
    async def import_rights_excel(
        file: UploadFile = File(...),
    ) -> dict[str, object]:
        filename = file.filename or ""
        content = await file.read(RightsWebService.MAX_UPLOAD_BYTES + 1)
        return rights_service.import_excel(filename, content)

    @app.post("/api/v1/rights/erp-extraction", response_model=TaskResponse)
    def extract_erp_rights_application(
        request: ErpRightsExtractionRequest,
    ) -> TaskResponse:
        if not request.transaction_type.strip():
            raise ValueError("请选择 ERP 事务类型")
        if not 1 <= request.page_size <= 200:
            raise ValueError("每页查询数量必须在 1–200 之间")
        snapshot = rights_service.submit_erp_extraction(
            account_id=request.account_id,
            transaction_type=request.transaction_type,
            statuses=tuple(request.statuses),
            application_code=request.application_code,
            start_date=request.start_date,
            end_date=request.end_date,
            page_size=request.page_size,
            reasoning_mode=request.reasoning_mode,
        )
        return TaskResponse.from_snapshot(snapshot)

    @app.get("/api/v1/rights/imports/{import_id}/records/{row_number}")
    def get_rights_import_record(
        import_id: str,
        row_number: int,
    ) -> dict[str, object]:
        return rights_service.erp_record_detail(import_id, row_number)

    @app.put("/api/v1/rights/imports/{import_id}/records/{row_number}")
    def update_rights_import_record(
        import_id: str,
        row_number: int,
        request: RightsManualRecordRequest,
    ) -> dict[str, object]:
        return rights_service.update_erp_record(
            import_id,
            row_number,
            request.model_dump(),
        )

    @app.post("/api/v1/rights/imports/{import_id}/records")
    def add_rights_import_record(
        import_id: str,
        request: RightsManualRecordRequest,
    ) -> dict[str, object]:
        return rights_service.add_erp_record(import_id, request.model_dump())

    @app.post(
        "/api/v1/rights/imports/{import_id}/records/{row_number}/candidate"
    )
    def select_rights_import_candidate(
        import_id: str,
        row_number: int,
        request: RightsCandidateSelectionRequest,
    ) -> dict[str, object]:
        return rights_service.select_erp_candidate(
            import_id,
            row_number,
            request.candidate_id,
        )

    @app.post("/api/v1/rights/imports/{import_id}/print-group")
    def resolve_rights_print_group(
        import_id: str,
        request: RightsPrintGroupResolutionRequest,
    ) -> dict[str, object]:
        return rights_service.resolve_erp_print_group(
            import_id,
            request.task_number,
            request.group_id,
            request.mode,
        )

    @app.post("/api/v1/rights/imports/{import_id}/print-group/conditions")
    def resolve_rights_print_group_conditions(
        import_id: str,
        request: RightsPrintGroupConditionsRequest,
    ) -> dict[str, object]:
        return rights_service.resolve_erp_print_group_conditions(
            import_id,
            task_number=request.task_number,
            group_id=request.group_id,
            insurance_type=request.insurance_type,
            start_month=request.start_month,
            end_month=request.end_month,
            overwrite=request.overwrite,
        )

    @app.get("/api/v1/rights/template", response_model=None)
    def download_rights_template() -> FileResponse:
        template = runtime_root / "templates" / "单位权益单人员导入模板.xlsx"
        RightsStatementTemplateService().write(template)
        return FileResponse(template, filename=template.name)

    @app.post("/api/v1/rights/tasks", response_model=TaskResponse)
    def start_rights_task(request: RightsTaskRequest) -> TaskResponse:
        try:
            mode = ExportMode(request.export_mode)
        except ValueError as exc:
            raise ValueError("导出方式无效") from exc
        if request.batch_size < 1:
            raise ValueError("单批人数必须大于 0")
        snapshot = rights_service.submit_import(
            import_id=request.import_id,
            account_id=request.account_id,
            mode=mode,
            batch_size=request.batch_size,
            upload_to_erp=request.upload_to_erp,
        )
        return TaskResponse.from_snapshot(snapshot)

    @app.post(
        "/api/v1/nocobase/applications/{application_id}/print",
        response_model=TaskResponse,
    )
    def print_nocobase_application(
        application_id: int,
        request: NocoBasePrintRequest,
    ) -> TaskResponse:
        detail = query_service.get_application(application_id)
        snapshot = rights_service.submit_nocobase_application(
            detail,
            account_id=request.account_id,
            upload_to_erp=request.upload_to_erp,
        )
        return TaskResponse.from_snapshot(snapshot)

    @app.get("/api/v1/artifacts/{token}", response_model=None)
    def download_artifact(token: str, preview: bool = False) -> FileResponse:
        path = artifact_registry.resolve(token)
        if path is None:
            raise HTTPException(status_code=404, detail="结果文件不存在或已失效")
        inline = preview and path.suffix.lower() == ".pdf"
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/pdf" if inline else None,
            content_disposition_type="inline" if inline else "attachment",
        )

    static_root = Path(__file__).with_name("static")
    assets_root = static_root / "assets"
    if assets_root.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_root), name="web-assets")

    @app.get(
        "/{full_path:path}",
        include_in_schema=False,
        response_model=None,
    )
    def web_client(full_path: str) -> FileResponse | JSONResponse:
        del full_path
        index = static_root / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={
                "message": "Web 前端尚未构建",
                "details": "请在 frontend 目录执行 npm install 和 npm run build",
            },
        )

    return app


def _task_list(coordinator: TaskCoordinator, *, limit: int) -> TaskListResponse:
    return TaskListResponse(
        revision=coordinator.revision,
        tasks=[
            TaskResponse.from_snapshot(snapshot)
            for snapshot in coordinator.list(limit=limit)
        ],
    )


def _mask_account(account: str) -> str:
    value = account.strip()
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(len(value) - 4, 4)}{value[-2:]}"


def _account_ready(
    system_type: SystemType,
    account: str,
    secondary_account: str,
    password: str,
) -> bool:
    if not account or not password:
        return False
    return system_type is not SystemType.JSHRSS or bool(secondary_account)


app = create_app()
