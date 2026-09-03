import { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Typography, Spin, Select, Alert, Space, message } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { reportApi } from '../api'

const { Title, Text } = Typography

const fmt = (cents) => (cents != null ? `¥${(cents / 100).toLocaleString()}` : '—')

export default function ComparePage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState([])
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState([])
  const [comparison, setComparison] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sumLoading, setSumLoading] = useState(false)

  // 加载已完成任务及其报告
  useEffect(() => {
    const load = async () => {
      try {
        const resp = await client.get('/tasks')
        const doneTasks = (resp.data?.tasks || []).filter((t) => t.status === 'done' || t.status === 'partial')
        setTasks(doneTasks)
        const all = []
        for (const t of doneTasks) {
          try {
            const r = await reportApi.get(t.id)
            ;(r.data?.reports || []).forEach((rep) => {
              all.push({ ...rep, taskId: t.id, debtor: rep.content?.report_meta?.debtor_name || `任务${t.id}` })
            })
          } catch { /* 跳过无报告任务 */ }
        }
        setReports(all)
      } catch { /* 拦截器已提示 */ }
    }
    load()
  }, [])

  const options = reports.map((r) => ({
    value: r.id,
    label: `${r.debtor}（报告#${r.id}）`,
  }))

  const doCompare = async () => {
    if (selected.length < 2) return message.warning('请至少选择 2 份报告')
    setLoading(true)
    try {
      const resp = await client.post('/compare', { report_ids: selected })
      setComparison(resp.data)
      setSummary(null)
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  const doSummary = async () => {
    if (!comparison) return message.warning('请先生成对比数据')
    setSumLoading(true)
    try {
      const resp = await client.post('/compare/summary', { report_ids: selected })
      setSummary(resp.data)
    } catch { /* 拦截器已提示 */ } finally {
      setSumLoading(false)
    }
  }

  // 对比表格：行为维度，列为报告
  const tableData = comparison
    ? comparison.fields.map((f) => {
        const row = { key: f.key, label: f.label }
        comparison.reports.forEach((r) => {
          let val = r[f.key]
          if (f.key === 'principal') val = fmt(val)
          if (f.key === 'collateral') val = val === true ? '有' : val === false ? '无' : val
          if (f.key === 'buy_price' && typeof val === 'number') val = fmt(val)
          row[`r${r.report_id}`] = val ?? '⚠️'
        })
        return row
      })
    : []

  const compareColumns = comparison
    ? [
        { title: '对比维度', dataIndex: 'label', fixed: 'left', width: 140 },
        ...comparison.reports.map((r) => ({
          title: r.debtor_name || `报告${r.report_id}`,
          dataIndex: `r${r.report_id}`,
          width: 180,
        })),
      ]
    : []

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <Title level={3}>债权对比分析</Title>
      <Text type="secondary">选择已完成的尽调报告进行横向对比（P2 功能）</Text>

      <Card style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select
            mode="multiple"
            placeholder="选择 2~10 份报告"
            options={options}
            value={selected}
            onChange={setSelected}
            style={{ width: '100%' }}
            maxTagCount={5}
          />
          <Space>
            <Button type="primary" icon={<ThunderboltOutlined />} loading={loading} onClick={doCompare}>
              生成对比
            </Button>
            <Button loading={sumLoading} onClick={doSummary} disabled={!comparison}>
              系统对比总结
            </Button>
          </Space>
        </Space>
      </Card>

      {comparison && (
        <Card title="对比结果" style={{ marginTop: 16 }}>
          <Table size="small" columns={compareColumns} dataSource={tableData} pagination={false} scroll={{ x: 'max-content' }} />
        </Card>
      )}

      {summary && (
        <Card title="系统对比总结" style={{ marginTop: 16 }}>
          {summary.ranking && summary.ranking.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Text strong>优先关注排序：</Text>
              {summary.ranking.map((name, i) => (
                <Tag key={i} color="blue" style={{ marginLeft: 8 }}>{i + 1}. {name}</Tag>
              ))}
            </div>
          )}
          {summary.recommendation && <Alert type="info" showIcon message="建议" description={summary.recommendation} style={{ marginBottom: 12 }} />}
          {(summary.highlights || []).map((h, i) => <div key={`h${i}`}>✨ {h}</div>)}
          {(summary.warnings || []).map((w, i) => <div key={`w${i}`} style={{ color: '#cf1322' }}>⚠️ {w}</div>)}
        </Card>
      )}
    </div>
  )
}
