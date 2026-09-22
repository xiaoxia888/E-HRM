import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Empty, Select, Skeleton, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import { PageTitle } from '../components/PageTitle'

export function ApplicationsPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [printAccountId, setPrintAccountId] = useState<number>()
  const [uploadToErp, setUploadToErp] = useState(false)
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
  const rightsAccounts = (accounts.data ?? []).filter((item) => item.system_type === 'JSHRSS' && item.ready)
  useEffect(() => {
    if (printAccountId === undefined && rightsAccounts.length) {
      setPrintAccountId((rightsAccounts.find((item) => item.is_default) ?? rightsAccounts[0]).id)
    }
  }, [printAccountId, rightsAccounts])
  useEffect(() => {
    if (settings.data) setUploadToErp(settings.data.upload_to_erp)
  }, [settings.data])
  const printApplication = useMutation({
    mutationFn: (applicationId: number) => {
      if (printAccountId === undefined) throw new Error('请先在系统设置中保存完整的江苏智慧人社账号')
      return api.printApplication(applicationId, printAccountId, uploadToErp)
    },
    onSuccess: (task) => {
      message.success(task.message)
      setSelectedId(null)
      navigate('/tasks')
    },
    onError: (error) => message.error(errorMessage(error)),
  })

  return (
    <div className="page-stack">
      <PageTitle
        title="权益申请"
        description="直接通过 NocoBase API 查询，不占用智慧人社浏览器队列"
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
        width="min(920px, 78vw)"
        open={selectedId !== null}
        onClose={() => setSelectedId(null)}
        extra={
          <Space>
            <Space size={6}>
              <Switch size="small" checked={uploadToErp} onChange={setUploadToErp} />
              <Typography.Text>完成后上传 ERP</Typography.Text>
            </Space>
            <Select
              value={printAccountId}
              placeholder="选择智慧人社账号"
              style={{ width: 210 }}
              options={rightsAccounts.map((item) => ({ value: item.id, label: `${item.display_name} · ${item.masked_account}` }))}
              onChange={setPrintAccountId}
            />
            <Button
              type="primary"
              disabled={!detail.data || !detail.data.related_persons.length || printAccountId === undefined}
              loading={printApplication.isPending}
              onClick={() => selectedId !== null && printApplication.mutate(selectedId)}
            >
              打印社保权益单
            </Button>
          </Space>
        }
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
            <div>
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
            </div>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
