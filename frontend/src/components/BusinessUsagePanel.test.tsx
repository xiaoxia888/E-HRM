// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import { api } from '../api/queries'
import type { BusinessUsageStatistics } from '../types'
import { BusinessUsagePanel } from './BusinessUsagePanel'

vi.mock('../api/queries', () => ({ api: { businessUsage: vi.fn() } }))
const nativeGetComputedStyle = window.getComputedStyle.bind(window)
const dates = ['2026-10-11', '2026-10-12', '2026-10-13']
const stats: BusinessUsageStatistics = {
  today: '2026-10-13', start_date: dates[0], end_date: dates[2],
  timezone: 'Asia/Shanghai', generated_at: '2026-10-13T06:00:00Z',
  businesses: [
    { key: 'rights', label: '权益单', total_count: 42, today_count: 3, period_count: 7, first_used_date: '2026-10-01', daily: dates.map((date, index) => ({ date, count: [1, 3, 3][index] })) },
    { key: 'social', label: '社保业务', total_count: 12, today_count: 2, period_count: 4, first_used_date: '2026-10-02', daily: dates.map((date, index) => ({ date, count: [2, 0, 2][index] })) },
    { key: 'medical', label: '医保业务', total_count: 25, today_count: 4, period_count: 6, first_used_date: '2026-10-03', daily: dates.map((date, index) => ({ date, count: [1, 1, 4][index] })) },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })) })
  vi.mocked(api.businessUsage).mockResolvedValue(stats)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function openPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<ConfigProvider theme={{ token: { motion: false } }}><QueryClientProvider client={client}><BusinessUsagePanel /></QueryClientProvider></ConfigProvider>)
  return client
}

function metric(label: string, name: string) {
  return within(screen.getByRole('article', { name: `${label}使用统计` })).getByText(name).closest('div')?.querySelector('dd')?.textContent
}

describe('分别统计三类业务', () => {
  it('同时显示每类业务各自的累计、今日、期间次数及独立每日图表', async () => {
    openPanel()
    await screen.findByRole('article', { name: '权益单使用统计' })
    expect(screen.getAllByRole('article')).toHaveLength(3)
    for (const business of stats.businesses) {
      expect(metric(business.label, '累计')).toBe(`${business.total_count}次`)
      expect(metric(business.label, '今日')).toBe(`${business.today_count}次`)
      expect(metric(business.label, '所选期间')).toBe(`${business.period_count}次`)
      expect(screen.getByRole('group', { name: `${business.label}每日使用次数，单位为次` })).toBeTruthy()
    }
    fireEvent.focus(screen.getByLabelText('医保业务 2026-10-13，使用 4 次'))
    expect(within(screen.getByRole('tooltip')).getByText('2026/10/13')).toBeTruthy()
    expect(within(screen.getByRole('tooltip')).getByText('4 次')).toBeTruthy()
  })

  it('共用日期筛选和刷新，保留每类各自的累计及今日口径', async () => {
    openPanel()
    await screen.findByRole('article', { name: '权益单使用统计' })
    vi.mocked(api.businessUsage).mockResolvedValue({ ...stats, businesses: stats.businesses.map((business, index) => ({ ...business, period_count: [2, 1, 0][index] })) })
    fireEvent.click(screen.getByText('最近 7 天'))
    await waitFor(() => expect(api.businessUsage).toHaveBeenCalledWith({ days: 7 }))
    await waitFor(() => expect(metric('权益单', '所选期间')).toBe('2次'))
    expect(metric('社保业务', '所选期间')).toBe('1次')
    expect(metric('医保业务', '所选期间')).toBe('0次')
    for (const business of stats.businesses) {
      expect(metric(business.label, '累计')).toBe(`${business.total_count}次`)
      expect(metric(business.label, '今日')).toBe(`${business.today_count}次`)
    }
    fireEvent.click(screen.getByRole('button', { name: '刷新统计' }))
    await waitFor(() => expect(api.businessUsage).toHaveBeenCalledTimes(3))
  })

  it('每日明细点击后打开，按日期同时展示三类准确次数', async () => {
    openPanel()
    await screen.findByRole('article', { name: '权益单使用统计' })
    expect(screen.queryByRole('table')).toBeNull()
    fireEvent.click(screen.getByText('每日明细'))
    const dialog = await screen.findByRole('dialog')
    const row = within(dialog).getByRole('cell', { name: '2026/10/11' }).closest('tr') as HTMLElement
    expect(within(row).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['2026/10/11', '1 次', '2 次', '1 次'])
    expect(within(dialog).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['日期', '权益单', '社保业务', '医保业务'])
  })

  it('没有记录的类别仍显示零值并保留三类面板', async () => {
    vi.mocked(api.businessUsage).mockResolvedValue({ ...stats, businesses: stats.businesses.map((business) => ({ ...business, total_count: 0, today_count: 0, period_count: 0, first_used_date: null, daily: business.daily.map((item) => ({ ...item, count: 0 })) })) })
    openPanel()
    await screen.findAllByText('暂无使用')
    expect(screen.getAllByRole('article')).toHaveLength(3)
    for (const business of stats.businesses) expect(metric(business.label, '累计')).toBe('0次')
  })

  it('首次加载失败时显示错误，避免把未知统计当成零', async () => {
    vi.mocked(api.businessUsage).mockRejectedValue(new Error('统计服务不可用'))
    openPanel()
    await screen.findByText('统计服务不可用')
    expect(screen.queryByRole('article')).toBeNull()
    expect(screen.queryByText('暂无使用')).toBeNull()
    expect(screen.getByText('30 天')).toBeTruthy()
  })

  it('刷新失败时保留各类已有统计并显示提示', async () => {
    openPanel()
    await screen.findByRole('article', { name: '权益单使用统计' })
    vi.mocked(api.businessUsage).mockRejectedValue(new Error('刷新暂时失败'))
    fireEvent.click(screen.getByRole('button', { name: '刷新统计' }))
    await screen.findByText('统计更新失败，以下为上次读取的结果')
    for (const business of stats.businesses) expect(metric(business.label, '累计')).toBe(`${business.total_count}次`)
  })
})
