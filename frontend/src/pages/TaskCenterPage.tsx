import { useState } from 'react'
import { Button, Card, Descriptions, Drawer, Empty, message, Progress, Space, Table, Typography } from 'antd'
import { DownloadOutlined, StopOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import { PageTitle } from '../components/PageTitle'
import { TaskStatusTag } from '../components/TaskStatusTag'

export function TaskCenterPage() {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: api.tasks,
    refetchInterval: 10_000,
  })
  const cancel = useMutation({
    mutationFn: api.cancelTask,
    onSuccess: (task) => {
      message.success(task.message)
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => message.error(errorMessage(error)),
  })

  const tasks = data?.tasks ?? []
  const selected = tasks.find((task) => task.task_id === selectedTaskId) ?? null
  const artifacts = resultArtifacts(selected?.result)
  const archive = resultArchive(selected?.result)
  return (
    <div className="page-stack">
      <PageTitle
        title="任务中心"
        description="任务可以在后台运行，离开当前页面不会中断处理"
      />
      <Card className="content-card">
        <Table
          rowKey="task_id"
          loading={isLoading}
          dataSource={tasks}
          locale={{ emptyText: <Empty description="暂无任务记录" /> }}
          onRow={(record) => ({ onClick: () => setSelectedTaskId(record.task_id) })}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          columns={[
            { title: '任务', dataIndex: 'title', width: 200 },
            { title: '状态', dataIndex: 'status', width: 110, render: (status) => <TaskStatusTag status={status} /> },
            { title: '使用资源', dataIndex: 'resource_label', width: 180 },
            {
              title: '进度',
              width: 190,
              render: (_, record) => (
                <Progress
                  percent={Math.round((record.progress_current / Math.max(record.progress_total, 1)) * 100)}
                  size="small"
                  status={record.status === 'failed' ? 'exception' : undefined}
                />
              ),
            },
            { title: '当前说明', dataIndex: 'message', ellipsis: true },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              width: 170,
              render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm:ss'),
            },
          ]}
        />
      </Card>
      <Drawer
        title="任务详情"
        width={560}
        open={selected !== null}
        onClose={() => setSelectedTaskId(null)}
        extra={
          selected && ['queued', 'running'].includes(selected.status) ? (
            <Button
              danger
              icon={<StopOutlined />}
              loading={cancel.isPending}
              onClick={() => cancel.mutate(selected.task_id)}
            >
              停止任务
            </Button>
          ) : null
        }
      >
        {selected && (
          <Space direction="vertical" size={24} style={{ width: '100%' }}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="任务名称">{selected.title}</Descriptions.Item>
              <Descriptions.Item label="状态"><TaskStatusTag status={selected.status} /></Descriptions.Item>
              <Descriptions.Item label="业务资源">{selected.resource_label}</Descriptions.Item>
              <Descriptions.Item label="任务编号"><Typography.Text copyable>{selected.task_id}</Typography.Text></Descriptions.Item>
              <Descriptions.Item label="当前说明">{selected.message}</Descriptions.Item>
            </Descriptions>
            {selected.error && (
              <Card size="small" title="错误信息" className="error-card">
                <Typography.Text type="danger">{selected.error}</Typography.Text>
              </Card>
            )}
            {(archive || artifacts.length > 0) && (
              <Card size="small" title="结果文件">
                <Space direction="vertical">
                  {archive && (
                    <Button type="primary" icon={<DownloadOutlined />} href={archive.url}>
                      下载全部结果（ZIP）
                    </Button>
                  )}
                  {artifacts.map((artifact) => (
                    <Button key={artifact.url} type="link" href={artifact.url}>
                      {artifact.name}
                    </Button>
                  ))}
                </Space>
              </Card>
            )}
          </Space>
        )}
      </Drawer>
    </div>
  )
}

function resultArtifacts(value: unknown): Array<{ name: string; url: string }> {
  if (!value || typeof value !== 'object' || !('artifacts' in value)) return []
  const artifacts = (value as { artifacts?: unknown }).artifacts
  if (!Array.isArray(artifacts)) return []
  return artifacts.filter(
    (item): item is { name: string; url: string } =>
      Boolean(item)
      && typeof item === 'object'
      && typeof (item as { name?: unknown }).name === 'string'
      && typeof (item as { url?: unknown }).url === 'string',
  )
}

function resultArchive(value: unknown): { name: string; url: string } | null {
  if (!value || typeof value !== 'object' || !('archive' in value)) return null
  const archive = (value as { archive?: unknown }).archive
  if (!archive || typeof archive !== 'object') return null
  if (typeof (archive as { name?: unknown }).name !== 'string') return null
  if (typeof (archive as { url?: unknown }).url !== 'string') return null
  return archive as { name: string; url: string }
}
