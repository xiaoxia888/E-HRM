// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import { api } from '../api/queries'
import type { ExecutionDetail, ExecutionSummary } from '../types'
import { ExecutionRecordsPage } from './ExecutionRecordsPage'

vi.mock('../api/queries', () => ({ api: { executions: vi.fn(), executionDetail: vi.fn() } }))
const getComputedStyle = window.getComputedStyle.bind(window)
const row: ExecutionSummary = { task_id: 'batch1', application_index: 0, source: 'erp', operation: 'rights_statement.acquire', operation_label: '获取社保权益单',
  transaction_type: '社保咨询', title: '办理申请甲', erp_code: 'ERP-001', application_code: 'NOCO-001', initiator: '发起人甲', initiated_at: '2026-10-20',
  account_label: '南化建社保账号', people_count: 1, created_at: '2026-10-26T01:00:00Z', finished_at: '2026-10-26T01:02:00Z', status: 'succeeded', outcome: 'succeeded', snapshot_origin: 'captured' }
const detail: ExecutionDetail = { account: { id: 10, display_name: '南化建社保账号', masked_account: 'te****01', login_method: 'government_sso' },
  application: { source: 'erp', transaction_type: '社保咨询', title: '办理申请甲', erp_code: 'ERP-001', application_code: 'NOCO-001',
    initiator: '发起人甲', initiated_at: '2026-10-20', problem_description: '问题描述甲\n第二行', handling_method: '处理方式甲', snapshot_origin: 'captured' },
  task: { task_id: 'batch1', title: '获取社保权益单', operation: 'rights_statement.acquire', status: 'succeeded', kind: 'jshrss_browser', resource_label: '南化建社保账号',
    created_at: row.created_at, started_at: row.created_at, finished_at: row.finished_at, progress_current: 1, progress_total: 1, queue_position: 0,
    message: '处理结束', error: '', result: { artifacts: [{ name: '甲.pdf', url: '/api/v1/artifacts/pdf1' }, { name: '乙.pdf', url: '/api/v1/artifacts/pdf2' }], archive: { name: '整批.zip', url: '/api/v1/artifacts/zip' } } },
  operation_label: '获取社保权益单', outcome: 'succeeded', people: [{ name: '申请人员甲', identity_number: '320101199001011234', row_number: '2', status: 'succeeded', message: '平台确认成功', file_name: '甲.pdf', phone: '13800000000' }] }

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => getComputedStyle(element))
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })) })
  vi.mocked(api.executions).mockResolvedValue({ records: [row, { ...row, application_index: 1, erp_code: 'ERP-002', title: '办理申请乙', outcome: 'failed' }], total: 2, page: 1, page_size: 20 })
  vi.mocked(api.executionDetail).mockResolvedValue(detail)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function openPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<ConfigProvider theme={{ token: { motion: false } }}><QueryClientProvider client={client}><ExecutionRecordsPage /></QueryClientProvider></ConfigProvider>)
}

describe('执行记录', () => {
  it('一批中不同申请各自列出完整业务信息和结果', async () => {
    openPage()
    await screen.findByText('ERP-001')
    expect(screen.getByText('ERP-002')).toBeTruthy()
    expect(screen.getAllByText('社保咨询')).toHaveLength(2)
    expect(screen.getAllByText('发起人甲')).toHaveLength(2)
    expect(screen.getAllByText('南化建社保账号')).toHaveLength(2)
    expect(screen.getByText('成功')).toBeTruthy()
    expect(screen.getByText('失败')).toBeTruthy()
    expect(api.executionDetail).not.toHaveBeenCalled()
    expect(screen.queryByText('申请人员甲')).toBeNull()
  })

  it('打开指定申请显示保存的问题、处理方式、人员、账号及本申请文件', async () => {
    openPage()
    fireEvent.click(await screen.findByText('办理申请甲'))
    await waitFor(() => expect(api.executionDetail).toHaveBeenCalledWith('batch1', 0))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('处理方式甲')
    expect(within(dialog).getByText(/问题描述甲/)).toBeTruthy()
    expect(within(dialog).getByText('ERP-001')).toBeTruthy()
    expect(within(dialog).getByText('NOCO-001')).toBeTruthy()
    expect(within(dialog).getByText('te****01')).toBeTruthy()
    expect(within(dialog).getByText('申请人员甲')).toBeTruthy()
    expect(within(dialog).getByText('320101199001011234')).toBeTruthy()
    expect(within(dialog).getByRole('link', { name: '甲.pdf' }).getAttribute('href')).toBe('/api/v1/artifacts/pdf1')
    expect(within(dialog).queryByRole('link', { name: '乙.pdf' })).toBeNull()
    expect(within(dialog).getByRole('link', { name: /下载整批结果/ })).toBeTruthy()
  })

  it('搜索在后端查询并重置页码，清空恢复所有记录', async () => {
    openPage()
    await screen.findByText('ERP-001')
    const search = screen.getByRole('searchbox', { name: '搜索执行记录' })
    fireEvent.change(search, { target: { value: 'ERP-002' } })
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', charCode: 13, keyCode: 13 })
    await waitFor(() => expect(api.executions).toHaveBeenCalledWith(expect.objectContaining({ keyword: 'ERP-002', page: 1 })))
    fireEvent.click(screen.getByRole('button', { name: '重置' }))
    await waitFor(() => expect((search as HTMLInputElement).value).toBe(''))
  })

  it('历史资料缺失明确提示，执行账号仍使用历史保存值', async () => {
    vi.mocked(api.executionDetail).mockResolvedValue({ ...detail, application: { ...detail.application, snapshot_origin: 'unavailable', problem_description: '', handling_method: '' } })
    openPage()
    fireEvent.click(await screen.findByText('办理申请甲'))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('该历史任务未保存完整申请详情，以下仅展示仍可追溯的信息。')
    expect(within(dialog).getByText('南化建社保账号')).toBeTruthy()
    expect(within(dialog).getAllByText('未提供')).toHaveLength(2)
  })

  it('切换分页向服务端查询对应页，筛选操作后返回第一页', async () => {
    vi.mocked(api.executions).mockResolvedValue({ records: [row], total: 45, page: 1, page_size: 20 })
    openPage()
    await screen.findByText('ERP-001')
    fireEvent.click(screen.getByTitle('2'))
    await waitFor(() => expect(api.executions).toHaveBeenCalledWith(expect.objectContaining({ page: 2, page_size: 20 })))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '执行操作' }))
    fireEvent.click(await screen.findByText('医保参保'))
    await waitFor(() => expect(api.executions).toHaveBeenCalledWith(expect.objectContaining({ page: 1, operation: 'application.medical_enrollment' })))
  })

  it('查询和详情失败分别显示错误与重试入口', async () => {
    vi.mocked(api.executions).mockRejectedValueOnce(new Error('历史记录不可用'))
    openPage()
    await screen.findByText('历史记录不可用')
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    await screen.findByText('办理申请甲')
    vi.mocked(api.executionDetail).mockRejectedValue(new Error('详情不可用'))
    fireEvent.click(screen.getByText('办理申请甲'))
    await screen.findByText('详情不可用')
  })
})
