import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircleOutlined,
  CloudDownloadOutlined,
  CloseCircleOutlined,
  DownloadOutlined,
  EditOutlined,
  FileExcelOutlined,
  FilePdfOutlined,
  FileSearchOutlined,
  IssuesCloseOutlined,
  LeftOutlined,
  LoadingOutlined,
  RightOutlined,
  StopOutlined,
  UploadOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  Alert, Button, Card, DatePicker, Empty, Form, Input, Modal,
  Progress, Radio, Select, Space, Statistic, Switch, Table, Tabs, Tag,
  Typography, Upload, message,
} from 'antd'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import { PageTitle } from '../components/PageTitle'
import type { ErpApplicationPreview, RightsImportPreview, RightsIssue, RightsPrintGroup, RightsRecordDetail, TaskRecord } from '../types'
import { projectPrintGroups } from '../utils/rights'

const TRANSACTION_TYPES = ['社保咨询', '工资咨询', '证实咨询', '福利咨询', '合同咨询', '档案咨询', '项目社保申请挂靠', '其他咨询']
const STATUS_OPTIONS = [
  { value: 0, label: '新增' }, { value: 15, label: '待送审' },
  { value: 20, label: '审批中' }, { value: 35, label: '生效' },
  { value: 40, label: '终止' }, { value: 50, label: '批准' },
]

interface ErpQueryValues {
  account_id: number
  transaction_type: string
  statuses: number[]
  application_code: string
  date_range?: [Dayjs, Dayjs]
}

