// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '../api/queries'
import type { AccountEditDetail, AccountSummary, WebPreferences } from '../types'
import { SettingsPage } from './SettingsPage'

vi.mock('../api/queries', () => ({ api: {
  settings: vi.fn(), accounts: vi.fn(), accountDetail: vi.fn(),
  saveAccount: vi.fn(), testNocoBaseConnection: vi.fn(),
} }))

const saved: AccountSummary = {
  id: 8, system_type: 'NOCOBASE', display_name: '接口用户',
  masked_account: '******', is_default: true, ready: true, login_method: 'direct',
}
const detail: AccountEditDetail = {
  ...saved, account: '', secondary_account: '', password_saved: false,
  password_mask: '', api_key_saved: true, api_key_mask: '******',
}
const nativeGetComputedStyle = window.getComputedStyle.bind(window)

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })) })
  vi.mocked(api.settings).mockResolvedValue({ ai_model_options: [] } as unknown as WebPreferences)
  vi.mocked(api.accounts).mockResolvedValue([])
  vi.mocked(api.accountDetail).mockResolvedValue(detail)
  vi.mocked(api.saveAccount).mockResolvedValue(saved)
  vi.mocked(api.testNocoBaseConnection).mockResolvedValue({ message: '连接成功，查询权限正常' })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

async function openEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>)
  await waitFor(() => expect(document.querySelector('.ant-spin-spinning')).toBeNull())
  const row = (await screen.findByText('NocoBase API 密钥')).closest('tr')!
  fireEvent.click(within(row).getByRole('button', { name: /编辑/ }))
  await screen.findByText('编辑NocoBase API 密钥')
  return screen.getByLabelText('API 密钥') as HTMLInputElement
}

describe('NocoBase API 密钥设置', () => {
  it('仅显示名称和密钥，连接测试不保存，保存不发送账号密码', async () => {
    const input = await openEditor()
    expect(screen.queryByLabelText('登录账号')).toBeNull()
    expect(screen.queryByLabelText('密码')).toBeNull()
    fireEvent.change(input, { target: { value: 'new-api-key' } })
    fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: '数据接口' } })
    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
    await screen.findByText('连接成功，查询权限正常')
    expect(api.testNocoBaseConnection).toHaveBeenCalledWith({ account_id: undefined, api_key: 'new-api-key' })
    expect(api.saveAccount).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(api.saveAccount).toHaveBeenCalledWith('NOCOBASE', {
      account_id: undefined, api_key: 'new-api-key', display_name: '数据接口',
    }))
    await waitFor(() => expect((screen.queryByLabelText('API 密钥') as HTMLInputElement | null)?.value ?? '').toBe(''))
  })

  it('保存的密钥只回填掩码，测试和改名时保留服务端密钥', async () => {
    vi.mocked(api.accounts).mockResolvedValue([saved])
    await openEditor()
    await waitFor(() => expect((screen.getByLabelText('API 密钥') as HTMLInputElement).value).toBe('******'))
    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
    await screen.findByText('连接成功，查询权限正常')
    expect(api.testNocoBaseConnection).toHaveBeenCalledWith({ account_id: 8, api_key: '' })
    fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: '改名' } })
    await waitFor(() => expect(screen.queryByText('连接成功，查询权限正常')).toBeNull())
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(api.saveAccount).toHaveBeenCalledWith('NOCOBASE', {
      account_id: 8, api_key: '', display_name: '改名',
    }))
  })

  it('连接失败在编辑窗口明确提示，不会保存配置', async () => {
    vi.mocked(api.testNocoBaseConnection).mockRejectedValue(new Error('API 密钥无效，请更换密钥'))
    const input = await openEditor()
    fireEvent.change(input, { target: { value: 'bad-key' } })
    fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
    await screen.findByText('连接测试失败')
    expect(api.saveAccount).not.toHaveBeenCalled()
  })

  it('ERP 仍使用账号密码，不提交 API 密钥', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>)
    await waitFor(() => expect(document.querySelector('.ant-spin-spinning')).toBeNull())
    const row = screen.getByText('ERP 账号').closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: /编辑/ }))
    await screen.findByText('编辑ERP 账号')
    expect(screen.queryByLabelText('API 密钥')).toBeNull()
    fireEvent.change(screen.getByLabelText('登录账号'), { target: { value: 'erp-user' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'erp-password' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(api.saveAccount).toHaveBeenCalledWith('ERP', {
      account_id: undefined, account: 'erp-user', secondary_account: '', password: 'erp-password', display_name: '', login_method: 'direct',
    }))
  })
})
