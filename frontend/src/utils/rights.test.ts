import { describe, expect, it } from 'vitest'
import type { RightsPrintGroup } from '../types'
import { projectPrintGroups } from './rights'

const group: RightsPrintGroup = {
  group_id: 'G01',
  group_sequence: 1,
  group_label: '组1',
  task_number: 'RLSQ-001',
  insurance_type: '养老',
  start_month: '2025-01',
  end_month: '2025-06',
  print_mode: 'individual',
  print_mode_label: '单独打印',
  people_count: 2,
  issue_count: 0,
  status: 'success',
  people: [
    { row_number: 2, name: '张三', identity_number: '1', unit: '单位', department: '部门' },
    { row_number: 3, name: '李四', identity_number: '2', unit: '单位', department: '部门' },
  ],
}

describe('projectPrintGroups', () => {
  it('按打印组展示时保留模型逻辑分组', () => {
    expect(projectPrintGroups([group], 'batch')).toEqual([group])
  })

  it('每人单独一份时将组投影为逐人权益单', () => {
    const projected = projectPrintGroups([group], 'individual')
    expect(projected).toHaveLength(2)
    expect(projected.map((item) => item.people[0].name)).toEqual(['张三', '李四'])
    expect(projected.every((item) => item.people_count === 1)).toBe(true)
  })
})
