import { Tag } from 'antd'
import type { TaskStatus } from '../types'
import { rightsResultOutcome } from '../utils/rights'

const statusMap: Record<
  TaskStatus,
  { color: string; text: string }
> = {
  queued: { color: 'gold', text: '排队中' },
  running: { color: 'processing', text: '执行中' },
  cancelling: { color: 'orange', text: '正在停止' },
  succeeded: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '执行失败' },
  cancelled: { color: 'default', text: '已停止' },
  interrupted: { color: 'default', text: '已中断' },
}

export function taskStatusLabel(status: TaskStatus, rightsResult?: unknown) {
  const outcome = rightsResultOutcome(status, rightsResult)
  if (outcome === 'warning') return '部分成功'
  if (outcome === 'error') return '执行失败'
  return statusMap[status].text
}

export function TaskStatusTag({ status, rightsResult }: { status: TaskStatus; rightsResult?: unknown }) {
  const item = statusMap[status]
  const outcome = rightsResultOutcome(status, rightsResult)
  const color = outcome === 'warning' ? 'warning' : outcome === 'error' ? 'error' : item.color
  return <Tag color={color}>{taskStatusLabel(status, rightsResult)}</Tag>
}
