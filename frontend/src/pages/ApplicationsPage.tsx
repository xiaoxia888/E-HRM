import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Empty, Modal, Progress, Select, Skeleton, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import { PageTitle } from '../components/PageTitle'
import { RightsTaskProgressModal } from './RightsPage'
import type { AccountSummary, BusinessPerson } from '../types'

const businessLabels: Record<string, string> = {
  social_security_rights: '单位社保权益单', social_security_termination: '社保退工停保登记',
  social_security_enrollment: '社保用工参保登记', medical_termination: '医保退工停保登记',
  medical_enrollment: '医保人员参保登记',
}
const stateLabels: Record<string, string> = { queued: '排队中', running: '执行中', submitting: '提交中', succeeded: '已办理', unknown: '结果待确认', failed: '失败', not_processed: '未办理' }
type Action = 'print' | 'termination' | 'medical_termination' | 'medical_enrollment' | 'information_collection' | 'enrollment'
const actionLabels = { print: '打印社保权益单', termination: '社保退保', medical_termination: '医保停保', medical_enrollment: '医保参保', information_collection: '基础信息采集', enrollment: '参保登记' }
type Confirmation = { action: Action; applicationId: number; account: AccountSummary; upload: boolean }

export function ApplicationsPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [printAccountId, setPrintAccountId] = useState<number>()
  const [medicalAccountId, setMedicalAccountId] = useState<number>()
  const [uploadToErp, setUploadToErp] = useState(false)
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [activeTask, setActiveTask] = useState<{ id: string; applicationId: number; action: Action } | null>(null)
  const [progressOpen, setProgressOpen] = useState(false)
  const applications = useQuery({
    queryKey: ['applications', page, pageSize],
    queryFn: () => api.applications(page, pageSize),
  })
  const detail = useQuery({
    queryKey: ['application', selectedId],
    queryFn: () => api.applicationDetail(selectedId as number),
    enabled: selectedId !== null,
  })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const statesId = selectedId
  const operationStates = useQuery({
    queryKey: ['application-operations', statesId], queryFn: () => api.applicationOperations(statesId as number),
    enabled: statesId !== null, refetchInterval: 1000,
  })
  const task = useQuery({
    queryKey: ['task', activeTask?.id], queryFn: () => api.task(activeTask!.id), enabled: Boolean(activeTask),
    refetchInterval: (query) => query.state.data && !['queued', 'running', 'cancelling'].includes(query.state.data.status) ? false : 1000,
  })
  const progressStates = useQuery({
    queryKey: ['application-operations', activeTask?.applicationId], queryFn: () => api.applicationOperations(activeTask!.applicationId),
    enabled: Boolean(activeTask) && progressOpen && ['termination', 'medical_termination', 'medical_enrollment'].includes(activeTask?.action ?? ''), refetchInterval: progressOpen ? 1000 : false,
  })
  const runId = ['application.termination:', 'application.medical_termination:', 'application.medical_enrollment:'].some((prefix) => task.data?.operation.startsWith(prefix)) ? task.data?.operation.split(':')[1] ?? '' : ''
  const operationResult = task.data?.result as { submitted_count: number; existing_count?: number; unknown_count: number; total: number } | null | undefined
  const logs = useQuery({
    queryKey: ['application-operation-logs', runId], queryFn: () => api.applicationOperationLogs(activeTask!.applicationId, runId),
    enabled: Boolean(runId), refetchInterval: progressOpen ? 1000 : false,
  })
  const canceller = useMutation({ mutationFn: api.cancelTask, onSuccess: () => task.refetch(), onError: (error) => message.error(errorMessage(error)) })
  const rightsAccounts = (accounts.data ?? []).filter((item) => item.system_type === 'JSHRSS' && item.ready)
  const medicalAccounts = (accounts.data ?? []).filter((item) => item.system_type === 'MEDICAL' && item.ready)
  useEffect(() => {
    if (rightsAccounts.length && !rightsAccounts.some((item) => item.id === printAccountId)) {
      setPrintAccountId((rightsAccounts.find((item) => item.is_default) ?? rightsAccounts[0]).id)
    } else if (!rightsAccounts.length && printAccountId !== undefined) {
      setPrintAccountId(undefined)
    }
  }, [printAccountId, rightsAccounts])
  useEffect(() => {
    if (medicalAccounts.length && !medicalAccounts.some((item) => item.id === medicalAccountId)) {
      setMedicalAccountId((medicalAccounts.find((item) => item.is_default) ?? medicalAccounts[0]).id)
    } else if (!medicalAccounts.length && medicalAccountId !== undefined) {
      setMedicalAccountId(undefined)
    }
  }, [medicalAccountId, medicalAccounts])
  useEffect(() => {
    if (settings.data) setUploadToErp(settings.data.upload_to_erp)
  }, [settings.data])
  const executor = useMutation({
    mutationFn: (value: Confirmation) => value.action === 'termination'
      ? api.terminateApplication(value.applicationId, value.account.id)
      : value.action === 'medical_termination'
        ? api.terminateMedicalApplication(value.applicationId, value.account.id)
        : value.action === 'medical_enrollment'
          ? api.enrollMedicalApplication(value.applicationId, value.account.id)
          : api.printApplication(value.applicationId, value.account.id, value.upload),
    onSuccess: (result, value) => {
      setConfirmation(null)
      setActiveTask({ id: result.task_id, applicationId: value.applicationId, action: value.action })
      setProgressOpen(true)
      operationStates.refetch()
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  const kind = detail.data?.problem_type ?? ''
  const currentStates = (statesId === selectedId ? operationStates.data : undefined) ?? detail.data?.operation_states
  const stateFor = (person: BusinessPerson, operation: string) => currentStates?.people.find((item) => item.person_key === person.operation_key && item.operation === operation)
  const operation = kind === 'medical_termination' ? 'medical_termination' : kind === 'medical_enrollment' ? 'medical_enrollment' : 'termination'
  const activeRun = currentStates?.runs.find((item) => item.active && item.operation === operation)
  const latestRun = currentStates?.runs.find((item) => item.operation === operation && item.task_id)
  const operationPeople = kind === 'medical_termination' ? detail.data?.med_ins_withdrawal_record ?? [] : kind === 'medical_enrollment' ? detail.data?.med_ins_enrollee ?? [] : detail.data?.termination_person ?? []
  const eligible = operationPeople.filter((person) => !['succeeded', 'unknown'].includes(stateFor(person, operation)?.status ?? ''))
  const ask = (action: Action) => {
    const medical = action === 'medical_termination' || action === 'medical_enrollment'
    const account = medical
      ? medicalAccounts.find((item) => item.id === medicalAccountId)
      : rightsAccounts.find((item) => item.id === printAccountId)
    if (!account || selectedId === null) { message.error(medical ? '请选择完整的医保政务平台账号' : '请选择完整的智慧人社登录账号'); return }
    setConfirmation({ action, applicationId: selectedId, account, upload: uploadToErp })
  }
  const confirm = () => {
    if (!confirmation) return
    if (['information_collection', 'enrollment'].includes(confirmation.action)) {
      message.info(`${actionLabels[confirmation.action]}为预留功能，本次未执行任何操作，也不会标记已办理`)
      setConfirmation(null)
      return
    }
    executor.mutate(confirmation)
  }
  const renderStatus = (person: BusinessPerson, operation: string) => {
    const state = stateFor(person, operation)
    const label = stateLabels[state?.status ?? 'not_processed'] ?? state?.status
    return <Space direction="vertical" size={0}><Tag color={state?.status === 'succeeded' ? 'green' : state?.status === 'unknown' ? 'orange' : 'blue'}>{label}</Tag>{state?.message && <Typography.Text type="secondary">{state.message}</Typography.Text>}</Space>
  }

  return (
    <div className="page-stack">
      <PageTitle
        title="权益申请"
        description="通过 NocoBase API 查询申请，并记录退保与医保参保执行状态"
        extra={<Button icon={<ReloadOutlined />} onClick={() => applications.refetch()}>刷新</Button>}
      />
      {applications.isError && <Alert type="error" showIcon message="权益申请查询失败" description={errorMessage(applications.error)} />}
      <Card className="content-card">
        <Table
          rowKey="application_id"
          loading={applications.isLoading}
          dataSource={applications.data?.records ?? []}
          locale={{ emptyText: <Empty description="暂无权益申请" /> }}
          onRow={(record) => ({ onClick: () => setSelectedId(record.application_id) })}
          scroll={{ x: 1100 }}
          pagination={{
            current: page,
            pageSize,
            total: applications.data?.meta.count ?? 0,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: (total) => `共 ${total} 条`,
            onChange: (nextPage, nextSize) => {
              setPage(nextSize !== pageSize ? 1 : nextPage)
              setPageSize(nextSize)
            },
          }}
          columns={[
            { title: '编号', dataIndex: 'code', width: 210 },
            { title: '状态', dataIndex: 'status', width: 100, render: (value) => <Tag color="blue">{value || '-'}</Tag> },
            { title: '事务类型', dataIndex: 'problem_type', width: 150, render: (value) => businessLabels[value] ?? value },
            { title: '标题', dataIndex: 'title', width: 260, ellipsis: true },
            { title: '发起人', dataIndex: 'initiator_name', width: 130 },
            { title: '发起日期', dataIndex: 'initiation_date', width: 150, render: (value) => value ? dayjs(value).format('YYYY-MM-DD') : '-' },
            { title: '预计工时', dataIndex: 'estimate_time', width: 110 },
            { title: '实际工时', dataIndex: 'actual_time', width: 110 },
          ]}
        />
      </Card>
      <Drawer
        title="权益申请详情"
        width="min(1100px, 94vw)"
        open={selectedId !== null}
        onClose={() => setSelectedId(null)}
        footer={kind.startsWith('social_security_') || kind === 'medical_termination' || kind === 'medical_enrollment' ? (
          <div className="application-detail-actions" aria-label="申请办理操作">
            <Space size={6}>
              {kind === 'social_security_rights' && <><Switch size="small" checked={uploadToErp} onChange={setUploadToErp} /><Typography.Text>完成后上传 ERP</Typography.Text></>}
            </Space>
            <Select
              aria-label="执行账号"
              value={kind.startsWith('medical_') ? medicalAccountId : printAccountId}
              placeholder={kind.startsWith('medical_') ? '选择医保政务平台账号' : '选择智慧人社账号'}
              className="application-detail-actions__account"
              options={(kind.startsWith('medical_') ? medicalAccounts : rightsAccounts).map((item) => ({ value: item.id, label: `${item.display_name} · ${item.masked_account} · ${item.login_method === 'government_sso' ? '政务服务平台' : '智慧人社直登'}` }))}
              onChange={kind.startsWith('medical_') ? setMedicalAccountId : setPrintAccountId}
            />
            {kind === 'social_security_rights' && <Button
              type="primary"
              disabled={!detail.data || !detail.data.related_persons.length || printAccountId === undefined}
              loading={executor.isPending}
              onClick={() => ask('print')}
            >
              打印社保权益单
            </Button>}
            {kind === 'social_security_termination' && <>
              <Button type="primary" danger disabled={!eligible.length || Boolean(activeRun) || printAccountId === undefined} loading={executor.isPending} onClick={() => ask('termination')}>退保</Button>
              {latestRun?.task_id && <Button onClick={() => { setActiveTask({ id: latestRun.task_id, applicationId: selectedId!, action: 'termination' }); setProgressOpen(true) }}>{activeRun ? '查看进度' : '查看执行结果'}</Button>}
            </>}
            {kind === 'medical_termination' && <>
              <Button type="primary" danger disabled={!eligible.length || Boolean(activeRun) || medicalAccountId === undefined} loading={executor.isPending} onClick={() => ask('medical_termination')}>医保停保</Button>
              {latestRun?.task_id && <Button onClick={() => { setActiveTask({ id: latestRun.task_id, applicationId: selectedId!, action: 'medical_termination' }); setProgressOpen(true) }}>{activeRun ? '查看进度' : '查看执行结果'}</Button>}
            </>}
            {kind === 'medical_enrollment' && <>
              <Button type="primary" disabled={!eligible.length || Boolean(activeRun) || medicalAccountId === undefined} loading={executor.isPending} onClick={() => ask('medical_enrollment')}>医保参保</Button>
              {latestRun?.task_id && <Button onClick={() => { setActiveTask({ id: latestRun.task_id, applicationId: selectedId!, action: 'medical_enrollment' }); setProgressOpen(true) }}>{activeRun ? '查看进度' : '查看执行结果'}</Button>}
            </>}
            {kind === 'social_security_enrollment' && <><Button disabled={printAccountId === undefined} onClick={() => ask('information_collection')}>基础信息采集</Button><Button disabled={printAccountId === undefined} onClick={() => ask('enrollment')}>参保登记</Button></>}
          </div>
        ) : null}
      >
        {detail.isLoading ? <Skeleton active /> : detail.isError ? (
          <Alert type="error" showIcon message="详情查询失败" description={errorMessage(detail.error)} />
        ) : detail.data ? (
          <Space direction="vertical" size={24} style={{ width: '100%' }}>
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="编号">{detail.data.code}</Descriptions.Item>
              <Descriptions.Item label="状态">{detail.data.status}</Descriptions.Item>
              <Descriptions.Item label="标题" span={2}>{detail.data.title}</Descriptions.Item>
              <Descriptions.Item label="录入人">{detail.data.created_by_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="发起人">{detail.data.initiator_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="问题描述" span={2}>{detail.data.problem_description || '暂无内容'}</Descriptions.Item>
              <Descriptions.Item label="处理方式" span={2}>{detail.data.handling_method || '暂无内容'}</Descriptions.Item>
            </Descriptions>
            {kind === 'social_security_termination' && <>
              <Alert type="warning" showIcon message="退保将真实提交。已办理或结果待确认的人员不会重复提交；待确认项请人工核对。" />
              <Table<BusinessPerson> rowKey="id" size="small" dataSource={operationPeople} pagination={false} scroll={{ x: 800 }} columns={[
                { title: '姓名', dataIndex: 'user_name', width: 100 }, { title: '身份证号', dataIndex: 'id_card_no', width: 190 },
                { title: '退工原因', width: 180, render: (_, row) => row.termination_reason_label || row.termination_reason || '-' },
                { title: '退保状态', render: (_, row) => renderStatus(row, 'termination') },
                { title: '执行账号', render: (_, row) => stateFor(row, 'termination')?.account_label ?? '-' },
                { title: '最后处理时间', render: (_, row) => { const at = stateFor(row, 'termination')?.updated_at; return at ? dayjs(at).format('YYYY-MM-DD HH:mm:ss') : '-' } },
              ]} />
            </>}
            {kind === 'social_security_enrollment' && <>
              <Alert type="info" showIcon message="基础信息采集和参保登记暂未接入执行。两个操作独立记录状态，预留按钮不会提交或标记成功。" />
              <Table<BusinessPerson> rowKey="id" size="small" dataSource={detail.data.insurance_person ?? []} pagination={false} scroll={{ x: 1300 }} expandable={{ expandedRowRender: (row) => <Descriptions bordered column={2} size="small">
                <Descriptions.Item label="民族">{row.ethnicity || '-'}</Descriptions.Item><Descriptions.Item label="工种">{row.job_type || '-'}</Descriptions.Item>
                <Descriptions.Item label="户籍地区 ID">{row.administrative_division_id ?? '-'}</Descriptions.Item><Descriptions.Item label="合同增加原因">{row.contract_add_reason || '-'}</Descriptions.Item>
                <Descriptions.Item label="合同结束日期">{row.contract_end_date || '-'}</Descriptions.Item><Descriptions.Item label="参保身份">{row.insurance_identity || '-'}</Descriptions.Item>
                <Descriptions.Item label="月缴费工资">{row.monthly_contribution_salary ?? '-'}</Descriptions.Item><Descriptions.Item label="是否管理技术岗">{row.is_technology === '1' ? '是' : row.is_technology === '0' ? '否' : '-'}</Descriptions.Item>
              </Descriptions> }} columns={[
                { title: '姓名', dataIndex: 'user_name' }, { title: '身份证号', dataIndex: 'id_card_no', width: 190 },
                { title: '电话', dataIndex: 'phone' }, { title: '户籍性质', dataIndex: 'household_type' },
                { title: '合同类别', dataIndex: 'contract_type' }, { title: '合同开始日期', dataIndex: 'contract_start_date' },
                { title: '信息采集状态', render: (_, row) => renderStatus(row, 'information_collection') },
                { title: '参保登记状态', render: (_, row) => renderStatus(row, 'enrollment') },
              ]} />
            </>}
            {kind === 'medical_termination' && <>
              <Alert type="warning" showIcon message="医保停保将按申请人员顺序逐人真实提交；已办理或结果待确认者不会重复提交，遇到提交失败或结果不明时停止后续办理。" />
              <Table<BusinessPerson> rowKey="id" size="small" dataSource={detail.data.med_ins_withdrawal_record ?? []} pagination={false} scroll={{ x: 900 }} columns={[
                { title: '姓名', dataIndex: 'user_name', width: 110 },
                { title: '身份证号', dataIndex: 'id_card_no', width: 190 },
                { title: '停保原因', dataIndex: 'med_ins_stop_reason', width: 220, render: (value) => value || '-' },
                { title: '停保时间', dataIndex: 'med_stop_date', width: 150, render: (value) => value || '-' },
                { title: '停保当月是否缴费', dataIndex: 'med_ins_stop_month_fee', width: 180, render: (value) => value || '-' },
                { title: '医保停保状态', width: 160, render: (_, row) => renderStatus(row, 'medical_termination') },
                { title: '执行账号', width: 120, render: (_, row) => stateFor(row, 'medical_termination')?.account_label ?? '-' },
                { title: '最后处理时间', width: 170, render: (_, row) => { const at = stateFor(row, 'medical_termination')?.updated_at; return at ? dayjs(at).format('YYYY-MM-DD HH:mm:ss') : '-' } },
              ]} />
            </>}
            {kind === 'medical_enrollment' && <>
              <Alert type="warning" showIcon message="医保参保将真实提交：先查参保，仅在平台提示需先建档时自动采集并重查。已办理或结果待确认者不重复提交；异常时停止后续人员。" />
              <Table<BusinessPerson> rowKey="id" size="small" dataSource={operationPeople} pagination={false} scroll={{ x: 1500 }} columns={[
                { title: '姓名', dataIndex: 'user_name', width: 110 },
                { title: '身份证号', dataIndex: 'id_card_no', width: 190 },
                { title: '民族', dataIndex: 'ethnicity', width: 100, render: (value) => value || '-' },
                { title: '联系电话', dataIndex: 'phone', width: 150, render: (value) => value || '-' },
                { title: '证件有效期起', dataIndex: 'cert_valid_from', width: 150, render: (value) => value || '-' },
                { title: '证件有效期止', dataIndex: 'cert_valid_to', width: 150, render: (value) => value || '-' },
                { title: '到单位时间', dataIndex: 'arrive_unit_time', width: 150, render: (value) => value || '-' },
                { title: '建档状态', width: 180, render: (_, row) => renderStatus(row, 'medical_information_collection') },
                { title: '医保参保状态', width: 200, render: (_, row) => renderStatus(row, 'medical_enrollment') },
                { title: '执行账号', width: 130, render: (_, row) => stateFor(row, 'medical_enrollment')?.account_label ?? '-' },
                { title: '最后处理时间', width: 175, render: (_, row) => { const at = stateFor(row, 'medical_enrollment')?.updated_at; return at ? dayjs(at).format('YYYY-MM-DD HH:mm:ss') : '-' } },
              ]} />
            </>}
            {kind === 'social_security_rights' && <div>
              <Typography.Title level={5}>申请人员（{detail.data.related_persons.length} 人）</Typography.Title>
              <Table
                rowKey="person_id"
                size="small"
                dataSource={detail.data.related_persons}
                scroll={{ x: 1050, y: 430 }}
                pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
                columns={[
                  { title: '打印组', dataIndex: 'print_group', width: 100, render: (value) => value || '单独打印' },
                  { title: '姓名', dataIndex: 'name', width: 110 },
                  { title: '身份证号', dataIndex: 'identity_number', width: 190 },
                  { title: '单位', dataIndex: 'company', width: 220, ellipsis: true },
                  { title: '部门', dataIndex: 'department', width: 160, ellipsis: true },
                  { title: '起始月份', dataIndex: 'start_month', width: 120, render: (value) => value ? dayjs(value).format('YYYY-MM') : '-' },
                  { title: '结束月份', dataIndex: 'end_month', width: 120, render: (value) => value ? dayjs(value).format('YYYY-MM') : '-' },
                ]}
              />
            </div>}
          </Space>
        ) : null}
      </Drawer>
      <Modal title="确认执行账号" open={Boolean(confirmation)} width={['medical_termination', 'medical_enrollment'].includes(confirmation?.action ?? '') ? 760 : undefined} destroyOnHidden onCancel={() => !executor.isPending && setConfirmation(null)} onOk={confirm} confirmLoading={executor.isPending} okText="确认执行" cancelText="取消" closable={!executor.isPending} maskClosable={false}>
        <Typography.Paragraph>确定使用以下账号执行「{confirmation && actionLabels[confirmation.action]}」？</Typography.Paragraph>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="执行账号">{confirmation?.account.display_name} · {confirmation?.account.masked_account}</Descriptions.Item>
          <Descriptions.Item label="登录方式">{confirmation?.account.login_method === 'government_sso' ? '江苏政务服务平台' : '智慧人社直登'}</Descriptions.Item>
        </Descriptions>
        {confirmation?.action === 'termination' && <Alert style={{ marginTop: 16 }} type="warning" showIcon message={`本次办理 ${eligible.length} 人退保，跳过已办理/待确认人员；将确认真实性声明并真实提交，请核对账号所属单位。退工日期沿用业务页面默认值。`} />}
        {confirmation?.action === 'medical_termination' && <>
          <Alert style={{ marginTop: 16 }} type="warning" showIcon message={`本次将按顺序办理 ${eligible.length} 名待办人员。请确认账号所属单位和下列资料；提交失败或结果不明时停止后续办理，结果不明者不会自动重试。`} />
          <Table<BusinessPerson> style={{ marginTop: 16 }} size="small" rowKey="id" pagination={false} scroll={{ x: 680, y: 240 }} dataSource={eligible} columns={[
            { title: '姓名', dataIndex: 'user_name', width: 100 },
            { title: '身份证号', dataIndex: 'id_card_no', width: 190 },
            { title: '停保日期', dataIndex: 'med_stop_date', width: 130 },
            { title: '停保原因', dataIndex: 'med_ins_stop_reason', width: 200 },
            { title: '当月缴费', dataIndex: 'med_ins_stop_month_fee', width: 90 },
          ]} />
        </>}
        {confirmation?.action === 'medical_enrollment' && <>
          <Alert style={{ marginTop: 16 }} type="warning" showIcon message={`本次将依次办理 ${eligible.length} 名待办人员。先查参保，仅在提示需先建档时自动采集；请核对账号所属单位和下列资料，确认后会真实提交。`} />
          <Table<BusinessPerson> style={{ marginTop: 16 }} size="small" rowKey="id" pagination={false} scroll={{ x: 680, y: 240 }} dataSource={eligible} columns={[
            { title: '姓名', dataIndex: 'user_name', width: 100 },
            { title: '身份证号', dataIndex: 'id_card_no', width: 190 },
            { title: '电话', dataIndex: 'phone', width: 140 },
            { title: '到单位时间', dataIndex: 'arrive_unit_time', width: 130 },
            { title: '民族（需建档时）', dataIndex: 'ethnicity', width: 140, render: (value) => value || '-' },
          ]} />
        </>}
        {confirmation && ['enrollment', 'information_collection'].includes(confirmation.action) && <Alert style={{ marginTop: 16 }} type="info" message="仅为功能预留，不执行真实操作。" />}
      </Modal>
      {activeTask?.action === 'print' && <RightsTaskProgressModal open={progressOpen} task={task.data} loading={task.isLoading} cancelling={canceller.isPending} onCancelTask={() => canceller.mutate(activeTask.id)} onOpenTasks={() => navigate('/tasks')} onClose={() => setProgressOpen(false)} />}
      {activeTask && ['termination', 'medical_termination', 'medical_enrollment'].includes(activeTask.action) && <Modal title={`${activeTask.action === 'medical_enrollment' ? '医保参保' : '退保'}执行${task.data && !['queued', 'running', 'cancelling'].includes(task.data.status) ? '结果' : '进度'}`} open={progressOpen} width={880} onCancel={() => setProgressOpen(false)} maskClosable={false} footer={<Space><Button onClick={() => navigate('/tasks')}>任务中心</Button>{task.data && ['queued', 'running', 'cancelling'].includes(task.data.status) && <Button danger loading={canceller.isPending} onClick={() => canceller.mutate(activeTask.id)}>停止后续处理</Button>}<Button onClick={() => setProgressOpen(false)}>关闭</Button></Space>}>
        {task.isError && <Alert type="error" message="进度获取失败，不能据此判断提交失败，请勿重复提交" description={errorMessage(task.error)} />}
        <Progress percent={Math.round((task.data?.progress_current ?? 0) / Math.max(1, task.data?.progress_total ?? 1) * 100)} />
        <Typography.Paragraph>{task.data?.message ?? '正在获取执行进度……'}</Typography.Paragraph>
        {operationResult?.total !== undefined && <Alert showIcon type={operationResult.submitted_count + (operationResult.existing_count ?? 0) === operationResult.total ? 'success' : 'warning'} message={`本次 ${operationResult.total} 人：提交成功 ${operationResult.submitted_count} 人${activeTask.action === 'medical_enrollment' ? `，平台已参保 ${operationResult.existing_count ?? 0} 人` : ''}，结果待确认 ${operationResult.unknown_count} 人，失败或未执行 ${operationResult.total - operationResult.submitted_count - (operationResult.existing_count ?? 0) - operationResult.unknown_count} 人。`} />}
        {task.data?.error && <Alert type="error" showIcon message={task.data.error} />}
        {progressStates.isError && <Alert type="error" message="办理状态加载失败，请人工核对结果，勿重复提交" />}
        <Table size="small" rowKey="person_key" pagination={false} dataSource={progressStates.data?.people.filter((item) => item.operation === (activeTask.action === 'medical_termination' ? 'medical_termination' : activeTask.action === 'medical_enrollment' ? 'medical_enrollment' : 'termination')) ?? []} columns={[
          { title: '姓名', dataIndex: 'name' }, { title: activeTask.action === 'medical_enrollment' ? '参保状态' : '退保状态', dataIndex: 'status', render: (value) => <Tag color={value === 'succeeded' ? 'green' : value === 'unknown' ? 'orange' : 'blue'}>{stateLabels[value] ?? value}</Tag> }, { title: '结果说明', dataIndex: 'message' },
        ]} />
        <Typography.Title level={5}>执行日志</Typography.Title>
        {logs.isError && <Alert type="warning" message="执行日志加载失败" />}
        <div style={{ maxHeight: 240, overflow: 'auto' }}>{logs.data?.map((item, index) => <Typography.Paragraph key={index} style={{ marginBottom: 6 }}>{dayjs(item.created_at).format('HH:mm:ss')}　{item.message}</Typography.Paragraph>)}</div>
      </Modal>}
    </div>
  )
}
