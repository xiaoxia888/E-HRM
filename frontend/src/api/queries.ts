import type {
  AccountSummary,
  AccountEditDetail,
  PolicyResponse,
  RightsApplicationDetail,
  RightsApplicationPage,
  TaskListResponse,
  TaskRecord,
  RightsImportPreview,
  WebPreferences,
} from '../types'
import { apiRequest } from './client'

export const api = {
  accounts: () => apiRequest<AccountSummary[]>('/api/v1/accounts'),
  accountDetail: (systemType: AccountSummary['system_type'], accountId: number) =>
    apiRequest<AccountEditDetail>(
      `/api/v1/settings/accounts/${systemType}?account_id=${accountId}`,
    ),
  policy: () => apiRequest<PolicyResponse>('/api/v1/concurrency-policy'),
  tasks: () => apiRequest<TaskListResponse>('/api/v1/tasks'),
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
    values: { account_id?: number; account: string; secondary_account?: string; password?: string; display_name?: string },
  ) => apiRequest<AccountSummary>(`/api/v1/settings/accounts/${systemType}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
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
