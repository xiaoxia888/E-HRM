import { useEffect, useMemo, useState } from 'react'
import {
  ApiOutlined, ClearOutlined, ClockCircleOutlined, EditOutlined,
  FolderOpenOutlined, InfoCircleOutlined, RobotOutlined, SaveOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import {
  Alert, Button, Card, Col, Descriptions, Form, Input, InputNumber, Menu,
  Modal, Radio, Row, Select, Space, Switch, Table, Tag, Typography, message,
} from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import { PageTitle } from '../components/PageTitle'
import type { AccountSummary, WebPreferences } from '../types'

type EditablePreferences = Omit<WebPreferences, 'ai_model_options' | 'active_ai_model' | 'active_reasoning_mode' | 'runtime_path' | 'logs_path' | 'version'>
type SettingsSection = 'accounts' | 'downloads' | 'automation' | 'models' | 'maintenance' | 'about'

const SECTION_INFO: Record<SettingsSection, { title: string; description: string }> = {
  accounts: { title: '账户与连接', description: '维护智慧人社、ERP 与 NocoBase 登录信息' },
  downloads: { title: '下载与任务', description: '配置权益单导出规则、保存位置和后续处理方式' },
  automation: { title: '自动化设置', description: '根据网络环境调整页面操作节奏和等待上限' },
  models: { title: '模型配置', description: '选择 ERP 申请解析使用的本地大模型与推理模式' },
  maintenance: { title: '系统维护', description: '查看服务端数据位置并清理可安全删除的临时文件' },
  about: { title: '关于软件', description: '查看当前 Web 工作台版本与运行说明' },
}

export function SettingsPage() {
  const [form] = Form.useForm<EditablePreferences>()
  const [activeSection, setActiveSection] = useState<SettingsSection>('accounts')
  const [editingSystem, setEditingSystem] = useState<AccountSummary['system_type'] | null>(null)
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const selectedModelId = Form.useWatch('ai_model_profile', form)

  useEffect(() => {
    if (settings.data) {
      const {
        ai_model_options: _options,
        active_ai_model: _activeModel,
        active_reasoning_mode: _activeReasoning,
        runtime_path: _runtimePath,
        logs_path: _logsPath,
        version: _version,
        ...editable
      } = settings.data
      form.setFieldsValue(editable)
    }
  }, [form, settings.data])

  const savePreferences = useMutation({
    mutationFn: api.savePreferences,
    onSuccess: (result) => {
      message.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  const clearTemporary = useMutation({
    mutationFn: api.clearTemporaryFiles,
    onSuccess: (result) => message.success(result.message),
    onError: (error) => message.error(errorMessage(error)),
  })
  const accountRows = useMemo(() => {
    const labels = { JSHRSS: '江苏智慧人社', ERP: 'ERP', NOCOBASE: 'NocoBase' }
    return (['JSHRSS', 'ERP', 'NOCOBASE'] as const).map((systemType) => ({
      systemType, systemName: labels[systemType],
      current: (accounts.data ?? []).find((item) => item.system_type === systemType),
    }))
  }, [accounts.data])
  const selectedModel = (settings.data?.ai_model_options ?? []).find((item) => item.value === selectedModelId)
    ?? (settings.data?.ai_model_options ?? []).find((item) => item.value === settings.data?.active_ai_model)
  const section = SECTION_INFO[activeSection]
  const save = () => savePreferences.mutate(form.getFieldsValue(true) as EditablePreferences)

  return (
    <div className="page-stack settings-page">
      <PageTitle title="系统设置" description="统一管理账户、任务规则、自动化节奏和模型配置" />
      <Card className="content-card" styles={{ body: { padding: 0 } }}>
        <div className="settings-workspace">
          <aside className="settings-nav">
            <Typography.Text className="settings-nav-label">设置分类</Typography.Text>
            <Menu
              mode="inline" selectedKeys={[activeSection]}
              onClick={({ key }) => setActiveSection(key as SettingsSection)}
              items={[
                { key: 'accounts', icon: <ApiOutlined />, label: '账户与连接' },
                { key: 'downloads', icon: <FolderOpenOutlined />, label: '下载与任务' },
                { key: 'automation', icon: <ClockCircleOutlined />, label: '自动化设置' },
                { key: 'models', icon: <RobotOutlined />, label: '模型配置' },
                { key: 'maintenance', icon: <SettingOutlined />, label: '系统维护' },
                { key: 'about', icon: <InfoCircleOutlined />, label: '关于软件' },
              ]}
            />
          </aside>
          <main className="settings-content">
            <div className="settings-content-header">
              <Typography.Title level={3}>{section.title}</Typography.Title>
              <Typography.Text type="secondary">{section.description}</Typography.Text>
            </div>
            <Form form={form} layout="vertical">
              {activeSection === 'accounts' && (
                <AccountsSection rows={accountRows} loading={accounts.isLoading} onEdit={setEditingSystem} />
              )}
              {activeSection === 'downloads' && <DownloadsSection />}
              {activeSection === 'automation' && <AutomationSection />}
              {activeSection === 'models' && (
                <ModelsSection
                  settings={settings.data}
                  selectedModel={selectedModel}
                  onSelect={(value) => {
                    const model = settings.data?.ai_model_options.find((item) => item.value === value)
                    form.setFieldValue('ai_model_profile', value)
                    const currentMode = form.getFieldValue('ai_reasoning_mode')
                    if (model && !model.reasoning_modes.includes(currentMode)) form.setFieldValue('ai_reasoning_mode', model.default_reasoning_mode)
                  }}
                />
              )}
              {activeSection === 'maintenance' && (
                <MaintenanceSection settings={settings.data} clearing={clearTemporary.isPending} onClear={() => clearTemporary.mutate()} />
              )}
              {activeSection === 'about' && <AboutSection settings={settings.data} />}
              {['downloads', 'automation', 'models'].includes(activeSection) && (
                <div className="settings-action-row">
                  <Button type="primary" size="large" icon={<SaveOutlined />} loading={savePreferences.isPending} onClick={save}>保存当前设置</Button>
                </div>
              )}
            </Form>
          </main>
        </div>
      </Card>
      <AccountEditorModal
        systemType={editingSystem}
        current={(accounts.data ?? []).find((item) => item.system_type === editingSystem)}
        onClose={() => setEditingSystem(null)}
        onSaved={() => void queryClient.invalidateQueries({ queryKey: ['accounts'] })}
      />
    </div>
  )
}

function AccountsSection({ rows, loading, onEdit }: { rows: Array<{ systemType: AccountSummary['system_type']; systemName: string; current?: AccountSummary }>; loading: boolean; onEdit: (value: AccountSummary['system_type']) => void }) {
  return (
    <>
      <Alert type="info" showIcon message="Web 与桌面端共用账户数据库" description="账号和证件信息可以正常回填；密码在浏览器中只显示固定掩码，不能查看之前保存的明文。" style={{ marginBottom: 18 }} />
      <Table
        rowKey="systemType" loading={loading} dataSource={rows} pagination={false}
        onRow={(record) => ({ onClick: () => onEdit(record.systemType) })}
        columns={[
          { title: '系统', dataIndex: 'systemName', width: 220, render: (value) => <Typography.Text strong>{value}</Typography.Text> },
          { title: '显示名称', render: (_, record) => record.current?.display_name || '-' },
          { title: '当前账号', width: 220, render: (_, record) => record.current?.masked_account || '尚未维护' },
          { title: '状态', width: 120, render: (_, record) => record.current?.ready ? <Tag color="success">已配置</Tag> : <Tag>未配置</Tag> },
          { title: '操作', width: 110, render: (_, record) => <Button type="link" icon={<EditOutlined />} onClick={(event) => { event.stopPropagation(); onEdit(record.systemType) }}>编辑</Button> },
        ]}
      />
    </>
  )
}

function DownloadsSection() {
  return (
    <>
      <Row gutter={20}>
        <Col span={24}><Form.Item name="output_path" label="服务器默认保存位置" extra="留空时保存到程序 runtime/output/rights 目录"><Input placeholder="例如 D:\\E-HRM\\output" /></Form.Item></Col>
        <Col span={24}><Form.Item name="export_mode" label="默认导出方式"><Radio.Group optionType="button" buttonStyle="solid" options={[{ label: '每人单独一份', value: 'individual' }, { label: '按打印组', value: 'batch' }]} /></Form.Item></Col>
      </Row>
      <Card size="small" title="任务完成行为">
        <Space direction="vertical" size={18}>
          <Form.Item name="open_output_folder" label="桌面端完成后打开结果文件夹" valuePropName="checked" style={{ margin: 0 }}><Switch /></Form.Item>
          <Form.Item name="upload_to_erp" label="权益单下载后默认上传 ERP" valuePropName="checked" style={{ margin: 0 }}><Switch /></Form.Item>
        </Space>
      </Card>
    </>
  )
}

function AutomationSection() {
  return (
    <>
      <Alert type="info" showIcon message="DOM 操作使用智能等待，并在所选节奏区间内随机停顿；接口请求不增加人工延迟。" style={{ marginBottom: 18 }} />
      <Row gutter={20}>
        <Col xs={24} md={12}><Form.Item name="execution_speed" label="执行节奏"><Select options={[{ label: '快速（0.5–1 秒）', value: 'fast' }, { label: '标准（使用配置文件）', value: 'standard' }, { label: '稳定（1.5–2.5 秒）', value: 'stable' }]} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="no_result_confirm_seconds" label="无结果确认时间（秒）"><InputNumber min={3} max={60} style={{ width: '100%' }} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="preview_download_delay_ms" label="预览下载等待（毫秒）"><InputNumber min={0} max={5000} style={{ width: '100%' }} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="download_timeout_seconds" label="下载超时（秒）"><InputNumber min={5} max={180} style={{ width: '100%' }} /></Form.Item></Col>
      </Row>
    </>
  )
}

function ModelsSection({ settings, selectedModel, onSelect }: { settings?: WebPreferences; selectedModel?: WebPreferences['ai_model_options'][number]; onSelect: (value: string) => void }) {
  return (
    <>
      <div className="settings-model-grid">
        {(settings?.ai_model_options ?? []).map((model) => (
          <Card key={model.value} className={`settings-model-card ${selectedModel?.value === model.value ? 'active' : ''}`} onClick={() => onSelect(model.value)}>
            <Space align="start">
              <Radio checked={selectedModel?.value === model.value} />
              <div><Typography.Text strong>{model.label}</Typography.Text><br /><Typography.Text type="secondary">{model.model}</Typography.Text></div>
            </Space>
          </Card>
        ))}
      </div>
      {selectedModel && (
        <Card title="当前模型参数" style={{ marginTop: 18 }} extra={<Tag color="success">已配置</Tag>}>
          <div className="settings-model-meta">
            <div><Typography.Text type="secondary">Ollama 模型标识</Typography.Text><Typography.Text strong>{selectedModel.model}</Typography.Text></div>
            <div><Typography.Text type="secondary">运行上下文</Typography.Text><Typography.Text strong>{selectedModel.num_ctx} tokens</Typography.Text></div>
            <div><Typography.Text type="secondary">最大输出长度</Typography.Text><Typography.Text strong>{selectedModel.num_predict} tokens</Typography.Text></div>
            <div><Typography.Text type="secondary">请求超时 / 保持加载</Typography.Text><Typography.Text strong>{selectedModel.request_timeout_seconds} 秒 / {selectedModel.keep_alive}</Typography.Text></div>
          </div>
        </Card>
      )}
      <Card size="small" title="推理模式" style={{ marginTop: 18 }}>
        <Form.Item name="ai_reasoning_mode" style={{ margin: 0 }}>
          <Radio.Group optionType="button" buttonStyle="solid" options={(selectedModel?.reasoning_modes ?? ['off', 'on']).map((value) => ({ value, label: reasoningLabel(value) }))} />
        </Form.Item>
        <Form.Item name="ai_model_profile" hidden><Input /></Form.Item>
      </Card>
    </>
  )
}

function MaintenanceSection({ settings, clearing, onClear }: { settings?: WebPreferences; clearing: boolean; onClear: () => void }) {
  return (
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      <Descriptions bordered column={1} size="small">
        <Descriptions.Item label="运行数据目录"><Typography.Text copyable>{settings?.runtime_path || '-'}</Typography.Text></Descriptions.Item>
        <Descriptions.Item label="日志目录"><Typography.Text copyable>{settings?.logs_path || '-'}</Typography.Text></Descriptions.Item>
      </Descriptions>
      <Card size="small" title="临时文件清理">
        <Space direction="vertical">
          <Typography.Text type="secondary">仅清理临时截图和会话快照，不会删除账号、业务结果或任务记录。</Typography.Text>
          <Button danger icon={<ClearOutlined />} loading={clearing} onClick={onClear}>清理临时文件</Button>
        </Space>
      </Card>
    </Space>
  )
}

function AboutSection({ settings }: { settings?: WebPreferences }) {
  return (
    <Card>
      <Descriptions column={1} bordered>
        <Descriptions.Item label="软件名称">南化建人力</Descriptions.Item>
        <Descriptions.Item label="版本">{settings?.version || '-'}</Descriptions.Item>
        <Descriptions.Item label="部署模式">单服务器任务协调</Descriptions.Item>
        <Descriptions.Item label="说明">Web 与桌面端共用账号数据库、用户偏好和业务服务；同一自动化账号的任务会自动串行排队。</Descriptions.Item>
      </Descriptions>
    </Card>
  )
}

function reasoningLabel(value: string) {
  return ({ off: '非思考', on: '思考', low: '低', medium: '中', max: '高' } as Record<string, string>)[value] ?? value
}

function AccountEditorModal({ systemType, current, onClose, onSaved }: { systemType: AccountSummary['system_type'] | null; current?: AccountSummary; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  const labels = { JSHRSS: '江苏智慧人社', ERP: 'ERP', NOCOBASE: 'NocoBase' }
  const passwordMask = '******'
  const detail = useQuery({
    queryKey: ['account-edit', systemType, current?.id],
    queryFn: () => {
      if (!systemType || !current) throw new Error('账号不存在，请刷新页面后重试')
      return api.accountDetail(systemType, current.id)
    },
    enabled: systemType !== null && current !== undefined,
    refetchOnMount: 'always',
  })
  useEffect(() => {
    if (!systemType) return
    if (detail.data) {
      form.setFieldsValue({ display_name: detail.data.display_name, account: detail.data.account, secondary_account: detail.data.secondary_account, password: detail.data.password_saved ? passwordMask : '' })
    } else if (!current) form.setFieldsValue({ display_name: '', account: '', secondary_account: '', password: '' })
  }, [current, detail.data, form, systemType])
  const save = useMutation({
    mutationFn: (values: { account?: string; secondary_account?: string; password?: string; display_name?: string }) => {
      if (!systemType) throw new Error('未选择要编辑的系统账号')
      return api.saveAccount(systemType, { account_id: current?.id, account: values.account ?? '', secondary_account: values.secondary_account ?? '', password: values.password === passwordMask ? '' : values.password ?? '', display_name: values.display_name ?? '' })
    },
    onSuccess: () => {
      message.success(`${systemType ? labels[systemType] : '系统'}账号已保存`)
      form.resetFields()
      void queryClient.invalidateQueries({ queryKey: ['account-edit', systemType] })
      onSaved(); onClose()
    },
    onError: (error) => message.error(errorMessage(error)),
  })
  return (
    <Modal title={systemType ? `编辑${labels[systemType]}账号` : '编辑账号'} open={systemType !== null} onCancel={onClose} onOk={() => form.submit()} confirmLoading={save.isPending} okButtonProps={{ disabled: detail.isLoading }} okText="保存" cancelText="取消" width={620}>
      <Alert type="info" showIcon message={`当前账号：${detail.data?.account || current?.masked_account || '尚未维护'}`} description="账号和证件信息会正常回填。密码只显示固定掩码，不能查看旧密码；输入新内容后才会替换已保存密码。" style={{ marginBottom: 20 }} />
      {detail.isError && current && <Alert type="error" showIcon message="账号信息加载失败" description={errorMessage(detail.error)} style={{ marginBottom: 20 }} />}
      <Form form={form} layout="vertical" disabled={detail.isLoading} onFinish={(values) => save.mutate(values)}>
        <Form.Item name="display_name" label="显示名称"><Input placeholder={current?.display_name || '例如：南京单位账号'} /></Form.Item>
        <Form.Item name="account" label={systemType === 'JSHRSS' ? '单位编号/统一社会信用代码' : '登录账号'}><Input autoComplete="off" placeholder="请输入登录账号" /></Form.Item>
        {systemType === 'JSHRSS' && <Form.Item name="secondary_account" label="证件号码/移动电话"><Input autoComplete="off" placeholder="请输入证件号码或移动电话" /></Form.Item>}
        <Form.Item name="password" label="密码" extra="保持 ****** 表示不修改；输入新内容后才会更新密码。">
          <Input.Password autoComplete="new-password" placeholder="请输入密码" onFocus={(event) => { if (form.getFieldValue('password') === passwordMask) event.currentTarget.select() }} onClick={(event) => { if (form.getFieldValue('password') === passwordMask) event.currentTarget.select() }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
