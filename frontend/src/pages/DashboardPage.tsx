import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons'
import { Alert, Card, Col, Row, Skeleton, Statistic, Table, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/queries'
import { PageTitle } from '../components/PageTitle'

export function DashboardPage() {
  const tasks = useQuery({ queryKey: ['tasks'], queryFn: api.tasks })
  const policy = useQuery({ queryKey: ['policy'], queryFn: api.policy })
  const records = tasks.data?.tasks ?? []
  const count = (status: string) =>
    records.filter((task) => task.status === status).length

  return (
    <div className="page-stack">
      <PageTitle
        title="工作台"
        description="统一查看业务运行状态、账号队列和处理结果"
      />
      <Alert
        type="info"
        showIcon
        message="系统已启用账号级安全调度"
        description="同一智慧人社账号自动串行排队，不同账号可使用独立浏览器并行；普通数据库和 API 查询不会占用浏览器队列。"
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title="执行中" value={count('running')} prefix={<LoadingOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title="排队中" value={count('queued')} prefix={<ClockCircleOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title="已完成" value={count('succeeded')} prefix={<CheckCircleOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card><Statistic title="执行失败" value={count('failed')} prefix={<CloseCircleOutlined />} /></Card>
        </Col>
      </Row>
      <Card title="任务并发规则" className="content-card">
        {policy.isLoading ? (
          <Skeleton active />
        ) : (
          <Table
            rowKey="situation"
            dataSource={policy.data?.items ?? []}
            pagination={false}
            columns={[
              { title: '情况', dataIndex: 'situation', width: 220 },
              {
                title: '执行方式',
                dataIndex: 'behavior',
                width: 180,
                render: (value: string) => <Tag color="blue">{value}</Tag>,
              },
              { title: '说明', dataIndex: 'explanation' },
            ]}
          />
        )}
      </Card>
    </div>
  )
}
