export type TaskKind = 'jshrss_browser' | 'erp_browser' | 'api_query' | 'erp_write'
export type TaskStatus =
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface TaskRecord {
  task_id: string
  title: string
  operation: string
  kind: TaskKind
  status: TaskStatus
  resource_label: string
  queue_position: number
  message: string
  progress_current: number
  progress_total: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  result: unknown
  error: string
}

export interface TaskListResponse {
  revision: number
  tasks: TaskRecord[]
}

export interface AccountSummary {
  id: number
  system_type: 'JSHRSS' | 'NOCOBASE' | 'ERP'
  display_name: string
  masked_account: string
  is_default: boolean
  ready: boolean
}

export interface AccountEditDetail {
  id: number
  system_type: AccountSummary['system_type']
  display_name: string
  account: string
  secondary_account: string
  password_mask: string
  password_saved: boolean
}

export interface WebPreferences {
  output_path: string
  export_mode: 'individual' | 'batch'
  batch_size: number
  upload_to_erp: boolean
  open_output_folder: boolean
  ai_model_profile: string
  ai_reasoning_mode: string
  execution_speed: 'fast' | 'standard' | 'stable'
  no_result_confirm_seconds: number
  preview_download_delay_ms: number
  download_timeout_seconds: number
  ai_model_options: Array<{
    value: string
    label: string
    model: string
    reasoning_modes: string[]
    default_reasoning_mode: string
    native_context_length: number
    num_ctx: number
    num_predict: number
    request_timeout_seconds: number
    keep_alive: string
    source_url: string
  }>
  active_ai_model: string
  active_reasoning_mode: string
  runtime_path: string
  logs_path: string
  version: string
}

export interface RightsImportPreview {
  import_id: string
  filename: string
  record_count: number
  unique_person_count?: number
  group_count: number
  estimated_pdf_count?: number
  erp_upload_available?: boolean
  source?: 'excel' | 'erp'
  executable?: boolean
  records: Array<{
    row_number: number
    task_number: string
    unit: string
    department: string
    name: string
    identity_number: string
    insurance_type: string
    start_month: string
    end_month: string
    print_group?: string
    print_group_id?: string
    status?: 'success' | 'warning' | 'error'
    issue_count?: number
  }>
  issues?: RightsIssue[]
  applications?: ErpApplicationPreview[]
  print_groups?: RightsPrintGroup[]
}

export interface RightsPrintGroup {
  group_id: string
  group_sequence: number
  group_label: string
  task_number: string
  insurance_type: string
  start_month: string
  end_month: string
  print_mode: string
  print_mode_label: string
  people_count: number
  issue_count: number
  status: 'success' | 'warning' | 'error'
  people: Array<{
    row_number: number
    name: string
    identity_number: string
    unit: string
    department: string
  }>
}

export interface RightsIssue {
  issue_id: string
  level: 'error' | 'warning' | 'pending' | 'info'
  level_label: string
  task_number: string
  person_name: string
  code: string
  message: string
  details: string
  row_number: number
  group_id: string
  candidates?: RightsPersonCandidate[]
}

export interface RightsPersonCandidate {
  candidate_id: string
  employee_code: string
  name: string
  masked_identity: string
  department: string
  company: string
  status: string
}

export interface RightsRecordDetail {
  row_number: number
  task_number: string
  print_group: string
  unit: string
  department: string
  name: string
  identity_number: string
  insurance_type: string
  start_month: string
  end_month: string
}

export interface ErpApplicationPreview {
  sequence: number
  task_number: string
  title: string
  description: string
  status_label: string
  originator: string
  department: string
  parse_status: { code?: string; message?: string; details?: string }
  issue_count: number
}

export interface PolicyItem {
  situation: string
  behavior: string
  explanation: string
}

export interface PolicyResponse {
  mode: string
  server_instances: number
  items: PolicyItem[]
}

export interface RightsApplication {
  application_id: number
  code: string
  status: string
  title: string
  problem_type: string
  initiator_id: number | null
  initiator_name: string
  initiation_date: string | null
  estimate_time: number
  actual_time: number
  estimate_date: string | null
  actual_date: string | null
}

export interface RightsApplicationPage {
  records: RightsApplication[]
  meta: {
    count: number
    page: number
    page_size: number
    total_page: number
    allowed_actions: Record<string, number[]>
  }
}

export interface RelatedPerson {
  person_id: number
  status: string
  insurance_type: string
  start_month: string | null
  end_month: string | null
  identity_number: string
  department: string
  name: string
  company: string
  print_group: string
}

export interface RightsApplicationDetail {
  application_id: number
  code: string
  status: string
  title: string
  problem_type: string
  created_at: string | null
  initiation_date: string | null
  estimate_time: number
  actual_time: number
  estimate_date: string | null
  actual_date: string | null
  created_by_name: string
  initiator_name: string
  problem_description: string
  handling_method: string
  related_persons: RelatedPerson[]
  attachment_names: string[]
  allowed_actions: Record<string, number[]>
}
