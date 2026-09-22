import { Tag } from 'antd'
import type { TaskStatus } from '../types'

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
}

export function taskStatusLabel(status: TaskStatus) {
  return statusMap[status].text
}

export function TaskStatusTag({ status }: { status: TaskStatus }) {
  const item = statusMap[status]
  return <Tag color={item.color}>{item.text}</Tag>
}
