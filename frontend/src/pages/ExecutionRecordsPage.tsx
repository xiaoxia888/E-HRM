import { useState } from 'react'
import { Alert, Button, Card, DatePicker, Descriptions, Drawer, Empty, Input, Select, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import { PageTitle } from '../components/PageTitle'
import { TaskStatusTag } from '../components/TaskStatusTag'
import type { ExecutionDetail, ExecutionOutcome, ExecutionPerson, ExecutionSummary } from '../types'

const operations = [
  ['rights_statement.acquire', '获取社保权益单'], ['erp.rights.upload', '上传权益单至 ERP'],
  ['application.termination', '社保退工停保'], ['application.information_collection', '社保基础信息采集'],
  ['application.enrollment', '社保参保登记'], ['application.medical_termination', '医保停保'], ['application.medical_enrollment', '医保参保'],
]
const outcomes: Record<ExecutionOutcome, { text: string; color: string }> = {
  queued: { text: '排队中', color: 'gold' }, running: { text: '执行中', color: 'processing' },
  cancelling: { text: '正在停止', color: 'orange' }, succeeded: { text: '成功', color: 'success' },
  partial: { text: '部分成功', color: 'warning' }, failed: { text: '失败', color: 'error' },
  unknown: { text: '结果待确认', color: 'orange' }, existing: { text: '平台已采集', color: 'cyan' },
  cancelled: { text: '已停止', color: 'default' }, interrupted: { text: '已中断', color: 'default' },
}
const sources: Record<string, string> = { erp: 'ERP', nocobase: '权益申请', excel: 'Excel 导入', legacy: '历史任务' }
const personLabels: Record<string, string> = {
  phone: '电话', company: '单位', department: '部门', insurance_type: '险种', start_month: '开始月份', end_month: '结束月份',
  termination_reason: '退工原因', household_type: '户籍性质', ethnicity: '民族', job_type: '岗位工种', contract_type: '合同类别',
  contract_start_date: '合同开始日期', contract_end_date: '合同结束日期', contract_add_reason: '合同增加原因',
  insurance_identity: '参保身份', monthly_contribution_salary: '月缴费工资', is_technology: '是否管理技术岗',
  med_ins_stop_reason: '医保停保原因', med_stop_date: '医保停保日期', med_ins_stop_month_fee: '当月是否缴费', arrive_unit_time: '到单位时间',
  cert_valid_from: '证件有效期起始日期', cert_valid_to: '证件有效期截止日期', household_address: '户籍地行政区划', print_group: '申请打印组',
}
function dateText(value: string | null | undefined, time = false) {
  return value && dayjs(value).isValid() ? dayjs(value).format(time ? 'YYYY-MM-DD HH:mm:ss' : 'YYYY-MM-DD') : value || '-'
}
function OutcomeTag({ outcome }: { outcome: ExecutionOutcome }) {
  const value = outcomes[outcome]
  return <Tag color={value?.color}>{value?.text ?? outcome}</Tag>
}

export function ExecutionRecordsPage() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [operation, setOperation] = useState<string>()
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [selected, setSelected] = useState<{ task_id: string; application_index: number } | null>(null)
  const filters = { page, page_size: pageSize, keyword, operation, start_date: range?.[0].format('YYYY-MM-DD'), end_date: range?.[1].format('YYYY-MM-DD') }
  const records = useQuery({ queryKey: ['executions', filters], queryFn: () => api.executions(filters), refetchInterval: 10_000 })
  const detail = useQuery({
    queryKey: ['execution-detail', selected?.task_id, selected?.application_index],
    queryFn: () => api.executionDetail(selected!.task_id, selected!.application_index), enabled: selected !== null,
    refetchOnMount: 'always',
    refetchInterval: (query) => query.state.data && ['queued', 'running', 'cancelling'].includes(query.state.data.task.status) ? 1000 : false,
  })
  const reset = () => { setKeywordInput(''); setKeyword(''); setOperation(undefined); setRange(null); setPage(1) }

  return <div className="page-stack">
    <PageTitle title="执行记录" description="按申请查看执行结果，追溯申请内容、人员与执行账号" extra={<Button icon={<ReloadOutlined />} loading={records.isFetching} onClick={() => void records.refetch()}>刷新</Button>} />
    <Card className="content-card">
      <div className="execution-filters">
        <Input.Search aria-label="搜索执行记录" placeholder="标题、ERP 编号、发起人、账号" allowClear value={keywordInput} onChange={(event) => { setKeywordInput(event.target.value); if (!event.target.value) { setKeyword(''); setPage(1) } }} onSearch={(value) => { setKeyword(value.trim()); setPage(1) }} />
        <Select aria-label="执行操作" placeholder="全部执行操作" allowClear value={operation} options={operations.map(([value, label]) => ({ value, label }))} onChange={(value) => { setOperation(value); setPage(1) }} />
        <DatePicker.RangePicker value={range} placeholder={['执行开始日期', '执行结束日期']} onChange={(values) => { setRange(values?.[0] && values[1] ? [values[0], values[1]] : null); setPage(1) }} />
        <Button type="link" onClick={reset}>重置</Button>
      </div>
      {records.isError && <Alert showIcon type="error" title="执行记录加载失败" description={errorMessage(records.error)} action={<Button onClick={() => void records.refetch()}>重试</Button>} />}
      <Table<ExecutionSummary> rowKey={(row) => `${row.task_id}:${row.application_index}`} loading={records.isLoading} dataSource={records.data?.records ?? []}
        locale={{ emptyText: <Empty description={keyword || operation || range ? '没有符合筛选条件的执行记录' : '暂无业务执行记录'} /> }}
        scroll={{ x: 1830 }} onRow={(row) => ({ onClick: () => setSelected({ task_id: row.task_id, application_index: row.application_index }) })}
        pagination={{ current: page, pageSize, total: records.data?.total ?? 0, showSizeChanger: true, showTotal: (total) => `共 ${total} 条执行记录`, onChange: (next, size) => { setPage(size !== pageSize ? 1 : next); setPageSize(size) } }}
        columns={[
          { title: '执行操作', dataIndex: 'operation_label', width: 160 },
          { title: '事务类型', dataIndex: 'transaction_type', width: 160, render: (value) => value || '-' },
          { title: '标题', dataIndex: 'title', width: 240, ellipsis: { showTitle: true } },
          { title: 'ERP 编号', dataIndex: 'erp_code', width: 190, render: (value) => value || '-' },
          { title: '发起人', dataIndex: 'initiator', width: 110, render: (value) => value || '-' },
          { title: '发起日期', dataIndex: 'initiated_at', width: 130, render: (value) => dateText(value) },
          { title: '执行账号', dataIndex: 'account_label', width: 170 },
          { title: '执行结果', dataIndex: 'outcome', width: 120, render: (value) => <OutcomeTag outcome={value} /> },
          { title: '申请人员', dataIndex: 'people_count', width: 100, render: (value, record) => record.snapshot_origin === 'unavailable' && !value ? '未保留' : `${value} 人` },
          { title: '执行时间', dataIndex: 'created_at', width: 180, render: (value) => dateText(value, true) },
          { title: '操作', key: 'detail', width: 90, fixed: 'right', render: () => <Button type="link">查看详情</Button> },
        ]} />
    </Card>
    <Drawer title="执行记录详情" size="large" styles={{ wrapper: { width: 'min(1080px, 96vw)' } }} open={selected !== null} onClose={() => setSelected(null)} destroyOnHidden>
      {detail.isLoading ? <Skeleton active /> : detail.isError ? <Alert showIcon type="error" title="执行详情加载失败" description={errorMessage(detail.error)} action={<Button onClick={() => void detail.refetch()}>重试</Button>} /> : detail.data ? <ExecutionContent detail={detail.data} /> : null}
    </Drawer>
  </div>
}

