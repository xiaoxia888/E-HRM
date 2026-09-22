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
  ])('将 %s 显示为友好中文状态', (status, expected) => {
    expect(taskStatusLabel(status)).toBe(expected)
  })
})
