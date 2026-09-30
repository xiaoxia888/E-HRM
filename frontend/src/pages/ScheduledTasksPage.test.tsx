// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '../api/queries'
import { ScheduledTasksPage } from './ScheduledTasksPage'
import type { ScheduledJob, ScheduledRun } from '../types'

vi.mock('../api/queries', () => ({ api: {
  scheduledTasks: vi.fn(), scheduledRuns: vi.fn(), scheduledRun: vi.fn(), scheduledLogs: vi.fn(),
  saveScheduledTask: vi.fn(), runScheduledTask: vi.fn(), cronPreview: vi.fn(), cancelTask: vi.fn(),
} }))

const job: ScheduledJob = { id: 'erp-nocobase-sync', name: 'ERP 原始同步', task_type: 'erp_nocobase_sync', cron: '0 * * * *', enabled: false, lookback_days: 2, timezone: 'Asia/Shanghai', next_run: null, notice: '' }
const run: ScheduledRun = { id: 'run-1', job_id: job.id, trigger_kind: 'manual', status: 'succeeded', task_id: 'task-1', created_at: '2026-09-29T02:00:00Z', started_at: '2026-09-29T02:00:01Z', finished_at: '2026-09-29T02:00:05Z', message: '完成', error: '', parameters: { start_date: '2026-09-28', end_date: '2026-09-29', dry_run: false }, result: { summary: { created: 1, failed: 0 } } }
const nativeGetComputedStyle = window.getComputedStyle.bind(window)
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })) })
  vi.mocked(api.scheduledTasks).mockResolvedValue({ jobs: [job], scheduler_running: true, timezone: job.timezone, task_types: [{ value: job.task_type, label: 'ERP → NocoBase 原始申请同步' }] })
  vi.mocked(api.scheduledRuns).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  vi.mocked(api.saveScheduledTask).mockResolvedValue(job)
  vi.mocked(api.cronPreview).mockResolvedValue({ timezone: job.timezone, times: ['2026-09-30T08:00:00+08:00'] })
  vi.mocked(api.runScheduledTask).mockResolvedValue({ ...run, trigger_kind: 'preview', status: 'skipped', message: '同类任务正在执行，已跳过' })
  vi.mocked(api.scheduledRun).mockResolvedValue(run)
  vi.mocked(api.scheduledLogs).mockResolvedValue({ items: [{ id: 1, created_at: run.created_at, level: 'info', message: '步骤一：获取原始申请' }], total: 1, page: 1, page_size: 50 })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

function openPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><ScheduledTasksPage /></QueryClientProvider>)
}

describe('定时任务工作台', () => {
  it('独立页面编辑 cron，预览时间不触发同步，保存不发送额外字段', async () => {
    openPage()
    const row = (await screen.findByText(job.name)).closest('tr')!
    expect(within(row).getByRole('switch').getAttribute('aria-checked')).toBe('false')
    fireEvent.click(within(row).getByRole('button', { name: /编辑/ }))
    const input = await screen.findByLabelText('Cron 表达式')
    await waitFor(() => expect((input as HTMLInputElement).value).toBe(job.cron))
    fireEvent.change(input, { target: { value: '0 8 * * mon' } })
    fireEvent.click(screen.getByRole('button', { name: '预览后 5 次触发' }))
    await waitFor(() => expect(vi.mocked(api.cronPreview).mock.calls[0]?.[0]).toBe('0 8 * * mon'))
    await screen.findByText('2026-09-30 08:00:00')
    expect(api.runScheduledTask).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(vi.mocked(api.saveScheduledTask).mock.calls[0]?.[0]).toEqual({ id: job.id, values: { name: job.name, task_type: job.task_type, cron: '0 8 * * mon', enabled: false, lookback_days: 2 } }))
  })

  it('关闭的计划也能手动预览，重复触发提示跳过，日志按执行记录获取', async () => {
    openPage()
    const row = (await screen.findByText(job.name)).closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: /执行一次/ }))
    fireEvent.click(await screen.findByRole('button', { name: '只读预览' }))
    await waitFor(() => expect(vi.mocked(api.runScheduledTask).mock.calls[0]?.[0]).toEqual({ id: job.id, start_date: '', end_date: '', dry_run: true }))
    await screen.findByText('同类任务正在执行，已跳过')
    await screen.findByText('步骤一：获取原始申请')
    expect(vi.mocked(api.scheduledLogs).mock.calls[0]).toEqual([run.id, 1, 50])
    expect(api.saveScheduledTask).not.toHaveBeenCalled()
  })

  it('历史记录采用服务端分页，失败说明和日志可查询', async () => {
    vi.mocked(api.scheduledRuns).mockResolvedValue({ items: [run], total: 25, page: 1, page_size: 20 })
    openPage()
    await screen.findByText('共 25 条')
    const card = screen.getByText('执行记录', { selector: '.ant-card-head-title' }).closest('.ant-card')!
    const next = card.querySelector('.ant-pagination-next')!
    fireEvent.click(next)
    await waitFor(() => expect(vi.mocked(api.scheduledRuns).mock.calls.some((args) => args[1] === 2)).toBe(true))
    fireEvent.click(await within(card as HTMLElement).findByRole('button', { name: '查看日志' }))
    await screen.findByText('执行详情与步骤日志')
    await screen.findByText('步骤一：获取原始申请')
  })
})
