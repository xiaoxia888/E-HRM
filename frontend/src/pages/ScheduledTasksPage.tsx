import { useEffect, useState } from 'react'
import { ClockCircleOutlined, EditOutlined, PlayCircleOutlined, PlusOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import { Alert, Button, Card, DatePicker, Descriptions, Drawer, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import { PageTitle } from '../components/PageTitle'
import type { ScheduledJob, ScheduledJobValues, ScheduledRun } from '../types'

const labels: Record<string, string> = { queued: '排队中', running: '执行中', cancelling: '正在停止', succeeded: '成功', partial_failed: '部分失败', failed: '失败', cancelled: '已停止', interrupted: '已中断', skipped: '已跳过' }
const triggerLabels: Record<string, string> = { automatic: '定时', manual: '手动', preview: '只读预览' }
const active = ['queued', 'running', 'cancelling']
dayjs.extend(utc)
const format = (value?: string | null) => value ? dayjs(value).utcOffset(480).format('YYYY-MM-DD HH:mm:ss') : '—'
const statusTag = (status?: string) => <Tag color={status === 'succeeded' ? 'success' : ['failed', 'partial_failed', 'interrupted'].includes(status ?? '') ? 'error' : active.includes(status ?? '') ? 'processing' : 'default'}>{status ? labels[status] ?? status : '未执行'}</Tag>
const defaults: ScheduledJobValues = { name: 'ERP 原始申请同步到 NocoBase', task_type: 'erp_nocobase_sync', cron: '0 * * * *', enabled: false, lookback_days: 2 }
const jobValues = (job: ScheduledJob): ScheduledJobValues => ({ name: job.name, task_type: job.task_type, cron: job.cron, enabled: job.enabled, lookback_days: job.lookback_days })

export function ScheduledTasksPage() {
  const client = useQueryClient()
  const [filter, setFilter] = useState<string>()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [editor, setEditor] = useState<ScheduledJob | 'new' | null>(null)
  const [execution, setExecution] = useState<ScheduledJob | null>(null)
  const [range, setRange] = useState({ start_date: '', end_date: '' })
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [form] = Form.useForm<ScheduledJobValues>()
  const jobs = useQuery({ queryKey: ['scheduled-tasks'], queryFn: api.scheduledTasks, refetchInterval: 5000 })
  const history = useQuery({ queryKey: ['scheduled-runs', filter, page, pageSize], queryFn: () => api.scheduledRuns(filter, page, pageSize), refetchInterval: 5000 })
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['scheduled-tasks'] })
    void client.invalidateQueries({ queryKey: ['scheduled-runs'] })
    void client.invalidateQueries({ queryKey: ['tasks'] })
  }
  const preview = useMutation({ mutationFn: api.cronPreview, onError: (error) => message.error(errorMessage(error)) })
  useEffect(() => {
    if (editor) { form.setFieldsValue(editor === 'new' ? defaults : jobValues(editor)) }
  }, [editor, form])
  const save = useMutation({
    mutationFn: api.saveScheduledTask,
    onSuccess: () => { message.success('定时任务已保存'); setEditor(null); refresh() },
    onError: (error) => message.error(errorMessage(error)),
  })
  const execute = useMutation({
    mutationFn: api.runScheduledTask,
    onSuccess: (run) => {
      if (run.status === 'skipped') message.warning(run.message)
      else message.success('任务已创建，执行记录和日志会持续更新')
      setExecution(null); setSelectedRun(run.id); refresh()
    },
    onError: (error) => { message.error(errorMessage(error)); refresh() },
  })
  const openEditor = (value: ScheduledJob | 'new') => { preview.reset(); setEditor(value) }
  return <div className="page-stack">
    <PageTitle title="定时任务" description="管理触发计划、手动执行和历史日志；只允许已注册的业务任务" extra={<Space><Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor('new')}>新增任务</Button></Space>} />
    <Alert type="info" showIcon title="ERP 同步只搬运原始申请，不解析人员" description="按标题、问题描述和申请日期判断来源变化；保留人员、附件及人工办理信息。定时和手动重叠会记录跳过，手动执行不会改变下一次计划。" />
    {jobs.isError && <Alert type="error" title={errorMessage(jobs.error)} />}
    {jobs.data && !jobs.data.scheduler_running && <Alert type="warning" title="调度器未运行，自动任务不会触发" />}
    <Card className="content-card" title={<Space><ClockCircleOutlined />任务计划<Typography.Text type="secondary">时区：Asia/Shanghai</Typography.Text></Space>}>
      <Table<ScheduledJob> rowKey="id" loading={jobs.isLoading} dataSource={jobs.data?.jobs ?? []} scroll={{ x: 1200 }} pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 个计划` }} columns={[
        { title: '任务名称', dataIndex: 'name', width: 245, render: (_, job) => <Space orientation="vertical"><Typography.Text strong>{job.name}</Typography.Text><Typography.Text type="secondary">ERP → NocoBase · 回查 {job.lookback_days} 天</Typography.Text>{job.notice && <Typography.Text type="warning">{job.notice}</Typography.Text>}</Space> },
        { title: 'Cron', dataIndex: 'cron', width: 155, render: (value) => <Typography.Text code>{value}</Typography.Text> },
        { title: '启用', width: 80, render: (_, job) => <Switch aria-label={`启用 ${job.name}`} checked={job.enabled} loading={save.isPending} onChange={(enabled) => save.mutate({ id: job.id, values: { ...jobValues(job), enabled } })} /> },
        { title: '下次执行', dataIndex: 'next_run', width: 175, render: format },
        { title: '最近触发', width: 185, render: (_, job) => <Space orientation="vertical">{statusTag(job.last_run?.status)}<Typography.Text type="secondary">{format(job.last_run?.created_at)}</Typography.Text></Space> },
        { title: '操作', width: 270, fixed: 'right', render: (_, job) => <Space wrap><Button type="link" icon={<EditOutlined />} onClick={() => openEditor(job)}>编辑</Button><Button type="link" icon={<PlayCircleOutlined />} onClick={() => { setRange({ start_date: '', end_date: '' }); setExecution(job) }}>执行一次</Button><Button type="link" onClick={() => { setFilter(job.id); setPage(1) }}>执行记录</Button></Space> },
      ]} />
    </Card>
    <Card className="content-card" title="执行记录" extra={<Select aria-label="筛选任务" allowClear placeholder="全部任务" style={{ width: 260 }} value={filter} options={jobs.data?.jobs.map((job) => ({ value: job.id, label: job.name }))} onChange={(value) => { setFilter(value); setPage(1) }} />}>
      {history.isError && <Alert type="error" title={errorMessage(history.error)} />}
      <Table<ScheduledRun> rowKey="id" loading={history.isLoading} dataSource={history.data?.items ?? []} scroll={{ x: 1000 }} pagination={{ current: page, pageSize, total: history.data?.total ?? 0, showSizeChanger: true, showTotal: (total) => `共 ${total} 条`, onChange: (next, size) => { setPage(next); setPageSize(size) } }} columns={[
        { title: '任务', width: 220, render: (_, run) => jobs.data?.jobs.find((job) => job.id === run.job_id)?.name ?? run.job_id },
        { title: '触发', dataIndex: 'trigger_kind', width: 110, render: (value) => triggerLabels[value] ?? value },
        { title: '状态', dataIndex: 'status', width: 115, render: statusTag },
        { title: '触发时间', dataIndex: 'created_at', width: 175, render: format },
        { title: '耗时', width: 90, render: (_, run) => run.started_at && run.finished_at ? `${Math.max(0, dayjs(run.finished_at).diff(dayjs(run.started_at), 'second'))} 秒` : '—' },
        { title: '当前说明', dataIndex: 'message', ellipsis: true },
        { title: '操作', width: 110, fixed: 'right', render: (_, run) => <Button type="link" onClick={() => setSelectedRun(run.id)}>查看日志</Button> },
      ]} />
    </Card>
    <Modal title={editor === 'new' ? '新增定时任务' : '编辑定时任务'} open={editor !== null} forceRender onCancel={() => setEditor(null)} confirmLoading={save.isPending} onOk={() => { void form.validateFields().then((values) => save.mutate({ id: editor && editor !== 'new' ? editor.id : undefined, values })) }} okText="保存">
      <Form form={form} layout="vertical" onValuesChange={() => preview.reset()}>
        <Form.Item name="name" label="任务名称" rules={[{ required: true, whitespace: true, max: 100 }]}><Input /></Form.Item>
        <Form.Item name="task_type" label="任务类型" rules={[{ required: true }]}><Select options={jobs.data?.task_types ?? [{ value: defaults.task_type, label: 'ERP → NocoBase 原始申请同步' }]} /></Form.Item>
        <Form.Item label="常用计划"><Select placeholder="选择后填入 cron，也可以手动编辑" onChange={(value) => { form.setFieldValue('cron', value); preview.reset() }} options={[{ value: '0 * * * *', label: '每小时整点' }, { value: '*/30 * * * *', label: '每半小时' }, { value: '0 8 * * *', label: '每天 08:00' }, { value: '0 8 * * mon', label: '每周一 08:00' }]} /></Form.Item>
        <Form.Item name="cron" label="Cron 表达式" rules={[{ required: true }]} extra="五段：分 时 日 月 星期；0/7 是周日，支持 mon–sun；日和星期同时限定时按任一匹配触发。时区 Asia/Shanghai。"><Input placeholder="0 * * * *" /></Form.Item>
        <Button loading={preview.isPending} onClick={() => preview.mutate(form.getFieldValue('cron') ?? '')}>预览后 5 次触发</Button>
        {preview.data && <Space orientation="vertical" style={{ display: 'flex', margin: '12px 0' }}>{preview.data.times.map((time) => <Typography.Text key={time}>{format(time)}</Typography.Text>)}</Space>}
        <Form.Item name="lookback_days" label="回查天数（包含今天）" rules={[{ required: true }]} extra="按 ERP 申请日期查询；历史申请修改请手动指定更大日期范围。" style={{ marginTop: 16 }}><InputNumber min={1} max={366} precision={0} /></Form.Item>
        <Form.Item name="enabled" label="启用自动执行" valuePropName="checked"><Switch /></Form.Item>
      </Form>
      <Typography.Text type="secondary">关闭仅停止后续自动触发，不取消当前任务。记录和日志不会到期删除。</Typography.Text>
    </Modal>
    <Modal title={`执行一次 · ${execution?.name ?? ''}`} open={execution !== null} onCancel={() => setExecution(null)} footer={<Space><Button onClick={() => setExecution(null)}>取消</Button><Button loading={execute.isPending} onClick={() => execution && execute.mutate({ id: execution.id, ...range, dry_run: true })}>只读预览</Button><Button type="primary" loading={execute.isPending} onClick={() => execution && execute.mutate({ id: execution.id, ...range, dry_run: false })}>开始同步</Button></Space>}>
      <Alert type="info" showIcon title="先预览，再确认是否同步" description="预览只查询、不写入。开始同步会向 NocoBase 新增或更新原始申请，不调用模型或办理参保、停保。" />
      <Space orientation="vertical" style={{ marginTop: 20, width: '100%' }}><Typography.Text>日期范围（不选则回查 {execution?.lookback_days} 天）</Typography.Text><DatePicker.RangePicker value={range.start_date ? [dayjs(range.start_date), dayjs(range.end_date)] : null} onChange={(_, dates) => setRange({ start_date: dates[0] ?? '', end_date: dates[1] ?? '' })} /></Space>
    </Modal>
    {selectedRun && <RunDetails id={selectedRun} onClose={() => setSelectedRun(null)} />}
  </div>
}

function RunDetails({ id, onClose }: { id: string; onClose: () => void }) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const run = useQuery({ queryKey: ['scheduled-run', id], queryFn: () => api.scheduledRun(id), refetchInterval: 3000 })
  const logs = useQuery({ queryKey: ['scheduled-logs', id, page, pageSize], queryFn: () => api.scheduledLogs(id, page, pageSize), refetchInterval: 3000 })
  const cancel = useMutation({ mutationFn: api.cancelTask, onSuccess: () => message.success('已请求停止'), onError: (error) => message.error(errorMessage(error)) })
  const record = run.data
  return <Drawer title="执行详情与步骤日志" width="min(900px, 95vw)" open onClose={onClose} extra={record?.task_id && active.includes(record.status) && <Button danger icon={<StopOutlined />} loading={cancel.isPending} onClick={() => record.task_id && cancel.mutate(record.task_id)}>停止任务</Button>}>
    {run.isError && <Alert type="error" title={errorMessage(run.error)} />}
    <Descriptions column={2} items={[
      { key: 'status', label: '状态', children: statusTag(record?.status) },
      { key: 'trigger', label: '触发方式', children: triggerLabels[record?.trigger_kind ?? ''] },
      { key: 'start', label: '开始执行', children: format(record?.started_at) },
      { key: 'end', label: '执行结束', children: format(record?.finished_at) },
      { key: 'range', label: '查询范围', children: record ? `${record.parameters.start_date} 至 ${record.parameters.end_date}` : '—', span: 2 },
      { key: 'task', label: '任务编号', children: record?.task_id ?? '未创建', span: 2 },
    ]} />
    {record?.message && <Alert style={{ margin: '16px 0' }} type={['failed', 'partial_failed'].includes(record.status) ? 'error' : 'info'} title={record.message} />}
    {record?.result?.summary && <Descriptions title="处理结果" column={3} items={Object.entries(record.result.summary).map(([key, value]) => ({ key, label: ({ total: '总数', created: '新增', updated: '更新', unchanged: '未变化', failed: '失败', would_create: '预计新增', would_update: '预计更新' } as Record<string, string>)[key] ?? key, children: value }))} />}
    {record?.result?.items && <Table size="small" rowKey={(_, index) => String(index)} dataSource={record.result.items} pagination={{ pageSize: 10 }} columns={[{ title: 'ERP 编号', dataIndex: 'application_code' }, { title: '处理结果', dataIndex: 'action', render: (value) => ({ created: '已新增', updated: '已更新', unchanged: '未变化', would_create: '预计新增', would_update: '预计更新', failed: '失败' } as Record<string, string>)[value] ?? value }, { title: '说明', render: (_, item) => String(item.error ?? item.warning ?? '') }]} />}
    <Typography.Title level={5}>步骤日志</Typography.Title>
    {logs.isError && <Alert type="error" title={errorMessage(logs.error)} />}
    <Table size="small" rowKey="id" loading={logs.isLoading} dataSource={logs.data?.items ?? []} pagination={{ current: page, pageSize, total: logs.data?.total ?? 0, showSizeChanger: true, showTotal: (total) => `共 ${total} 条`, onChange: (next, size) => { setPage(next); setPageSize(size) } }} columns={[
      { title: '时间', dataIndex: 'created_at', width: 170, render: format },
      { title: '级别', dataIndex: 'level', width: 75, render: (value) => <Tag color={value === 'error' ? 'error' : value === 'warning' ? 'warning' : 'default'}>{value === 'error' ? '错误' : value === 'warning' ? '警告' : '信息'}</Tag> },
      { title: '日志', dataIndex: 'message' },
    ]} />
  </Drawer>
}
