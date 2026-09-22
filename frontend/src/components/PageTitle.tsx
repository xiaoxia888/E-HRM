import type { ReactNode } from 'react'
import { Flex, Typography } from 'antd'

interface PageTitleProps {
  title: string
  description: string
  extra?: ReactNode
}

export function PageTitle({ title, description, extra }: PageTitleProps) {
  return (
    <Flex justify="space-between" align="flex-start" gap={24} wrap>
      <div>
        <Typography.Title level={2} className="page-title">
          {title}
        </Typography.Title>
        <Typography.Text type="secondary">{description}</Typography.Text>
      </div>
      {extra}
    </Flex>
  )
}
