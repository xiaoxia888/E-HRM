import { describe, expect, it } from 'vitest'
import type { TaskStatus } from '../types'
import { taskStatusLabel } from './TaskStatusTag'

describe('taskStatusLabel', () => {
  it.each<[TaskStatus, string]>([
    ['queued', '排队中'],
    ['running', '执行中'],
    ['cancelling', '正在停止'],
    ['succeeded', '已完成'],
    ['failed', '执行失败'],
    ['cancelled', '已停止'],
    ['interrupted', '已中断'],
  ])('将 %s 显示为友好中文状态', (status, expected) => {
    expect(taskStatusLabel(status)).toBe(expected)
  })

  it('历史权益单任务全部失败时不显示已完成', () => {
    expect(taskStatusLabel('succeeded', { succeeded: 0, failed: 4 })).toBe('执行失败')
  })

  it('权益单部分成功时显示部分成功', () => {
    expect(taskStatusLabel('succeeded', { succeeded: 1, failed: 3 })).toBe('部分成功')
  })
})
