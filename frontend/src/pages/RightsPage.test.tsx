// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import type { TaskRecord } from '../types'
import { RightsTaskProgressModal } from './RightsPage'

const nativeGetComputedStyle = window.getComputedStyle.bind(window)
const platformError = '智慧人社业务接口请求失败\nstatus 400 reading GlobalBusinessManagerService#startBusiness(BusinessLog)\nappCode=-1'
const archive = { name: '结果.zip', url: '/api/v1/artifacts/zip' }
const workbook = { name: '执行结果.xlsx', url: '/api/v1/artifacts/excel' }
const pdf = { name: '权益单.pdf', url: '/api/v1/artifacts/pdf' }

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element))
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })) })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function openResult(status: TaskRecord['status'], succeeded: number, failed: number) {
  const onClose = vi.fn()
  const task = {
    task_id: 'print-task', status, message: '任务已完成，可以查看或下载处理结果',
    result: {
      succeeded, failed, archive, artifacts: succeeded ? [workbook, pdf] : [workbook],
      items: Array.from({ length: succeeded + failed }, (_, index) => ({
        row_number: index + 2, success: index < succeeded,
        code: index < succeeded ? 'SUCCESS' : 'RIGHTS_API_REQUEST_FAILED',
        message: index < succeeded ? '成功' : platformError,
      })),
    },
  } as TaskRecord
  render(<ConfigProvider theme={{ token: { motion: false } }}><RightsTaskProgressModal open task={task} loading={false} cancelling={false} onCancelTask={vi.fn()} onOpenTasks={vi.fn()} onClose={onClose} /></ConfigProvider>)
  return { onClose }
}

describe('权益单业务结果', () => {
  it.each(['succeeded', 'failed'] as const)('全部失败（任务状态 %s）显示失败及平台原文，仍能下载和关闭', (status) => {
    const { onClose } = openResult(status, 0, 2)
    expect(screen.getByRole('heading', { name: '权益单获取失败' })).toBeTruthy()
    expect(screen.queryByText('权益单获取完成')).toBeNull()
    expect(screen.getAllByText(/startBusiness\(BusinessLog\)/)).toHaveLength(2)
    expect(screen.getByText('成功 0 项，失败 2 项')).toBeTruthy()
    expect(document.querySelector('.rights-result-summary.has-error')).toBeTruthy()
    expect(screen.getByRole('link', { name: /下载全部结果/ }).getAttribute('href')).toBe(archive.url)
    expect(screen.getByRole('link', { name: /执行结果.xlsx/ }).getAttribute('href')).toBe(workbook.url)
    fireEvent.click(screen.getByRole('button', { name: /关\s*闭/ }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('部分成功显示警告和错误详情，同时保留成功 PDF 的预览', () => {
    openResult('succeeded', 1, 1)
    expect(screen.getByRole('heading', { name: '权益单部分获取成功' })).toBeTruthy()
    expect(document.querySelector('.rights-result-summary.has-warning')).toBeTruthy()
    expect(screen.getByText(/startBusiness\(BusinessLog\)/)).toBeTruthy()
    expect(screen.getByTitle('权益单 PDF 预览').getAttribute('src')).toContain(pdf.url)
    expect(screen.getByRole('link', { name: /下载当前 PDF/ })).toBeTruthy()
  })

  it('全部成功继续显示绿色完成和 PDF 预览', () => {
    openResult('succeeded', 2, 0)
    expect(screen.getByRole('heading', { name: '权益单获取完成' })).toBeTruthy()
    expect(document.querySelector('.erp-extraction-progress__icon.is-success')).toBeTruthy()
    expect(screen.getByTitle('权益单 PDF 预览')).toBeTruthy()
    expect(screen.queryByText('失败原因')).toBeNull()
  })

  it('没有逐行结果的异常也展示任务错误原文', () => {
    render(<RightsTaskProgressModal open task={{ task_id: 'failed-task', status: 'failed', error: platformError } as TaskRecord} loading={false} cancelling={false} onCancelTask={vi.fn()} onOpenTasks={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByRole('heading', { name: '权益单获取失败' })).toBeTruthy()
    expect(screen.getByText(/startBusiness\(BusinessLog\)/)).toBeTruthy()
  })
})
