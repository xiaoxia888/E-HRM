import type {
  ScheduledJob, ScheduledJobValues, ScheduledRun, ScheduledLog, PagedItems,
  AccountSummary,
  AccountEditDetail,
  GovernmentIdentitySummary,
  GovernmentIdentityDetail,
  PolicyResponse,
  RightsApplicationDetail,
  ApplicationOperationStates,
  RightsApplicationPage,
  TaskListResponse,
  TaskRecord,
  BusinessUsageStatistics,
  RightsImportPreview,
  RightsRecordDetail,
  WebPreferences,
} from '../types'
import { apiRequest } from './client'

export const api = {
  accounts: () => apiRequest<AccountSummary[]>('/api/v1/accounts'),
  governmentIdentities: () => apiRequest<GovernmentIdentitySummary[]>('/api/v1/government-identities'),
  governmentIdentityDetail: (id: number) => apiRequest<GovernmentIdentityDetail>(`/api/v1/government-identities/${id}`),
  saveGovernmentIdentity: (values: { identity_id?: number; account: string; password?: string; display_name?: string; social_enabled: boolean; medical_enabled: boolean }) =>
    apiRequest<GovernmentIdentitySummary>('/api/v1/government-identities', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
    }),
  bindGovernmentIdentity: (id: number, purpose: 'social' | 'medical') =>
    apiRequest<GovernmentIdentitySummary>(`/api/v1/government-identities/${id}/bind/${purpose}`, { method: 'POST' }),
  defaultGovernmentIdentity: (id: number, purpose: 'social' | 'medical') =>
    apiRequest<GovernmentIdentitySummary>(`/api/v1/government-identities/${id}/default/${purpose}`, { method: 'POST' }),
  accountDetail: (systemType: AccountSummary['system_type'], accountId: number) =>
    apiRequest<AccountEditDetail>(
      `/api/v1/settings/accounts/${systemType}?account_id=${accountId}`,
    ),
  policy: () => apiRequest<PolicyResponse>('/api/v1/concurrency-policy'),
  tasks: () => apiRequest<TaskListResponse>('/api/v1/tasks?limit=500'),
  businessUsage: (values: { days?: number; start_date?: string; end_date?: string }) => {
    const params = new URLSearchParams()
    if (values.days !== undefined) params.set('days', String(values.days))
    if (values.start_date) params.set('start_date', values.start_date)
    if (values.end_date) params.set('end_date', values.end_date)
    return apiRequest<BusinessUsageStatistics>(`/api/v1/dashboard/business-usage?${params}`)
  },
  task: (taskId: string) => apiRequest<TaskRecord>(`/api/v1/tasks/${taskId}`),
  cancelTask: (taskId: string) =>
    apiRequest<TaskRecord>(`/api/v1/tasks/${taskId}/cancel`, {
      method: 'POST',
    }),
  applications: (page: number, pageSize: number) =>
    apiRequest<RightsApplicationPage>(
      `/api/v1/nocobase/applications?page=${page}&page_size=${pageSize}`,
    ),
  applicationDetail: (applicationId: number) =>
    apiRequest<RightsApplicationDetail>(
      `/api/v1/nocobase/applications/${applicationId}`,
    ),
  applicationOperations: (applicationId: number) => apiRequest<ApplicationOperationStates>(
    `/api/v1/nocobase/applications/${applicationId}/operations`),
  applicationOperationLogs: (applicationId: number, runId: string) => apiRequest<Array<{ created_at: string; message: string }>>(
    `/api/v1/nocobase/applications/${applicationId}/operations/${runId}/logs`),
  terminateApplication: (applicationId: number, accountId: number) => apiRequest<TaskRecord>(
    `/api/v1/nocobase/applications/${applicationId}/termination`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, confirmed: true }),
    }),
  terminateMedicalApplication: (applicationId: number, accountId: number) => apiRequest<TaskRecord>(
    `/api/v1/nocobase/applications/${applicationId}/medical-termination`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, confirmed: true }),
    }),
  enrollMedicalApplication: (applicationId: number, accountId: number) => apiRequest<TaskRecord>(
    `/api/v1/nocobase/applications/${applicationId}/medical-enrollment`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, confirmed: true }),
    }),
  settings: () => apiRequest<WebPreferences>('/api/v1/settings'),
  savePreferences: (preferences: Omit<WebPreferences, 'ai_model_options' | 'active_ai_model' | 'active_reasoning_mode' | 'runtime_path' | 'logs_path' | 'version'>) =>
    apiRequest<{ message: string }>('/api/v1/settings/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(preferences),
    }),
  clearTemporaryFiles: () => apiRequest<{ message: string; removed: number }>('/api/v1/settings/maintenance/clear-temporary', {
    method: 'POST',
  }),
  saveAccount: (
    systemType: AccountSummary['system_type'],
    values: { account_id?: number; account?: string; secondary_account?: string; password?: string; api_key?: string; display_name?: string; login_method?: 'direct' | 'government_sso' },
  ) => apiRequest<AccountSummary>(`/api/v1/settings/accounts/${systemType}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  }),
  setDefaultMedicalAccount: (accountId: number) =>
    apiRequest<AccountSummary>(`/api/v1/settings/accounts/MEDICAL/${accountId}/default`, {
      method: 'POST',
    }),
  testNocoBaseConnection: (values: { account_id?: number; api_key?: string }) =>
    apiRequest<{ message: string }>('/api/v1/settings/nocobase/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    }),
  scheduledTasks: () => apiRequest<{ jobs: ScheduledJob[]; scheduler_running: boolean; timezone: string;
    task_types: { value: string; label: string }[] }>('/api/v1/scheduled-tasks'),
  saveScheduledTask: ({ id, values }: { id?: string; values: ScheduledJobValues }) =>
    apiRequest<ScheduledJob>(`/api/v1/scheduled-tasks${id ? `/${id}` : ''}`, {
      method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
    }),
  cronPreview: (cron: string) => apiRequest<{ timezone: string; times: string[] }>(
    `/api/v1/scheduled-tasks/cron-preview?cron=${encodeURIComponent(cron)}`),
  runScheduledTask: ({ id, ...values }: { id: string; start_date?: string; end_date?: string; dry_run?: boolean }) =>
    apiRequest<ScheduledRun>(`/api/v1/scheduled-tasks/${id}/run`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
    }),
  scheduledRuns: (jobId: string | undefined, page: number, pageSize: number) =>
    apiRequest<PagedItems<ScheduledRun>>(`/api/v1/scheduled-runs?page=${page}&page_size=${pageSize}${jobId ? `&job_id=${encodeURIComponent(jobId)}` : ''}`),
  scheduledRun: (id: string) => apiRequest<ScheduledRun>(`/api/v1/scheduled-runs/${id}`),
  scheduledLogs: (id: string, page: number, pageSize: number) =>
    apiRequest<PagedItems<ScheduledLog>>(`/api/v1/scheduled-runs/${id}/logs?page=${page}&page_size=${pageSize}`),
  syncErpToNocoBase: (values: { start_date?: string; end_date?: string; dry_run?: boolean }) =>
    apiRequest<TaskRecord>('/api/v1/nocobase/sync', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
    }),
  importRights: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiRequest<RightsImportPreview>('/api/v1/rights/import', {
      method: 'POST',
      body: form,
    })
  },
  extractErpRights: (values: {
    account_id: number
    transaction_type: string
    statuses: number[]
    application_code: string
    start_date: string
    end_date: string
    page_size: number
    reasoning_mode: string
  }) => apiRequest<TaskRecord>('/api/v1/rights/erp-extraction', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  }),
  rightsRecord: (importId: string, rowNumber: number) =>
    apiRequest<RightsRecordDetail>(
      `/api/v1/rights/imports/${importId}/records/${rowNumber}`,
    ),
  updateRightsRecord: (
    importId: string,
    rowNumber: number,
    values: Omit<RightsRecordDetail, 'row_number'>,
  ) => apiRequest<RightsImportPreview>(
    `/api/v1/rights/imports/${importId}/records/${rowNumber}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    },
  ),
  addRightsRecord: (
    importId: string,
    values: Omit<RightsRecordDetail, 'row_number'>,
  ) => apiRequest<RightsImportPreview>(
    `/api/v1/rights/imports/${importId}/records`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    },
  ),
  selectRightsCandidate: (
    importId: string,
    rowNumber: number,
    candidateId: string,
  ) => apiRequest<RightsImportPreview>(
    `/api/v1/rights/imports/${importId}/records/${rowNumber}/candidate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId }),
    },
  ),
  resolveRightsPrintGroup: (
    importId: string,
    taskNumber: string,
    groupId: string,
    mode: 'batch' | 'individual',
  ) => apiRequest<RightsImportPreview>(
    `/api/v1/rights/imports/${importId}/print-group`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_number: taskNumber, group_id: groupId, mode }),
    },
  ),
  resolveRightsPrintGroupConditions: (
    importId: string,
    values: {
      task_number: string
      group_id: string
      insurance_type: string
      start_month: string
      end_month: string
      overwrite: boolean
    },
  ) => apiRequest<RightsImportPreview>(
    `/api/v1/rights/imports/${importId}/print-group/conditions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    },
  ),
  startRightsTask: (values: {
    import_id: string
    account_id: number
    export_mode: 'individual' | 'batch'
    batch_size: number
    upload_to_erp: boolean
  }) => apiRequest<TaskRecord>('/api/v1/rights/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  }),
  printApplication: (applicationId: number, accountId: number, uploadToErp: boolean) =>
    apiRequest<TaskRecord>(`/api/v1/nocobase/applications/${applicationId}/print`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, upload_to_erp: uploadToErp }),
    }),
}
