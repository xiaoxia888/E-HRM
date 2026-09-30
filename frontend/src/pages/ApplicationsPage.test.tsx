// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { api } from '../api/queries'
import { ApplicationsPage } from './ApplicationsPage'
import type { RightsApplicationDetail, TaskRecord } from '../types'

vi.mock('../api/queries', () => ({ api: {
  applications: vi.fn(), applicationDetail: vi.fn(), accounts: vi.fn(), settings: vi.fn(),
  applicationOperations: vi.fn(), applicationOperationLogs: vi.fn(), terminateApplication: vi.fn(),
  printApplication: vi.fn(), task: vi.fn(), cancelTask: vi.fn(),
} }))
const nativeGetComputedStyle = window.getComputedStyle.bind(window)
const detail = {
  application_id: 1, code: 'TEST-001', title: '测试申请', status: 'NEW', problem_type: 'social_security_termination',
  related_persons: [], termination_person: [{ id: 2, user_name: '测试人员', id_card_no: '320101199001011234', termination_reason: '双方协商一致解除', operation_key: 'key1' }],
  insurance_person: [{ id: 3, user_name: '参保人员', id_card_no: '320101199002021235', operation_key: 'key2', contract_type: '固定期限' }],
} as unknown as RightsApplicationDetail
const task = { task_id: 'task1', status: 'running', operation: 'application.termination:run1', message: '正在填入退保表单', progress_current: 0, progress_total: 1 } as TaskRecord
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })) })
  vi.mocked(api.applications).mockResolvedValue({ records: [detail], meta: { count: 1, page: 1, page_size: 20, total_page: 1 } } as never)
  vi.mocked(api.applicationDetail).mockResolvedValue(detail)
  vi.mocked(api.accounts).mockResolvedValue([{ id: 10, display_name: '八化建', masked_account: 'zw***z7', system_type: 'JSHRSS', ready: true, is_default: true, login_method: 'government_sso' }])
  vi.mocked(api.settings).mockResolvedValue({ upload_to_erp: false } as never)
  vi.mocked(api.applicationOperations).mockResolvedValue({ people: [], runs: [] })
  vi.mocked(api.applicationOperationLogs).mockResolvedValue([{ created_at: '2026-09-29T02:00:00Z', message: '日志：正在进入单位办理' }])
  vi.mocked(api.terminateApplication).mockResolvedValue(task)
  vi.mocked(api.task).mockResolvedValue(task)
  vi.mocked(api.printApplication).mockResolvedValue({ ...task, operation: 'rights_statement.acquire' })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
async function openPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<ConfigProvider theme={{ token: { motion: false } }}><QueryClientProvider client={client}><MemoryRouter><ApplicationsPage /></MemoryRouter></QueryClientProvider></ConfigProvider>)
  fireEvent.click(await screen.findByText('TEST-001'))
  await screen.findByText('问题描述')
  await screen.findByText('八化建 · zw***z7 · 政务服务平台')
}
async function dialog(title: string) {
  // rc-util uses the same "test-id" for Drawer/Modal under NODE_ENV=test;
  // anchor on the title to avoid their test-only aria-labelledby collision.
  return (await screen.findByText(title)).closest('[role="dialog"]') as HTMLElement
}