function ExecutionContent({ detail }: { detail: ExecutionDetail }) {
  const { application: app, account, task, people } = detail
  const result = task.result && typeof task.result === 'object' ? task.result as Record<string, unknown> : {}
  const artifacts = Array.isArray(result.artifacts) ? result.artifacts.filter((value): value is { name: string; url: string } => Boolean(value && typeof value === 'object' && typeof value.name === 'string' && typeof value.url === 'string')) : []
  const archive = result.archive as { name?: string; url?: string } | undefined
  const pdfNames = new Set(people.map((person) => person.file_name).filter(Boolean))
  const files = artifacts.filter((file) => !file.name.toLowerCase().endsWith('.pdf') || pdfNames.has(file.name))
  return <Space orientation="vertical" size={20} className="execution-detail-content">
    {app.snapshot_origin !== 'captured' && <Alert showIcon type="info" title={app.snapshot_origin === 'recovered' ? '该历史记录由本地保留的执行文件还原，缺失的信息以“—”展示。' : '该历史任务未保存完整申请详情，以下仅展示仍可追溯的信息。'} />}
    <Descriptions title="申请信息" bordered size="small" column={2}>
      <Descriptions.Item label="事务类型">{app.transaction_type || '-'}</Descriptions.Item>
      <Descriptions.Item label="信息来源">{sources[app.source] ?? app.source}</Descriptions.Item>
      <Descriptions.Item label="标题" span={2}>{app.title || '-'}</Descriptions.Item>
      <Descriptions.Item label="ERP 编号">{app.erp_code ? <Typography.Text copyable>{app.erp_code}</Typography.Text> : '-'}</Descriptions.Item>
      <Descriptions.Item label="申请编号">{app.application_code || '-'}</Descriptions.Item>
      <Descriptions.Item label="发起人">{app.initiator || '-'}</Descriptions.Item>
      <Descriptions.Item label="发起日期">{dateText(app.initiated_at)}</Descriptions.Item>
      <Descriptions.Item label="所属部门" span={2}>{app.department || '-'}</Descriptions.Item>
      <Descriptions.Item label="问题描述" span={2}><div className="execution-long-text">{app.problem_description || '未提供'}</div></Descriptions.Item>
      <Descriptions.Item label="处理方式" span={2}><div className="execution-long-text">{app.handling_method || '未提供'}</div></Descriptions.Item>
    </Descriptions>
    <Descriptions title="执行情况" bordered size="small" column={2}>
      <Descriptions.Item label="执行操作">{detail.operation_label}</Descriptions.Item>
      <Descriptions.Item label="本申请结果"><OutcomeTag outcome={detail.outcome} /></Descriptions.Item>
      <Descriptions.Item label="执行账号">{account.display_name || task.resource_label}</Descriptions.Item>
      <Descriptions.Item label="登录账号">{account.masked_account || '历史记录未保存'}</Descriptions.Item>
      <Descriptions.Item label="执行时间">{dateText(task.created_at, true)}</Descriptions.Item>
      <Descriptions.Item label="完成时间">{dateText(task.finished_at, true)}</Descriptions.Item>
      <Descriptions.Item label="整批任务状态"><TaskStatusTag status={task.status} /></Descriptions.Item>
      <Descriptions.Item label="登录方式">{account.login_method === 'government_sso' ? '政务服务平台' : account.login_method === 'direct' ? '账号直登' : '-'}</Descriptions.Item>
      <Descriptions.Item label="任务编号" span={2}><Typography.Text copyable>{task.task_id}</Typography.Text></Descriptions.Item>
    </Descriptions>
    {task.error && <Alert showIcon type="warning" title="任务提示" description={<div className="execution-long-text">{task.error}</div>} />}
    <div>
      <Typography.Title level={5}>申请人员与执行结果{people.length || app.snapshot_origin === 'captured' ? `（${people.length}）` : ''}</Typography.Title>
      <Table<ExecutionPerson> size="small" rowKey={(_, index) => index!} dataSource={people} pagination={people.length > 10 ? { pageSize: 10 } : false} scroll={{ x: 1100 }}
        locale={{ emptyText: app.snapshot_origin === 'unavailable' ? '历史记录未保留申请人员信息' : '暂无人员信息' }}
        expandable={{ expandedRowRender: (person) => <Descriptions size="small" column={2}>{Object.entries(personLabels).filter(([key]) => person[key] !== undefined && person[key] !== '').map(([key, label]) => <Descriptions.Item key={key} label={label}>{key === 'is_technology' ? person[key] === '1' ? '是' : '否' : String(person[key])}</Descriptions.Item>)}</Descriptions> }}
        columns={[
          { title: '姓名', dataIndex: 'name', width: 100 }, { title: '身份证号', dataIndex: 'identity_number', width: 190, render: (value) => value || '-' },
          { title: '险种 / 期间', width: 170, render: (_, person) => [person.insurance_type, person.start_month && `${person.start_month} — ${person.end_month || ''}`].filter(Boolean).join(' · ') || '-' },
          { title: '结果', dataIndex: 'status', width: 120, render: (value) => value === 'submitted' ? <OutcomeTag outcome="succeeded" /> : value === 'not_processed' ? <Tag>未执行</Tag> : <OutcomeTag outcome={value as ExecutionOutcome} /> },
          { title: '平台提示 / 结果说明', dataIndex: 'message', width: 320, render: (value) => <div className="execution-long-text">{value || '-'}</div> },
          { title: 'ERP 上传', width: 180, render: (_, person) => person.erp_success === true ? <Tag color="success">上传成功</Tag> : person.erp_success === false ? <Typography.Text type="danger">{person.erp_message || '上传失败'}</Typography.Text> : '-' },
        ]} />
    </div>
    {(files.length > 0 || archive?.url) && <Card size="small" title="结果文件">
      <Space orientation="vertical" align="start">
        {archive?.url && <Button icon={<DownloadOutlined />} href={archive.url}>下载整批结果（ZIP）</Button>}
        {files.map((file) => <Button key={file.url} type="link" href={file.url}>{file.name}</Button>)}
      </Space>
    </Card>}
  </Space>
}
