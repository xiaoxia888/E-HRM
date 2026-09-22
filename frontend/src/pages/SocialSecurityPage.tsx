import { Alert, Card, Col, Row, Tag, Typography } from 'antd'
import { FormOutlined, SafetyCertificateOutlined, UserAddOutlined } from '@ant-design/icons'
import { PageTitle } from '../components/PageTitle'

const operations = [
  { title: '人员退保', description: '根据身份证号和退工原因录入退工停保信息', icon: <SafetyCertificateOutlined /> },
  { title: '人员基础信息采集', description: '采集人员身份、民族、户籍性质和行政区划信息', icon: <FormOutlined /> },
  { title: '人员参保', description: '录入合同、岗位、参保身份和月缴费工资', icon: <UserAddOutlined /> },
]

export function SocialSecurityPage() {
  return (
    <div className="page-stack">
      <PageTitle title="社保业务" description="智慧人社自动化业务统一入口" />
      <Alert
        type="warning"
        showIcon
        message="Web 表单正在接入"
        description="浏览器自动化能力已经完成，本页下一阶段接入业务表单和任务提交。正式提交功能启用前，系统仍只录入数据，不点击智慧人社确认提交。"
      />
      <Row gutter={[16, 16]}>
        {operations.map((item) => (
          <Col xs={24} lg={8} key={item.title}>
            <Card className="operation-card">
              <div className="operation-icon">{item.icon}</div>
              <Typography.Title level={4}>{item.title}</Typography.Title>
              <Typography.Paragraph type="secondary">{item.description}</Typography.Paragraph>
              <Tag color="processing">自动化脚本已实现，Web 接入中</Tag>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
