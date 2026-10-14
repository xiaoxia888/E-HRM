import type { TaskStatus } from '../types'

export interface RightsFailure {
  row_number: number
  stage: string
  message: string
}

export function rightsResultFailures(value: unknown): RightsFailure[] {
  if (!value || typeof value !== 'object') return []
  const items = (value as { items?: unknown }).items
  if (!Array.isArray(items)) return []
  const failures: RightsFailure[] = []
  for (const item of items) {
    if (!item || typeof item !== 'object' || typeof item.row_number !== 'number') continue
    if (item.success === false) {
      failures.push({
        row_number: item.row_number, stage: '获取权益单',
        message: typeof item.message === 'string' && item.message ? item.message : '权益单获取失败',
      })
    }
    if (item.erp_success === false) {
      failures.push({
        row_number: item.row_number, stage: 'ERP 上传',
        message: typeof item.erp_message === 'string' && item.erp_message ? item.erp_message : 'ERP 上传失败',
      })
    }
  }
  return failures
}

export function rightsResultOutcome(
  status: TaskStatus,
  value: unknown,
): 'success' | 'warning' | 'error' | undefined {
  if (!['succeeded', 'failed'].includes(status)) return undefined
  if (value && typeof value === 'object') {
    const result = value as Record<string, unknown>
    if (Number(result.failed ?? 0) > 0) {
      return Number(result.succeeded ?? 0) > 0 ? 'warning' : 'error'
    }
  }
  return status === 'failed' ? 'error' : 'success'
}

export function estimateRightsOutputCount(
  printGroupCount: number,
  recordCount: number,
  mode: 'individual' | 'batch',
): number {
  return mode === 'individual' ? recordCount : printGroupCount
}
