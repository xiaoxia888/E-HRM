import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { FilePdfOutlined, InfoCircleOutlined, MedicineBoxOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { Alert, Button, Card, DatePicker, Modal, Radio, Skeleton, Table, Tooltip, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { api } from '../api/queries'
import { errorMessage } from '../api/client'
import type { BusinessUsageSeries } from '../types'

const businessStyles = {
  rights: { color: '#1677ff', icon: <FilePdfOutlined />, description: '权益单获取' },
  social: { color: '#12936e', icon: <SafetyCertificateOutlined />, description: '退工停保' },
  medical: { color: '#8056d9', icon: <MedicineBoxOutlined />, description: '停保 / 参保' },
}

export function BusinessUsagePanel() {
  const [days, setDays] = useState(30)
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const startDate = range?.[0].format('YYYY-MM-DD')
  const endDate = range?.[1].format('YYYY-MM-DD')
  const usage = useQuery({
    queryKey: ['business-usage', startDate ?? days, endDate],
    queryFn: () => api.businessUsage(startDate && endDate ? { start_date: startDate, end_date: endDate } : { days }),
    refetchInterval: 30_000,
  })
  const data = usage.data
  const today = data?.today ?? new Date(Date.now() + 8 * 3_600_000).toISOString().slice(0, 10)
  const dailyRows = (data?.businesses[0]?.daily ?? []).map((day, index) => ({
    date: day.date,
    ...Object.fromEntries(data!.businesses.map((business) => [business.key, business.daily[index]?.count ?? 0])),
  }))

  return (
    <section aria-label="业务使用统计">
      <Card size="small" className="content-card business-usage-panel">
        <div className="business-usage-header">
          <div className="business-usage-title">
            <Typography.Title level={5}>业务使用统计</Typography.Title>
            <Tooltip title="每次创建业务任务计 1 次，成功、失败及取消均计入；按北京时间统计。累计从系统保存的首条记录开始。">
              <InfoCircleOutlined tabIndex={0} aria-label="统计口径" />
            </Tooltip>
          </div>
          <div className="business-usage-controls">
            <Radio.Group size="small" aria-label="快捷统计范围" value={range ? null : days} onChange={(event) => { setDays(event.target.value); setRange(null) }}>
              <Radio.Button value={7}>最近 7 天</Radio.Button>
              <Radio.Button value={30}>30 天</Radio.Button>
              <Radio.Button value={90}>90 天</Radio.Button>
            </Radio.Group>
            <DatePicker.RangePicker
              size="small"
              value={range}
              format="YYYY-MM-DD"
              placeholder={['开始日期', '结束日期']}
              disabledDate={(value) => value.format('YYYY-MM-DD') > today}
              onChange={(values) => {
                if (!values) setRange(null)
                else if (values[0] && values[1]) setRange([values[0], values[1]])
              }}
            />
            <Button size="small" type="text" aria-label="刷新统计" icon={<ReloadOutlined />} loading={usage.isFetching} onClick={() => void usage.refetch()} />
          </div>
        </div>
        {usage.isError && <Alert showIcon type="error" title={data ? '统计更新失败，以下为上次读取的结果' : '使用统计加载失败'} description={errorMessage(usage.error)} />}
        {usage.isLoading ? <Skeleton active title={false} paragraph={{ rows: 3 }} /> : data ? (
          <>
            <div className="business-usage-grid">
              {data.businesses.map((business) => {
                const style = businessStyles[business.key]
                return <article key={business.key} aria-label={`${business.label}使用统计`} className="business-usage-item" style={{ '--usage-color': style.color } as CSSProperties}>
                  <div className="business-usage-item-title">
                    <span className="business-usage-name">{style.icon}<strong>{business.label}</strong></span>
                    <Typography.Text type="secondary">{style.description}</Typography.Text>
                  </div>
                  <dl className="business-usage-metrics">
                    <div>
                      <dt><Tooltip title={business.first_used_date ? `自 ${dayjs(business.first_used_date).format('YYYY/MM/DD')} 起` : '暂无使用记录'}>累计</Tooltip></dt>
                      <dd>{business.total_count.toLocaleString()}<small>次</small></dd>
                    </div>
                    <div><dt>今日</dt><dd>{business.today_count.toLocaleString()}<small>次</small></dd></div>
                    <div><dt>所选期间</dt><dd>{business.period_count.toLocaleString()}<small>次</small></dd></div>
                  </dl>
                  <DailyUsageChart key={`${data.start_date}:${data.end_date}`} business={business} color={style.color} />
                </article>
              })}
            </div>
            <div className="business-usage-footer">
              <Typography.Text type="secondary">{dayjs(data.start_date).format('YYYY/MM/DD')} — {dayjs(data.end_date).format('YYYY/MM/DD')} · 每日次数</Typography.Text>
              <Button size="small" type="link" onClick={() => setDetailsOpen(true)}>每日明细</Button>
            </div>
          </>
        ) : null}
      </Card>
      <Modal title="每日使用明细" open={detailsOpen} width={680} onCancel={() => setDetailsOpen(false)} footer={<Button onClick={() => setDetailsOpen(false)}>关闭</Button>}>
        <Table size="small" rowKey="date" dataSource={dailyRows} pagination={{ pageSize: 10, showSizeChanger: false }} columns={[
          { title: '日期', dataIndex: 'date', render: (value: string) => dayjs(value).format('YYYY/MM/DD') },
          ...(data?.businesses ?? []).map((business) => ({ title: business.label, dataIndex: business.key, align: 'right' as const, render: (value: number) => `${value} 次` })),
        ]} />
      </Modal>
    </section>
  )
}

function DailyUsageChart({ business, color }: { business: BusinessUsageSeries; color: string }) {
  const { daily, label } = business
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const container = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(300)
  useEffect(() => {
    const element = container.current
    if (!element) return
    const resize = () => setWidth(Math.max(160, Math.round(element.clientWidth)))
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const height = 100
  const left = 22
  const right = 6
  const top = 14
  const baseline = height - 20
  const plotHeight = baseline - top
  const step = Math.max(1, Math.ceil(Math.max(1, ...daily.map((item) => item.count)) / 2))
  const maximum = step * 2
  const slot = (width - left - right) / Math.max(1, daily.length)
  const selected = selectedIndex === null ? null : daily[selectedIndex]

  return (
    <div ref={container} className="business-usage-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={`${label}每日使用次数，单位为次`}>
        {[0, step, maximum].map((value) => {
          const y = baseline - value / maximum * plotHeight
          return <g key={value}>
            <line x1={left} x2={width - right} y1={y} y2={y} stroke="#e4e9f0" strokeDasharray={value === 0 ? undefined : '3 3'} />
            <text x={left - 5} y={y + 3} textAnchor="end" className="business-usage-axis">{value}</text>
          </g>
        })}
        {daily.map((item, index) => {
          const center = left + slot * (index + 0.5)
          const barHeight = item.count / maximum * plotHeight
          const barWidth = Math.min(20, slot * 0.65)
          const active = index === selectedIndex
          return <g key={item.date} tabIndex={0} aria-label={`${label} ${item.date}，使用 ${item.count} 次`} data-date={item.date}
            className="business-usage-day"
            onMouseEnter={() => setSelectedIndex(index)} onMouseLeave={(event) => { if (!event.currentTarget.contains(document.activeElement)) setSelectedIndex(null) }}
            onFocus={() => setSelectedIndex(index)} onBlur={() => setSelectedIndex(null)}>
            <rect x={left + slot * index} y={top} width={slot} height={plotHeight} fill={active ? color : 'transparent'} fillOpacity={0.08} />
            <rect x={center - barWidth / 2} y={baseline - barHeight} width={barWidth} height={barHeight} fill={color} fillOpacity={active ? 1 : 0.8} rx={Math.min(2, barWidth / 2)} />
          </g>
        })}
        {daily.length > 0 && <>
          <text x={left} y={height - 3} className="business-usage-axis">{dayjs(daily[0].date).format('MM/DD')}</text>
          <text x={width - right} y={height - 3} textAnchor="end" className="business-usage-axis">{dayjs(daily[daily.length - 1].date).format('MM/DD')}</text>
        </>}
      </svg>
      {selected && selectedIndex !== null && <div role="tooltip" className="business-usage-tooltip" style={{ left: `${Math.min(78, Math.max(22, (left + slot * (selectedIndex + 0.5)) / width * 100))}%` }}>
        <span>{dayjs(selected.date).format('YYYY/MM/DD')}</span>
        <strong>{selected.count} 次</strong>
      </div>}
      {daily.every((item) => item.count === 0) && <div className="business-usage-empty">暂无使用</div>}
    </div>
  )
}