export function RightsPage() {
  const navigate = useNavigate()
  const [erpForm] = Form.useForm<ErpQueryValues>()
  const [preview, setPreview] = useState<RightsImportPreview | null>(null)
  const [accountId, setAccountId] = useState<number>()
  const [mode, setMode] = useState<'individual' | 'batch'>('individual')
  const [batchSize, setBatchSize] = useState(50)
  const [uploadToErp, setUploadToErp] = useState(false)
  const [erpModalOpen, setErpModalOpen] = useState(false)
  const [progressModalOpen, setProgressModalOpen] = useState(false)
  const [extractionTaskId, setExtractionTaskId] = useState<string | null>(null)
  const [rightsTaskId, setRightsTaskId] = useState<string | null>(null)
  const [rightsProgressOpen, setRightsProgressOpen] = useState(false)
  const [activePreviewTab, setActivePreviewTab] = useState('people')
  const [resolutionIssue, setResolutionIssue] = useState<RightsIssue | null>(null)
  const [editingGroup, setEditingGroup] = useState<RightsPrintGroup | null>(null)
  const [editingRowNumber, setEditingRowNumber] = useState<number | null>(null)
  const handledTask = useRef<string | null>(null)

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const rightsAccounts = useMemo(
    () => (accounts.data ?? []).filter((item) => item.system_type === 'JSHRSS' && item.ready),
    [accounts.data],
  )
  const erpAccounts = useMemo(
    () => (accounts.data ?? []).filter((item) => item.system_type === 'ERP' && item.ready),
    [accounts.data],
  )

  useEffect(() => {
    if (!settings.data) return
    setMode(settings.data.export_mode)
    setBatchSize(settings.data.batch_size)
    setUploadToErp(settings.data.upload_to_erp)
  }, [settings.data])
  useEffect(() => {
    if (accountId === undefined && rightsAccounts.length) {
      setAccountId((rightsAccounts.find((item) => item.is_default) ?? rightsAccounts[0]).id)
    }
  }, [accountId, rightsAccounts])
  useEffect(() => {
    if (!erpAccounts.length) return
    const preferred = (erpAccounts.find((item) => item.is_default) ?? erpAccounts[0]).id
    if (!erpForm.getFieldValue('account_id')) erpForm.setFieldValue('account_id', preferred)
  }, [erpAccounts, erpForm])

  const extractionTask = useQuery({
    queryKey: ['task', extractionTaskId],
    queryFn: () => api.task(extractionTaskId as string),
    enabled: Boolean(extractionTaskId),
    refetchInterval: (query) => {
      const task = query.state.data
      return task && ['succeeded', 'failed', 'cancelled'].includes(task.status) ? false : 1000
    },
  })
  const rightsTask = useQuery({
    queryKey: ['task', rightsTaskId],
    queryFn: () => api.task(rightsTaskId as string),
    enabled: Boolean(rightsTaskId),
    refetchInterval: (query) => {
      const task = query.state.data
      return task && ['succeeded', 'failed', 'cancelled'].includes(task.status) ? false : 1000
    },
  })
  useEffect(() => {
    const task = extractionTask.data
    if (!task || handledTask.current === task.task_id) return
    if (task.status === 'succeeded') {
      const result = task.result as { preview?: RightsImportPreview } | null
      if (!result?.preview) message.error('ERP 申请解析已结束，但没有返回可预览的数据')
      else {
        setPreview(result.preview)
        setActivePreviewTab(result.preview.issues?.length ? 'issues' : result.preview.print_groups?.length ? 'groups' : 'people')
      }
      handledTask.current = task.task_id
    } else if (task.status === 'failed') {
      handledTask.current = task.task_id
    } else if (task.status === 'cancelled') {
      handledTask.current = task.task_id
    }
  }, [extractionTask.data])

  const importer = useMutation({
    mutationFn: api.importRights,
    onSuccess: (result) => {
      setPreview(result)
      setUploadToErp(false)
      setActivePreviewTab(result.print_groups?.length ? 'groups' : 'people')
      message.success(`已读取 ${result.record_count} 人，共 ${result.group_count} 个打印组`)
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  const extractor = useMutation({
    mutationFn: api.extractErpRights,
    onSuccess: (task) => {
      handledTask.current = null
      setExtractionTaskId(task.task_id)
      setErpModalOpen(false)
      setProgressModalOpen(true)
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  const starter = useMutation({
    mutationFn: api.startRightsTask,
    onSuccess: (task) => {
      setRightsTaskId(task.task_id)
      setRightsProgressOpen(true)
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  const extractionCanceller = useMutation({
    mutationFn: api.cancelTask,
    onSuccess: (task) => message.info(task.message),
    onError: (error) => message.error(errorMessage(error)),
  })
  const rightsCanceller = useMutation({
    mutationFn: api.cancelTask,
    onSuccess: (task) => message.info(task.message),
    onError: (error) => message.error(errorMessage(error)),
  })

  const issues = preview?.issues ?? []
  const blockingIssueCount = issues.filter((item) => ['error', 'pending'].includes(item.level)).length
  const canExecute = Boolean(preview && preview.record_count > 0 && preview.executable !== false && blockingIssueCount === 0)
  const estimatedPdfCount = useMemo(() => {
    if (!preview) return 0
    if (mode === 'individual') return preview.record_count
    if (preview.print_groups?.length) return preview.print_groups.length
    return preview.estimated_pdf_count ?? preview.group_count
  }, [preview, mode])
  const displayedPrintGroups = useMemo(() => {
    return projectPrintGroups(preview?.print_groups ?? [], mode)
  }, [preview, mode])

  const startExtraction = (values: ErpQueryValues) => {
    extractor.mutate({
      account_id: values.account_id,
      transaction_type: values.transaction_type,
      statuses: values.statuses ?? [],
      application_code: values.application_code ?? '',
      start_date: values.date_range?.[0]?.format('YYYY-MM-DD') ?? '',
      end_date: values.date_range?.[1]?.format('YYYY-MM-DD') ?? '',
      page_size: 50,
      reasoning_mode: '',
    })
  }

  return (
    <div className="page-stack rights-page">
      <div className="rights-page-header">
        <PageTitle title="单位权益单获取" description="从 ERP 获取申请信息或临时导入 Excel，核对人员与问题后生成权益单" />
        <Space wrap>
          <Button type="primary" icon={<FileSearchOutlined />} onClick={() => setErpModalOpen(true)}>获取申请信息</Button>
          <Button icon={<CloudDownloadOutlined />} href="/api/v1/rights/template">下载 Excel 模板</Button>
          <Upload
            accept=".xlsx,.xlsm" maxCount={1} showUploadList={false}
            customRequest={({ file, onSuccess, onError }) => {
              importer.mutate(file as File, {
                onSuccess: () => onSuccess?.({}),
                onError: (error) => onError?.(error as Error),
              })
            }}
          >
            <Button icon={<UploadOutlined />} loading={importer.isPending}>导入 Excel</Button>
          </Upload>
        </Space>
      </div>

      <div className="rights-workbench-grid">
        <Card className="content-card rights-preview-card" title="申请人员与问题">
          {!preview ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无数据，请获取 ERP 申请信息或导入 Excel">
              <Button type="primary" onClick={() => setErpModalOpen(true)}>获取申请信息</Button>
            </Empty>
          ) : (
            <>
              <div className="rights-summary-row">
                <Statistic title="涉及人员" value={preview.unique_person_count ?? preview.record_count} suffix="人" prefix={<UserOutlined />} />
                <Statistic title={mode === 'batch' ? '打印组' : '单独权益单'} value={displayedPrintGroups.length} suffix="组" prefix={<FileExcelOutlined />} />
                <Statistic title="需处理问题" value={issues.filter((item) => item.level !== 'info').length} suffix="项" prefix={<IssuesCloseOutlined />} valueStyle={blockingIssueCount ? { color: '#cf1322' } : undefined} />
                <div className="rights-source-name">
                  <Typography.Text type="secondary">数据来源</Typography.Text>
                  <Typography.Text strong>{preview.source === 'erp' ? 'ERP 申请解析' : preview.filename}</Typography.Text>
                </div>
              </div>
              {blockingIssueCount > 0 && (
                <Alert type="warning" showIcon message={`有 ${blockingIssueCount} 项问题会阻止执行`} description="请在“问题信息”中查看具体申请、人员和原因。处理后重新获取申请信息或修正 Excel。" className="rights-inline-alert" />
              )}
              <Tabs
                activeKey={activePreviewTab} onChange={setActivePreviewTab}
                items={[
                  ...(preview.print_groups?.length ? [{ key: 'groups', label: `${mode === 'batch' ? '打印组' : '单独权益单'}（${displayedPrintGroups.length}）`, children: <PrintGroupsTable groups={displayedPrintGroups} source={preview.source} individualView={mode === 'individual'} onShowIssues={() => setActivePreviewTab('issues')} onEditGroup={setEditingGroup} onEditPerson={setEditingRowNumber} /> }] : []),
                  { key: 'people', label: `人员明细（${preview.record_count}）`, children: <PeopleTable preview={preview} onShowIssues={() => setActivePreviewTab('issues')} onEditPerson={setEditingRowNumber} /> },
                  { key: 'issues', label: `问题信息（${issues.length}）`, children: <IssuesTable issues={issues} onResolve={setResolutionIssue} /> },
                  ...(preview.applications?.length ? [{ key: 'applications', label: `ERP 申请（${preview.applications.length}）`, children: <ApplicationsTable applications={preview.applications} /> }] : []),
                ]}
              />
            </>
          )}
        </Card>

        <Card className="content-card rights-settings-card" title="执行设置">
          <Form layout="vertical">
            <Form.Item label="智慧人社账号" required>
              <Select value={accountId} placeholder="请先在系统设置中维护账号" options={rightsAccounts.map((item) => ({ value: item.id, label: `${item.display_name} · ${item.masked_account}` }))} onChange={setAccountId} />
            </Form.Item>
            <Form.Item label="导出方式">
              <Radio.Group value={mode} onChange={(event) => setMode(event.target.value)} className="rights-export-modes">
                <Radio.Button value="batch">按打印组</Radio.Button>
                <Radio.Button value="individual">每人单独一份</Radio.Button>
              </Radio.Group>
              {preview && (
                <div className="rights-pdf-estimate">
                  预计生成 <strong>{estimatedPdfCount}</strong> 份权益单
                  {mode === 'batch' && `（${preview.group_count} 个打印组）`}
                </div>
              )}
            </Form.Item>
            <Form.Item label="下载完成后上传 ERP">
              <Space align="start">
                <Switch checked={uploadToErp} disabled={preview?.erp_upload_available === false} onChange={setUploadToErp} />
                <Typography.Text type="secondary">{preview?.erp_upload_available === false ? '存在未填写 ERP申请编号的打印组，不能自动上传 ERP' : uploadToErp ? '下载成功后按 ERP申请编号匹配并上传 PDF' : '仅生成并保留权益单文件'}</Typography.Text>
              </Space>
            </Form.Item>
            {!rightsAccounts.length && <Alert type="warning" showIcon message="尚未配置可用的智慧人社账号" />}
            <Button type="primary" size="large" block disabled={!canExecute || accountId === undefined} loading={starter.isPending} onClick={() => preview && accountId !== undefined && starter.mutate({ import_id: preview.import_id, account_id: accountId, export_mode: mode, batch_size: batchSize, upload_to_erp: uploadToErp })}>获取权益单</Button>
            {preview && !canExecute && <Typography.Text type="secondary" className="rights-disabled-reason">当前数据存在阻塞问题，暂不能开始获取。</Typography.Text>}
          </Form>
        </Card>
      </div>

      <Modal title="从 ERP 获取申请信息" open={erpModalOpen} onCancel={() => setErpModalOpen(false)} onOk={() => erpForm.submit()} confirmLoading={extractor.isPending} okText="开始获取" cancelText="取消" width={720}>
        <Form form={erpForm} layout="vertical" initialValues={{ transaction_type: '社保咨询', statuses: [], application_code: '' }} onFinish={startExtraction}>
          <Form.Item name="account_id" label="ERP 账号" rules={[{ required: true, message: '请先选择 ERP 账号' }]}> 
            <Select placeholder="请先在系统设置中维护 ERP 账号" options={erpAccounts.map((item) => ({ value: item.id, label: `${item.display_name} · ${item.masked_account}` }))} />
          </Form.Item>
          <div className="erp-query-grid">
            <Form.Item name="application_code" label="申请编号"><Input allowClear placeholder="可选，精确查询某一申请" /></Form.Item>
            <Form.Item name="date_range" label="发起日期"><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="transaction_type" label="事务类型" rules={[{ required: true, message: '请选择事务类型' }]}><Select options={TRANSACTION_TYPES.map((value) => ({ value, label: value }))} /></Form.Item>
            <Form.Item name="statuses" label="申请状态"><Select mode="multiple" allowClear options={STATUS_OPTIONS} /></Form.Item>
          </div>
        </Form>
      </Modal>

      <IssueResolutionModal
        open={resolutionIssue !== null}
        issue={resolutionIssue}
        importId={preview?.import_id ?? ''}
        onClose={() => setResolutionIssue(null)}
        onResolved={(updated) => {
          setPreview(updated)
          setResolutionIssue(null)
          setActivePreviewTab(updated.issues?.length ? 'issues' : updated.print_groups?.length ? 'groups' : 'people')
        }}
      />
      <PrintGroupEditModal
        open={editingGroup !== null}
        group={editingGroup}
        importId={preview?.import_id ?? ''}
        onClose={() => setEditingGroup(null)}
        onSaved={(updated) => {
          setPreview(updated)
          setEditingGroup(null)
        }}
      />
      <RecordEditModal
        open={editingRowNumber !== null}
        rowNumber={editingRowNumber}
        importId={preview?.import_id ?? ''}
        onClose={() => setEditingRowNumber(null)}
        onSaved={(updated) => {
          setPreview(updated)
          setEditingRowNumber(null)
        }}
      />

      <ExtractionProgressModal
        open={progressModalOpen}
        task={extractionTask.data}
        loading={extractionTask.isLoading}
        cancelling={extractionCanceller.isPending}
        modelName={settings.data?.active_ai_model ?? ''}
        reasoningMode={settings.data?.active_reasoning_mode ?? ''}
        onCancelTask={() => extractionTaskId && extractionCanceller.mutate(extractionTaskId)}
        onOpenTasks={() => navigate('/tasks')}
        onClose={() => {
          setProgressModalOpen(false)
          setExtractionTaskId(null)
        }}
      />
      <RightsTaskProgressModal
        open={rightsProgressOpen}
        task={rightsTask.data}
        loading={rightsTask.isLoading}
        cancelling={rightsCanceller.isPending}
        onCancelTask={() => rightsTaskId && rightsCanceller.mutate(rightsTaskId)}
        onOpenTasks={() => navigate('/tasks')}
        onClose={() => {
          setRightsProgressOpen(false)
          setRightsTaskId(null)
        }}
      />
    </div>
  )
}

type ManualRecordValues = Omit<RightsRecordDetail, 'row_number' | 'start_month' | 'end_month'> & {
  start_month?: Dayjs
  end_month?: Dayjs
}

function monthText(value?: Dayjs | string | null): string {
  if (!value) return ''
  return typeof value === 'string' ? value : value.format('YYYY-MM')
}

function recordToFormValues(record: RightsRecordDetail): ManualRecordValues {
  return {
    ...record,
    start_month: record.start_month ? dayjs(record.start_month, 'YYYY-MM') : undefined,
    end_month: record.end_month ? dayjs(record.end_month, 'YYYY-MM') : undefined,
  }
}

function IssueResolutionModal({
  open,
  issue,
  importId,
  onClose,
  onResolved,
}: {
  open: boolean
  issue: RightsIssue | null
  importId: string
  onClose: () => void
  onResolved: (preview: RightsImportPreview) => void
}) {
  const [form] = Form.useForm<ManualRecordValues>()
  const candidates = issue?.candidates ?? []
  const hasCandidates = issue?.code === 'ERP_PERSON_AMBIGUOUS' && candidates.length > 0
  const isPrintGroupIssue = issue?.code === 'AI_PRINT_MODE_REQUIRED'
  const isGroupConditionMissing = ['PRINT_GROUP_CONDITION_MISSING', 'AI_DATE_MISSING'].includes(issue?.code ?? '') && Boolean(issue?.group_id)
  const isGroupConditionConflict = issue?.code === 'PRINT_GROUP_CONDITION_CONFLICT' && Boolean(issue.group_id)
  const isGroupConditionIssue = isGroupConditionMissing || isGroupConditionConflict
  const [mode, setMode] = useState<'candidate' | 'manual'>('manual')
  const [groupMode, setGroupMode] = useState<'batch' | 'individual'>('batch')
  const [candidateId, setCandidateId] = useState('')
  const detail = useQuery({
    queryKey: ['rights-record', importId, issue?.row_number],
    queryFn: () => api.rightsRecord(importId, issue?.row_number as number),
    enabled: open && !isPrintGroupIssue && Boolean(importId) && Boolean(issue && issue.row_number > 0),
    retry: false,
  })
  useEffect(() => {
    if (!open || !issue) return
    setMode(hasCandidates ? 'candidate' : 'manual')
    setGroupMode('batch')
    setCandidateId(candidates[0]?.candidate_id ?? '')
    form.resetFields()
    form.setFieldsValue({
      task_number: issue.task_number === '-' ? '' : issue.task_number,
      insurance_type: '养老',
    } as Partial<ManualRecordValues>)
  }, [open, issue?.issue_id])
  useEffect(() => {
    if (detail.data) form.setFieldsValue(recordToFormValues(detail.data))
  }, [detail.data, form])

  const resolver = useMutation({
    mutationFn: async (values?: ManualRecordValues) => {
      if (!issue) throw new Error('需要处理的问题已经失效')
      if (isPrintGroupIssue) {
        return api.resolveRightsPrintGroup(importId, issue.task_number, issue.group_id, groupMode)
      }
      if (isGroupConditionIssue) {
        if (!values) throw new Error('请填写完整的打印组条件')
        return api.resolveRightsPrintGroupConditions(importId, {
          task_number: issue.task_number,
          group_id: issue.group_id,
          insurance_type: values.insurance_type,
          start_month: monthText(values.start_month),
          end_month: monthText(values.end_month),
          overwrite: isGroupConditionConflict,
        })
      }
      if (mode === 'candidate') {
        if (!candidateId) throw new Error('请选择一名 ERP 候选人员')
        return api.selectRightsCandidate(importId, issue.row_number, candidateId)
      }
      if (!values) throw new Error('请填写完整的人员信息')
      const payload = {
        ...values,
        start_month: monthText(values.start_month),
        end_month: monthText(values.end_month),
        task_number: issue.task_number === '-' ? values.task_number : issue.task_number,
      }
      return issue.row_number > 0
        ? api.updateRightsRecord(importId, issue.row_number, payload)
        : api.addRightsRecord(importId, payload)
    },
    onSuccess: (updated) => {
      message.success(
        isPrintGroupIssue
          ? '打印组已确认并重新校验'
          : isGroupConditionConflict
            ? '已将险种和起止月份统一应用到整个打印组'
            : isGroupConditionMissing
              ? '已补充组内空缺条件并重新校验'
            : mode === 'candidate'
              ? '已选择 ERP 人员并重新校验'
              : '人工录入已保存并重新校验',
      )
      onResolved(updated)
    },
    onError: (error) => message.error(errorMessage(error)),
  })

  const canHandle = Boolean(
    issue
      && (issue.row_number > 0 || issue.code === 'AI_NO_PERSON_EXTRACTED'),
  )
  return (
    <Modal
      title={isPrintGroupIssue ? '确认打印组方式' : isGroupConditionConflict ? '统一打印组条件' : isGroupConditionMissing ? '补充打印组条件' : hasCandidates && mode === 'candidate' ? '选择正确的 ERP 人员' : issue?.row_number ? '人工处理人员信息' : '人工新增申请人员'}
      open={open}
      width={760}
      destroyOnHidden
      maskClosable={false}
      onCancel={onClose}
      okText={isPrintGroupIssue ? '确认打印组' : isGroupConditionConflict ? '统一整组条件' : mode === 'candidate' ? '使用选中人员' : '保存人工处理'}
      cancelText="取消"
      confirmLoading={resolver.isPending}
      okButtonProps={{ disabled: !canHandle || (!isPrintGroupIssue && detail.isLoading) || (mode === 'candidate' && !candidateId) }}
      onOk={() => isPrintGroupIssue ? resolver.mutate(undefined) : mode === 'candidate' ? resolver.mutate(undefined) : form.submit()}
    >
      {issue && (
        <Alert
          type="warning"
          showIcon
          message={`${issue.task_number} · ${issue.person_name}`}
          description={issue.details}
          className="rights-resolution-alert"
        />
      )}
      {!canHandle ? (
        <Alert
          type="info"
          showIcon
          message="该问题不能通过修改人员资料解决"
          description="请根据错误信息修复系统服务后重新获取申请，或将不支持的业务转为线下办理。"
        />
      ) : isPrintGroupIssue ? (
        <div className="rights-group-resolution">
          <Typography.Paragraph>当前已将申请中的人员暂时放在同一个打印组，请确认最终人员分组：</Typography.Paragraph>
          <Radio.Group value={groupMode} onChange={(event) => setGroupMode(event.target.value)} optionType="button" buttonStyle="solid">
            <Radio.Button value="batch">确认按当前打印组</Radio.Button>
            <Radio.Button value="individual">每人单独一份</Radio.Button>
          </Radio.Group>
        </div>
      ) : hasCandidates && mode === 'candidate' ? (
        <>
          <Typography.Paragraph type="secondary">ERP 查询到多名同名人员，请根据员工编号、身份证尾号、单位和部门选择正确人员。</Typography.Paragraph>
          <Radio.Group value={candidateId} onChange={(event) => setCandidateId(event.target.value)} className="rights-candidate-list">
            {candidates.map((candidate) => (
              <Radio key={candidate.candidate_id} value={candidate.candidate_id} className="rights-candidate-option">
                <div className="rights-candidate-option__title">
                  <Typography.Text strong>{candidate.name || issue?.person_name}</Typography.Text>
                  {candidate.status && <Tag color={candidate.status.includes('在职') ? 'success' : 'default'}>{candidate.status}</Tag>}
                </div>
                <Typography.Text type="secondary">
                  员工编号：{candidate.employee_code || '未维护'}　身份证：{candidate.masked_identity}
                </Typography.Text>
                <Typography.Text type="secondary">
                  {candidate.company || '单位未维护'} · {candidate.department || '部门未维护'}
                </Typography.Text>
              </Radio>
            ))}
          </Radio.Group>
          <Button type="link" className="rights-manual-switch" onClick={() => setMode('manual')}>候选人员均不正确，改为人工录入</Button>
        </>
      ) : isGroupConditionIssue ? (
        <Form form={form} layout="vertical" onFinish={(values) => resolver.mutate(values)} className="rights-manual-form">
          {(['task_number', 'name', 'identity_number', 'unit', 'department'] as const).map((field) => (
            <Form.Item key={field} name={field} hidden><Input /></Form.Item>
          ))}
          <Alert
            type={isGroupConditionConflict ? 'warning' : 'info'}
            showIcon
            message={isGroupConditionConflict ? '本次保存会统一修改整个打印组' : '本次只补充组内空缺字段'}
            description={isGroupConditionConflict ? '险种、开始月份和结束月份将覆盖该申请编号与打印组下的全部人员。' : '组内已有值不会被覆盖；如果补充值与已有值不同，系统会报告打印组条件不一致，再由你确认是否统一整组。'}
            style={{ marginBottom: 16 }}
          />
          <div className="rights-manual-form__grid">
            <Form.Item name="insurance_type" label="险种" rules={[{ required: true, message: '请选择险种' }]}>
              <Select options={['养老', '工伤', '失业'].map((value) => ({ value, label: value }))} />
            </Form.Item>
            <div />
            <Form.Item name="start_month" label="开始月份" rules={[{ required: true, message: '请选择开始月份' }]}><DatePicker picker="month" format="YYYY-MM" placeholder="选择开始月份" style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="end_month" label="结束月份" rules={[{ required: true, message: '请选择结束月份' }]}><DatePicker picker="month" format="YYYY-MM" placeholder="选择结束月份" style={{ width: '100%' }} /></Form.Item>
          </div>
          {detail.isLoading && <Typography.Text type="secondary">正在读取打印组条件…</Typography.Text>}
        </Form>
      ) : (
        <Form form={form} layout="vertical" onFinish={(values) => resolver.mutate(values)} className="rights-manual-form">
          <Form.Item name="task_number" hidden><Input /></Form.Item>
          <div className="rights-manual-form__grid">
            <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}><Input placeholder="请输入人员姓名" /></Form.Item>
            <Form.Item name="identity_number" label="身份证号" rules={[{ required: true, message: '请输入身份证号' }]}><Input maxLength={18} placeholder="请输入15位或18位身份证号" /></Form.Item>
            <Form.Item name="unit" label="单位" rules={[{ required: true, message: '请输入单位' }]}><Input placeholder="请输入参保单位" /></Form.Item>
            <Form.Item name="department" label="部门" rules={[{ required: true, message: '请输入部门' }]}><Input placeholder="请输入所属部门" /></Form.Item>
            <Form.Item name="insurance_type" label="险种" rules={[{ required: true, message: '请选择险种' }]}>
              <Select options={['养老', '工伤', '失业'].map((value) => ({ value, label: value }))} />
            </Form.Item>
            <div />
            <Form.Item name="start_month" label="开始月份" rules={[{ required: true, message: '请选择开始月份' }]}><DatePicker picker="month" format="YYYY-MM" placeholder="选择开始月份" style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="end_month" label="结束月份" rules={[{ required: true, message: '请选择结束月份' }]}><DatePicker picker="month" format="YYYY-MM" placeholder="选择结束月份" style={{ width: '100%' }} /></Form.Item>
          </div>
          {hasCandidates && <Button type="link" className="rights-manual-switch" onClick={() => setMode('candidate')}>返回候选人员选择</Button>}
          {detail.isLoading && <Typography.Text type="secondary">正在读取原始人员信息…</Typography.Text>}
        </Form>
      )}
    </Modal>
  )
}

interface GroupConditionFormValues {
  insurance_type: string
  start_month?: Dayjs
  end_month?: Dayjs
}

function PrintGroupEditModal({
  open,
  group,
  importId,
  onClose,
  onSaved,
}: {
  open: boolean
  group: RightsPrintGroup | null
  importId: string
  onClose: () => void
  onSaved: (preview: RightsImportPreview) => void
}) {
  const [form] = Form.useForm<GroupConditionFormValues>()
  useEffect(() => {
    if (!open || !group) return
    form.setFieldsValue({
      insurance_type: group.insurance_type,
      start_month: group.start_month ? dayjs(group.start_month, 'YYYY-MM') : undefined,
      end_month: group.end_month ? dayjs(group.end_month, 'YYYY-MM') : undefined,
    })
  }, [open, group, form])
  const saver = useMutation({
    mutationFn: (values: GroupConditionFormValues) => {
      if (!group) throw new Error('打印组已经失效')
      return api.resolveRightsPrintGroupConditions(importId, {
        task_number: group.task_number,
        group_id: group.group_id,
        insurance_type: values.insurance_type,
        start_month: monthText(values.start_month),
        end_month: monthText(values.end_month),
        overwrite: true,
      })
    },
    onSuccess: (updated) => {
      message.success('打印组险种和月份已更新')
      onSaved(updated)
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  return (
    <Modal
      title="编辑打印组条件"
      open={open}
      width={680}
      maskClosable={false}
      destroyOnHidden
      onCancel={onClose}
      onOk={() => form.submit()}
      okText="保存整组信息"
      cancelText="取消"
      confirmLoading={saver.isPending}
    >
      {group && <Alert type="info" showIcon message={`${group.task_number} · ${group.group_label}`} description={`保存后会同步修改该打印组内 ${group.people_count} 名人员的险种和月份。`} style={{ marginBottom: 18 }} />}
      <Form form={form} layout="vertical" onFinish={(values) => saver.mutate(values)}>
        <Form.Item name="insurance_type" label="险种" rules={[{ required: true, message: '请选择险种' }]}>
          <Select options={['养老', '工伤', '失业'].map((value) => ({ value, label: value }))} />
        </Form.Item>
        <div className="rights-manual-form__grid">
          <Form.Item name="start_month" label="开始月份" rules={[{ required: true, message: '请选择开始月份' }]}><DatePicker picker="month" format="YYYY-MM" style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="end_month" label="结束月份" rules={[{ required: true, message: '请选择结束月份' }]}><DatePicker picker="month" format="YYYY-MM" style={{ width: '100%' }} /></Form.Item>
        </div>
      </Form>
    </Modal>
  )
}

function RecordEditModal({
  open,
  rowNumber,
  importId,
  onClose,
  onSaved,
}: {
  open: boolean
  rowNumber: number | null
  importId: string
  onClose: () => void
  onSaved: (preview: RightsImportPreview) => void
}) {
  const [form] = Form.useForm<ManualRecordValues>()
  const detail = useQuery({
    queryKey: ['rights-record-edit', importId, rowNumber],
    queryFn: () => api.rightsRecord(importId, rowNumber as number),
    enabled: open && rowNumber !== null,
    retry: false,
  })
  useEffect(() => {
    if (!open) return
    form.resetFields()
  }, [open, rowNumber, form])
  useEffect(() => {
    if (detail.data) form.setFieldsValue(recordToFormValues(detail.data))
  }, [detail.data, form])
  const saver = useMutation({
    mutationFn: (values: ManualRecordValues) => {
      if (rowNumber === null) throw new Error('人员记录已经失效')
      return api.updateRightsRecord(importId, rowNumber, {
        ...values,
        start_month: monthText(values.start_month),
        end_month: monthText(values.end_month),
      })
    },
    onSuccess: (updated) => {
      message.success('人员信息已更新并重新校验打印组')
      onSaved(updated)
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  return (
    <Modal
      title="编辑人员信息"
      open={open}
      width={820}
      maskClosable={false}
      destroyOnHidden
      onCancel={onClose}
      onOk={() => form.submit()}
      okText="保存并校验"
      cancelText="取消"
      confirmLoading={saver.isPending}
      okButtonProps={{ disabled: detail.isLoading || detail.isError }}
    >
      <Alert type="info" showIcon message="修改后会重新计算打印组" description="人员移入已有打印组时，系统会校验险种和起止月份是否一致；不一致会出现在问题信息中。" style={{ marginBottom: 18 }} />
      <Form form={form} layout="vertical" onFinish={(values) => saver.mutate(values)} className="rights-manual-form">
        <Form.Item name="task_number" hidden><Input /></Form.Item>
        <div className="rights-manual-form__grid">
          <Form.Item name="print_group" label="打印组" rules={[{ required: true, message: '请输入打印组' }]}><Input placeholder="例如：组1" /></Form.Item>
          <Form.Item name="insurance_type" label="险种" rules={[{ required: true, message: '请选择险种' }]}><Select options={['养老', '工伤', '失业'].map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="unit" label="单位" rules={[{ required: true, message: '请输入单位' }]}><Input /></Form.Item>
          <Form.Item name="department" label="部门" rules={[{ required: true, message: '请输入部门' }]}><Input /></Form.Item>
          <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}><Input /></Form.Item>
          <Form.Item name="identity_number" label="身份证号" rules={[{ required: true, message: '请输入身份证号' }]}><Input maxLength={18} /></Form.Item>
          <Form.Item name="start_month" label="开始月份" rules={[{ required: true, message: '请选择开始月份' }]}><DatePicker picker="month" format="YYYY-MM" style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="end_month" label="结束月份" rules={[{ required: true, message: '请选择结束月份' }]}><DatePicker picker="month" format="YYYY-MM" style={{ width: '100%' }} /></Form.Item>
        </div>
      </Form>
    </Modal>
  )
}

function ExtractionProgressModal({
  open,
  task,
  loading,
  cancelling,
  modelName,
  reasoningMode,
  onCancelTask,
  onOpenTasks,
  onClose,
}: {
  open: boolean
  task?: TaskRecord
  loading: boolean
  cancelling: boolean
  modelName: string
  reasoningMode: string
  onCancelTask: () => void
  onOpenTasks: () => void
  onClose: () => void
}) {
  const status = task?.status ?? 'queued'
  const running = ['queued', 'running', 'cancelling'].includes(status)
  const succeeded = status === 'succeeded'
  const failed = status === 'failed'
  const result = task?.result as { preview?: RightsImportPreview } | null | undefined
  const preview = result?.preview
  const percent = Math.round(((task?.progress_current ?? 0) / Math.max(task?.progress_total ?? 1, 1)) * 100)
  const reasoningLabel = reasoningMode === 'off' ? '非思考' : reasoningMode === 'on' ? '思考' : reasoningMode
  const title = running ? '正在获取并解析申请信息' : succeeded ? '申请信息解析完成' : failed ? '申请信息获取失败' : '任务已停止'
  return (
    <Modal
      open={open}
      width={640}
      title={null}
      closable={!running}
      maskClosable={false}
      keyboard={!running}
      onCancel={running ? undefined : onClose}
      footer={running ? [
        <Button key="tasks" onClick={onOpenTasks}>转到任务中心</Button>,
        <Button key="stop" danger icon={<StopOutlined />} loading={cancelling} disabled={status === 'cancelling'} onClick={onCancelTask}>停止任务</Button>,
      ] : [<Button key="close" type="primary" onClick={onClose}>{succeeded ? '查看解析结果' : '关闭'}</Button>]}
    >
      <div className="erp-extraction-progress">
        <div className={`erp-extraction-progress__icon ${succeeded ? 'is-success' : failed ? 'is-error' : ''}`}>
          {running || loading ? <LoadingOutlined spin /> : succeeded ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        </div>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>{title}</Typography.Title>
          <Typography.Text type="secondary">
            {running ? '请保持程序运行，每条申请将按顺序处理。' : succeeded ? '数据已载入当前页面，请核对人员及问题信息。' : '本次任务没有生成可用的申请人员数据。'}
          </Typography.Text>
        </div>
      </div>
      <div className="erp-extraction-progress__detail">
        <Typography.Text type="secondary">解析模型</Typography.Text>
        <Typography.Text strong>{modelName || '当前已配置模型'}{reasoningLabel ? ` · ${reasoningLabel}` : ''}</Typography.Text>
        <Typography.Text type="secondary">当前进度</Typography.Text>
        <Typography.Text>{task?.message || '正在创建任务并等待调度'}</Typography.Text>
      </div>
      {running && (
        <div className="erp-extraction-progress__bar">
          <div className="erp-extraction-progress__bar-label">
            <Typography.Text>解析进度</Typography.Text>
            <Typography.Text type="secondary">{task?.progress_current ?? 0} / {task?.progress_total ?? 1}</Typography.Text>
          </div>
          <Progress percent={percent} status="active" showInfo={false} />
        </div>
      )}
      {succeeded && preview && (
        <Alert
          type={preview.record_count ? 'success' : 'warning'}
          showIcon
          message={`已获取 ${preview.unique_person_count ?? preview.record_count} 名人员、${preview.group_count} 个打印组`}
          description={preview.issues?.length ? `发现 ${preview.issues.length} 项问题，请在页面中核对处理。` : '未发现阻塞问题。'}
        />
      )}
      {failed && <Alert type="error" showIcon message="未能获取申请信息" description={task?.error || '任务执行失败，请检查查询条件后重试。'} />}
      {status === 'cancelled' && <Alert type="warning" showIcon message="任务已停止" description={task?.message} />}
    </Modal>
  )
}

interface ResultArtifact {
  name: string
  url: string
}

function RightsTaskProgressModal({
  open,
  task,
  loading,
  cancelling,
  onCancelTask,
  onOpenTasks,
  onClose,
}: {
  open: boolean
  task?: TaskRecord
  loading: boolean
  cancelling: boolean
  onCancelTask: () => void
  onOpenTasks: () => void
  onClose: () => void
}) {
  const status = task?.status ?? 'queued'
  const running = ['queued', 'running', 'cancelling'].includes(status)
  const succeeded = status === 'succeeded'
  const failed = status === 'failed'
  const result = taskResult(task?.result)
  const artifacts = resultArtifacts(task?.result)
  const archive = resultArchive(task?.result)
  const pdfs = artifacts.filter((item) => item.name.toLowerCase().endsWith('.pdf'))
  const [selectedPdfUrl, setSelectedPdfUrl] = useState('')
  useEffect(() => {
    if (!open) return
    setSelectedPdfUrl((current) => pdfs.some((item) => item.url === current) ? current : (pdfs[0]?.url ?? ''))
  }, [open, task?.task_id, pdfs.map((item) => item.url).join('|')])
  const selectedPdfIndex = Math.max(0, pdfs.findIndex((item) => item.url === selectedPdfUrl))
  const selectAdjacentPdf = (offset: number) => {
    const next = pdfs[selectedPdfIndex + offset]
    if (next) setSelectedPdfUrl(next.url)
  }
  const percent = Math.round(((task?.progress_current ?? 0) / Math.max(task?.progress_total ?? 1, 1)) * 100)
  const title = running ? '正在获取权益单' : succeeded ? '权益单获取完成' : failed ? '权益单获取失败' : '任务已停止'
  return (
    <Modal
      open={open}
      centered
      className={`rights-result-modal ${succeeded && pdfs.length ? 'rights-result-modal--preview' : ''}`}
      wrapClassName="rights-result-modal-wrap"
      width={succeeded && pdfs.length ? 'min(1100px, 94vw)' : 680}
      title={null}
      closable={!running}
      maskClosable={false}
      keyboard={!running}
      onCancel={running ? undefined : onClose}
      footer={running ? [
        <Button key="tasks" onClick={onOpenTasks}>转到任务中心</Button>,
        <Button key="stop" danger icon={<StopOutlined />} loading={cancelling} disabled={status === 'cancelling'} onClick={onCancelTask}>停止任务</Button>,
      ] : [
        <Button key="tasks" onClick={onOpenTasks}>任务中心</Button>,
        <Button key="close" type="primary" onClick={onClose}>关闭</Button>,
      ]}
    >
      <div className="erp-extraction-progress">
        <div className={`erp-extraction-progress__icon ${succeeded ? 'is-success' : failed ? 'is-error' : ''}`}>
          {running || loading ? <LoadingOutlined spin /> : succeeded ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        </div>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>{title}</Typography.Title>
          <Typography.Text type="secondary">{task?.message || '正在创建任务并等待调度'}</Typography.Text>
        </div>
      </div>
      {running && (
        <div className="erp-extraction-progress__bar">
          <div className="erp-extraction-progress__bar-label">
            <Typography.Text>处理进度</Typography.Text>
            <Typography.Text type="secondary">{task?.progress_current ?? 0} / {task?.progress_total ?? 1}</Typography.Text>
          </div>
          <Progress percent={percent} status="active" showInfo={false} />
        </div>
      )}
      {failed && <Alert type="error" showIcon message="权益单获取失败" description={task?.error || '任务执行失败，请检查错误信息后重试。'} />}
      {status === 'cancelled' && <Alert type="warning" showIcon message="任务已停止" description={task?.message} />}
      {succeeded && (
        <>
          <div className={`rights-result-summary ${result.failed ? 'has-warning' : ''}`}>
            <CheckCircleOutlined />
            <div>
              <Typography.Text strong>成功 {result.succeeded} 项，失败 {result.failed} 项</Typography.Text>
              <Typography.Text type="secondary">{result.erp_message || result.erp_warning || (pdfs.length ? '可预览单份 PDF，完整结果请下载压缩包' : '本次任务没有生成可预览的 PDF')}</Typography.Text>
            </div>
            {archive && (
              <Button type="primary" icon={<DownloadOutlined />} href={archive.url}>
                下载全部结果（ZIP）
              </Button>
            )}
          </div>
          {pdfs.length > 0 ? (
            <div className="rights-pdf-preview">
              <div className="rights-pdf-preview__viewer">
                <div className="rights-pdf-preview__toolbar">
                  <div className="rights-pdf-preview__picker">
                    {pdfs.length > 1 && (
                      <Space.Compact className="rights-pdf-preview__navigation">
                        <Button
                          aria-label="上一份权益单"
                          icon={<LeftOutlined />}
                          disabled={selectedPdfIndex === 0}
                          onClick={() => selectAdjacentPdf(-1)}
                        />
                        <Button className="rights-pdf-preview__counter" disabled>
                          第 {selectedPdfIndex + 1} 份 / 共 {pdfs.length} 份
                        </Button>
                        <Button
                          aria-label="下一份权益单"
                          icon={<RightOutlined />}
                          disabled={selectedPdfIndex >= pdfs.length - 1}
                          onClick={() => selectAdjacentPdf(1)}
                        />
                      </Space.Compact>
                    )}
                    <Select
                      aria-label="选择权益单文件"
                      value={selectedPdfUrl}
                      onChange={setSelectedPdfUrl}
                      className="rights-pdf-preview__select"
                      options={pdfs.map((artifact, index) => ({
                        value: artifact.url,
                        label: pdfs.length > 1 ? `${index + 1}. ${artifact.name}` : artifact.name,
                      }))}
                      suffixIcon={<FilePdfOutlined />}
                    />
                  </div>
                  <Button icon={<DownloadOutlined />} href={selectedPdfUrl}>下载当前 PDF</Button>
                </div>
                {selectedPdfUrl && <iframe title="权益单 PDF 预览" src={`${selectedPdfUrl}?preview=true#view=FitH`} />}
              </div>
            </div>
          ) : artifacts.length > 0 ? (
            <Space direction="vertical" style={{ width: '100%' }}>
              {artifacts.map((artifact) => <Button key={artifact.url} icon={<DownloadOutlined />} href={artifact.url}>{artifact.name}</Button>)}
            </Space>
          ) : null}
        </>
      )}
    </Modal>
  )
}

function resultArtifacts(value: unknown): ResultArtifact[] {
  if (!value || typeof value !== 'object' || !('artifacts' in value)) return []
  const artifacts = (value as { artifacts?: unknown }).artifacts
  if (!Array.isArray(artifacts)) return []
  return artifacts.filter(
    (item): item is ResultArtifact => Boolean(item)
      && typeof item === 'object'
      && typeof (item as { name?: unknown }).name === 'string'
      && typeof (item as { url?: unknown }).url === 'string',
  )
}

function resultArchive(value: unknown): ResultArtifact | null {
  if (!value || typeof value !== 'object' || !('archive' in value)) return null
  const archive = (value as { archive?: unknown }).archive
  if (!archive || typeof archive !== 'object') return null
  if (typeof (archive as { name?: unknown }).name !== 'string') return null
  if (typeof (archive as { url?: unknown }).url !== 'string') return null
  return archive as ResultArtifact
}

function taskResult(value: unknown): { succeeded: number; failed: number; erp_message?: string; erp_warning?: string } {
  if (!value || typeof value !== 'object') return { succeeded: 0, failed: 0 }
  const result = value as Record<string, unknown>
  return {
    succeeded: Number(result.succeeded ?? 0),
    failed: Number(result.failed ?? 0),
    erp_message: typeof result.erp_message === 'string' ? result.erp_message : undefined,
    erp_warning: typeof result.erp_warning === 'string' ? result.erp_warning : undefined,
  }
}

function PrintGroupsTable({
  groups,
  source,
  individualView,
  onShowIssues,
  onEditGroup,
  onEditPerson,
}: {
  groups: Array<RightsPrintGroup & { view_key?: string }>
  source?: 'excel' | 'erp'
  individualView: boolean
  onShowIssues: () => void
  onEditGroup: (group: RightsPrintGroup) => void
  onEditPerson: (rowNumber: number) => void
}) {
  return (
    <Table
      rowKey={(record) => record.view_key ?? `${record.task_number}:${record.group_id}`}
      size="small"
      dataSource={groups}
      scroll={{ x: 1050, y: 440 }}
      pagination={{ pageSize: 12, showTotal: (total) => `共 ${total} 个打印组` }}
      expandable={{
        expandedRowRender: (group) => (
          <Table
            rowKey={(person) => `${group.group_id}:${person.row_number}`}
            size="small"
            pagination={false}
            dataSource={group.people}
            columns={[
              { title: '姓名', dataIndex: 'name', width: 110 },
              { title: '身份证号', dataIndex: 'identity_number', width: 210 },
              { title: '单位', dataIndex: 'unit', ellipsis: true },
              { title: '部门', dataIndex: 'department', width: 180, ellipsis: true },
              ...(source === 'erp' ? [{ title: '操作', width: 88, render: (_: unknown, person: RightsPrintGroup['people'][number]) => <Button type="link" size="small" icon={<EditOutlined />} onClick={() => onEditPerson(person.row_number)}>编辑</Button> }] : []),
            ]}
          />
        ),
      }}
      columns={[
        {
          title: '状态', width: 94, fixed: 'left',
          render: (_, record) => record.status === 'error'
            ? <Tag color="error" onClick={onShowIssues}>有问题 {record.issue_count || ''}</Tag>
            : record.status === 'warning'
              ? <Tag color="warning" onClick={onShowIssues}>待复核 {record.issue_count || ''}</Tag>
              : <Tag color="success">正常</Tag>,
        },
        ...(source === 'erp' || groups.some((group) => group.task_number)
          ? [{ title: 'ERP申请编号', dataIndex: 'task_number', width: 190 }]
          : []),
        { title: '打印组', dataIndex: 'group_label', width: 110 },
        {
          title: '组内人员', width: 230,
          render: (_, record) => (
            <Space size={[4, 4]} wrap>
              {record.people.map((person) => <Tag key={`${record.group_id}:${person.row_number}`}>{person.name || '未识别姓名'}</Tag>)}
            </Space>
          ),
        },
        { title: '人数', dataIndex: 'people_count', width: 74, render: (value) => `${value} 人` },
        { title: '险种', dataIndex: 'insurance_type', width: 80 },
        { title: '开始月份', dataIndex: 'start_month', width: 110 },
        { title: '结束月份', dataIndex: 'end_month', width: 110 },
        ...(source === 'erp' ? [{
          title: '操作', width: 110, fixed: 'right' as const,
          render: (_: unknown, record: RightsPrintGroup) => (
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => individualView ? onEditPerson(record.people[0].row_number) : onEditGroup(record)}>
              {individualView ? '编辑人员' : '编辑整组'}
            </Button>
          ),
        }] : []),
      ]}
    />
  )
}

function PeopleTable({ preview, onShowIssues, onEditPerson }: { preview: RightsImportPreview; onShowIssues: () => void; onEditPerson: (rowNumber: number) => void }) {
  return <Table rowKey="row_number" size="small" dataSource={preview.records} scroll={{ x: 1180, y: 480 }} pagination={{ pageSize: 15, showSizeChanger: true, showTotal: (total) => `共 ${total} 人` }} columns={[
    { title: '状态', width: 92, fixed: 'left', render: (_, record) => record.status === 'error' ? <Tag color="error" onClick={onShowIssues}>有问题 {record.issue_count || ''}</Tag> : record.status === 'warning' ? <Tag color="warning" onClick={onShowIssues}>待复核 {record.issue_count || ''}</Tag> : <Tag color="success">正常</Tag> },
    { title: '打印组', dataIndex: 'print_group', width: 100 },
    ...(preview.source === 'erp' || preview.records.some((record) => record.task_number)
      ? [{ title: 'ERP申请编号', dataIndex: 'task_number', width: 190 }]
      : []),
    { title: '单位', dataIndex: 'unit', width: 210, ellipsis: true }, { title: '部门', dataIndex: 'department', width: 160, ellipsis: true },
    { title: '姓名', dataIndex: 'name', width: 100 }, { title: '身份证号', dataIndex: 'identity_number', width: 200 },
    { title: '险种', dataIndex: 'insurance_type', width: 80 }, { title: '开始月份', dataIndex: 'start_month', width: 110 }, { title: '结束月份', dataIndex: 'end_month', width: 110 },
    ...(preview.source === 'erp' ? [{ title: '操作', width: 88, fixed: 'right' as const, render: (_: unknown, record: RightsImportPreview['records'][number]) => <Button type="link" size="small" icon={<EditOutlined />} onClick={() => onEditPerson(record.row_number)}>编辑</Button> }] : []),
  ]} />
}

function IssuesTable({ issues, onResolve }: { issues: RightsIssue[]; onResolve: (issue: RightsIssue) => void }) {
  if (!issues.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有发现问题" />
  return <Table className="rights-issues-table" rowKey="issue_id" size="small" dataSource={issues} scroll={{ x: 1040, y: 'max(240px, calc(100vh - 700px))' }} pagination={{ defaultPageSize: 10, pageSizeOptions: [10, 15, 30, 50], showSizeChanger: true, showQuickJumper: true, showTotal: (total, range) => `第 ${range[0]}-${range[1]} 项，共 ${total} 项` }} columns={[
    { title: '级别', dataIndex: 'level_label', width: 90, render: (value, record) => <Tag color={issueColor(record.level)}>{value}</Tag> },
    { title: '申请编号', dataIndex: 'task_number', width: 190 }, { title: '人员', dataIndex: 'person_name', width: 100 },
    { title: '问题', dataIndex: 'message', width: 190 }, { title: '详细说明', dataIndex: 'details' },
    {
      title: '操作', width: 110, fixed: 'right',
      render: (_, record) => {
        const actionable = record.row_number > 0 || record.code === 'AI_NO_PERSON_EXTRACTED'
        if (!actionable) return <Typography.Text type="secondary">重新获取</Typography.Text>
        const label = record.code === 'ERP_PERSON_AMBIGUOUS' && record.candidates?.length
          ? '选择人员'
          : record.row_number > 0 ? '人工处理' : '人工新增'
        return <Button type="link" onClick={() => onResolve(record)}>{label}</Button>
      },
    },
  ]} />
}

function ApplicationsTable({ applications }: { applications: ErpApplicationPreview[] }) {
  return <Table rowKey={(record) => `${record.sequence}-${record.task_number}`} size="small" dataSource={applications} scroll={{ x: 900, y: 460 }} expandable={{ expandedRowRender: (record) => <div className="erp-application-description"><Typography.Text strong>问题描述</Typography.Text><Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{record.description || '未填写问题描述'}</Typography.Paragraph></div> }} pagination={{ pageSize: 12, showTotal: (total) => `共 ${total} 条申请` }} columns={[
    { title: '申请编号', dataIndex: 'task_number', width: 190 }, { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '状态', dataIndex: 'status_label', width: 120 }, { title: '发起人', dataIndex: 'originator', width: 110 },
    { title: '部门', dataIndex: 'department', width: 150, ellipsis: true }, { title: '问题', dataIndex: 'issue_count', width: 90, render: (value) => value ? <Tag color="error">{value} 项</Tag> : <Tag color="success">正常</Tag> },
  ]} />
}

function issueColor(level: RightsIssue['level']) {
  if (level === 'error') return 'error'
  if (level === 'pending') return 'processing'
  if (level === 'warning') return 'warning'
  return 'default'
}