describe('权益申请分类执行', () => {
  it('退保先确认账号，取消不执行，确认后展示进度和日志', async () => {
    await openPage()
    expect(screen.queryByRole('button', { name: '基础信息采集' })).toBeNull()
    expect(screen.queryByRole('button', { name: '打印社保权益单' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /退\s*保/ }))
    const confirmation = await dialog('确认执行账号')
    expect(within(confirmation).getByText(/八化建/)).toBeTruthy()
    expect(within(confirmation).getByText('江苏政务服务平台')).toBeTruthy()
    expect(api.terminateApplication).not.toHaveBeenCalled()
    fireEvent.click(within(confirmation).getByRole('button', { name: /取\s*消/ }))
    await waitFor(() => expect(screen.queryByText('确认执行账号')).toBeNull())
    expect(api.terminateApplication).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /退\s*保/ }))
    fireEvent.click(screen.getByRole('button', { name: '确认执行' }))
    await waitFor(() => expect(api.terminateApplication).toHaveBeenCalledWith(1, 10))
    await dialog('退保执行进度')
    await screen.findByText('正在填入退保表单')
    await screen.findByText(/日志：正在进入单位办理/)
  })

  it('参保显示两个预留按钮，不提交、不标记成功', async () => {
    vi.mocked(api.applicationDetail).mockResolvedValue({ ...detail, problem_type: 'social_security_enrollment' })
    await openPage()
    expect(screen.queryByRole('button', { name: /退\s*保/ })).toBeNull()
    await screen.findByText('参保人员')
    for (const label of ['基础信息采集', '参保登记']) {
      fireEvent.click(screen.getByRole('button', { name: label }))
      const modal = await dialog('确认执行账号')
      fireEvent.click(within(modal).getByRole('button', { name: '确认执行' }))
      await waitFor(() => expect(screen.queryByText('确认执行账号')).toBeNull())
    }
    expect(api.terminateApplication).not.toHaveBeenCalled()
    expect(api.printApplication).not.toHaveBeenCalled()
    expect(screen.queryByText('已办理')).toBeNull()
  })

  it.each(['succeeded', 'unknown'])('状态 %s 显示状态并禁止重复点击', async (status) => {
    vi.mocked(api.applicationOperations).mockResolvedValue({ people: [{ person_key: 'key1', name: '测试人员', operation: 'termination', status, message: '请查看结果', updated_at: '', task_id: 'old', account_label: '八化建' }], runs: [] })
    await openPage()
    await screen.findByText(status === 'succeeded' ? '已办理' : '结果待确认')
    expect((screen.getByRole('button', { name: /退\s*保/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('权益单打印也必须先确认账号', async () => {
    vi.mocked(api.applicationDetail).mockResolvedValue({ ...detail, problem_type: 'social_security_rights', related_persons: [{ person_id: 5, name: '打印人员' } as never] })
    await openPage()
    fireEvent.click(screen.getByRole('button', { name: '打印社保权益单' }))
    const modal = await dialog('确认执行账号')
    expect(api.printApplication).not.toHaveBeenCalled()
    fireEvent.click(within(modal).getByRole('button', { name: '确认执行' }))
    await waitFor(() => expect(api.printApplication).toHaveBeenCalledWith(1, 10, false))
    await screen.findByText('正在获取权益单')
  })

  it('处理中申请禁止重复执行，重新打开仍能查看进度', async () => {
    vi.mocked(api.applicationOperations).mockResolvedValue({ people: [], runs: [{ id: 'run1', operation: 'termination', active: 1, task_id: 'task1', account_label: '八化建' }] })
    await openPage()
    expect((screen.getByRole('button', { name: /退\s*保/ }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(await screen.findByRole('button', { name: '查看进度' }))
    await dialog('退保执行进度')
    await screen.findByText('正在填入退保表单')
    expect(api.terminateApplication).not.toHaveBeenCalled()
  })

  it('退工原因显示中文枚举，账号和按钮位于底部操作栏', async () => {
    vi.mocked(api.applicationDetail).mockResolvedValue({ ...detail, termination_person: [{ ...detail.termination_person![0], termination_reason: '6304', termination_reason_label: '双方协商一致解除' }] })
    await openPage()
    await screen.findByText('双方协商一致解除')
    expect(screen.queryByText('6304')).toBeNull()
    const button = screen.getByRole('button', { name: /退\s*保/ })
    const footer = button.closest('.ant-drawer-footer') as HTMLElement
    expect(footer).toBeTruthy()
    expect(within(footer).getByRole('combobox', { name: '执行账号' })).toBeTruthy()
    expect(document.querySelector('.ant-drawer-header')?.querySelector('.application-detail-actions')).toBeNull()
    expect(api.terminateApplication).not.toHaveBeenCalled()
  })

  it('处理结束展示结果待确认，不冒充全部办理成功', async () => {
    vi.mocked(api.task).mockResolvedValue({ ...task, status: 'succeeded', result: { submitted_count: 0, unknown_count: 1, total: 1 } })
    await openPage()
    fireEvent.click(screen.getByRole('button', { name: /退\s*保/ }))
    fireEvent.click(within(await dialog('确认执行账号')).getByRole('button', { name: '确认执行' }))
    await dialog('退保执行结果')
    await screen.findByText(/提交成功 0 人，结果待确认 1 人/)
  })
})
