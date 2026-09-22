import { useMemo, useState } from 'react'
import {
  ApartmentOutlined,
  CheckCircleFilled,
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { Badge, Button, Flex, Layout, Menu, Tooltip, Typography } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/queries'
import { useTaskStream } from '../hooks/useTaskStream'

const { Sider, Content } = Layout

const items = [
  { key: '/', icon: <DashboardOutlined />, label: '工作台' },
  { key: '/applications', icon: <FileTextOutlined />, label: '权益申请' },
  { key: '/rights', icon: <DatabaseOutlined />, label: '权益单获取' },
  { key: '/social-security', icon: <ApartmentOutlined />, label: '社保业务' },
  { key: '/tasks', icon: <UnorderedListOutlined />, label: '任务中心' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
]

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  useTaskStream()
  const { data } = useQuery({
    queryKey: ['tasks'],
    queryFn: api.tasks,
    refetchInterval: 10_000,
  })
  const activeTasks = useMemo(
    () =>
      data?.tasks.filter((task) =>
        ['queued', 'running', 'cancelling'].includes(task.status),
      ).length ?? 0,
    [data],
  )

  return (
    <Layout className="app-layout">
      <Sider
        theme="light"
        width={232}
        collapsedWidth={72}
        collapsed={collapsed}
        className="app-sider"
      >
        <Flex className={`brand ${collapsed ? 'brand-collapsed' : ''}`} align="center" gap={10}>
          {!collapsed && <div className="brand-mark"><DatabaseOutlined /></div>}
          {!collapsed && (
            <div className="brand-copy">
              <Typography.Text strong className="brand-title">南化建人力</Typography.Text>

            </div>
          )}
          <Tooltip title={collapsed ? '展开导航栏' : '收起导航栏'} placement="right">
            <Button
              type="text"
              className="brand-collapse-button"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((value) => !value)}
              aria-label="切换导航栏"
            />
          </Tooltip>
        </Flex>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={items}
          onClick={({ key }) => navigate(key)}
          className="main-menu"
        />
        <div className={`sidebar-runtime ${collapsed ? 'sidebar-runtime-collapsed' : ''}`}>
          <Tooltip title="单服务器运行正常" placement="right">
            <div className="sidebar-runtime-row">
              <CheckCircleFilled className="sidebar-runtime-ok" />
              {!collapsed && <span>单服务器运行正常</span>}
            </div>
          </Tooltip>
          <Tooltip title={`进行中任务 ${activeTasks}`} placement="right">
            <button className="sidebar-task-button" type="button" onClick={() => navigate('/tasks')}>
              <Badge count={activeTasks} size="small" offset={[4, -2]}>
                <UnorderedListOutlined />
              </Badge>
              {!collapsed && <span>进行中任务 {activeTasks}</span>}
            </button>
          </Tooltip>
        </div>
      </Sider>
      <Layout>
        <Content className={`app-content ${location.pathname === '/rights' ? 'app-content-fixed' : ''}`}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
