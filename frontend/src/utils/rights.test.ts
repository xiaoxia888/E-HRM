import { describe, expect, it } from 'vitest'
import { estimateRightsOutputCount } from './rights'

describe('estimateRightsOutputCount', () => {
  it('遵循申请打印组时按原始打印组数量计算', () => {
    expect(estimateRightsOutputCount(1, 4, 'batch')).toBe(1)
  })

  it('强制每人单独一份时按人员记录数量计算', () => {
    expect(estimateRightsOutputCount(1, 4, 'individual')).toBe(4)
  })
})
