import { useEffect, useState, useMemo } from 'react'
import { Row, Col, Select, Input, Button, Tag, Empty, Spin, Pagination, Space, Typography, Table, Checkbox, message, Alert } from 'antd'
import { RobotOutlined, SwapOutlined, FireOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore } from '../store/auth'
import { claimApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'

const { Text } = Typography

export default function DebtListPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const isPick = params.get('feature') === 'pick'
  const token = useAuthStore((s) => s.token)
  const setClaims = useClaimDraftStore((s) => s.setClaims)

  const [section, setSection] = useState(isPick ? 'pick' : 'featured')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [region, setRegion] = useState('')
  const [risk, setRisk] = useState('')
  const [discount, setDiscount] = useState('')
  const [selectedKeys, setSelectedKeys] = useState([])
  const [ddLoading, setDdLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (section !== 'pick') q.set('section', section)
      const resp = await client.get(`/feed?${q.toString()}`)
      let list = resp.data?.items || []
      const total = resp.data?.total ?? list.length
      if (section === 'pick') {
        const [bank, featured] = await Promise.all([
          client.get('/feed?section=bargain').catch(() => ({ data: { items: [] } })),
          client.get('/feed?section=featured').catch(() => ({ data: { items: [] } })),
        ])
        const bankItems = bank.data?.items || []
        const featuredItems = (featured.data?.items || []).filter((it) => {
          const disc = (it.detail || {}).discount || ''
          return /[01234]\.?\d*折/.test(disc) || /破产|重整/.test((it.tags || []).join(''))
        })
        list = [...bankItems, ...featuredItems]
      }
      if (region) list = list.filter((it) => ((it.detail || {}).region || '').includes(region))
      if (risk) list = list.filter((it) => (it.detail || {}).risk === risk)
      if (discount) {
        const max = parseFloat(discount)
        list = list.filter((it) => {
          const m = ((it.detail || {}).discount || '').match(/([\d.]+)折/)
          return m ? parseFloat(m[1]) <= max : false
        })
      }
      if (keyword) list = list.filter((it) => (it.title + (it.summary || '')).includes(keyword))
      setItems(list)
      setTotal(total)
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => { setSection(isPick ? 'pick' : 'featured'); setPage(1) }, [isPick])
  useEffect(() => { load() }, [section, page, pageSize])

  const regions = useMemo(() => {
    const set = new Set()
    items.forEach((it) => { const r = (it.detail || {}).region; if (r && r !== '—') set.add(r) })
    return [...set]
  }, [items])

  // 批量尽调（仅精选债权可用）：勾选行 → 提取字段 → 预览页
  const startBatchDD = async () => {
    if (!token) { message.warning('请先登录后发起尽调'); navigate('/login'); return }
    if (selectedKeys.length === 0) { message.warning('请至少勾选 1 条债权'); return }
    if (selectedKeys.length > 5) { message.warning('单次最多勾选 5 条'); return }
    setDdLoading(true)
    try {
      const selected = items.filter((it) => selectedKeys.includes(it.id))
      const texts = selected.map((it) => `${it.title}\n${it.summary || ''}\n${JSON.stringify(it.detail || {})}`).join('\n---\n')
      const resp = await claimApi.importText(texts)
      setClaims(resp.data.claims)
      message.success(`已提取 ${selected.length} 条债权字段，请确认后尽调`)
      navigate('/preview')
    } catch { /* 拦截器已提示 */ } finally {
      setDdLoading(false)
    }
  }

  const riskColor = (r) => (r === 'high' ? 'red' : r === 'medium' ? 'orange' : 'green')
  const riskLabel = (r) => (r === 'high' ? '高风险' : r === 'medium' ? '中风险' : '低风险')

  // 精选债权：紧凑表格 + 行勾选批量尽调（技术文档 §5.3.1 勾选已有债权）
  const tableColumns = [
    {
      title: '债权', dataIndex: 'title', key: 'title', width: 260,
      render: (v, r) => (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{v}</div>
          <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>{r.source || ''}</div>
        </div>
      ),
    },
    { title: '债务人', key: 'debtor', width: 130, render: (_, r) => (r.detail || {}).debtor_name || '—' },
    { title: '本金', key: 'claim', width: 90, render: (_, r) => <Text strong style={{ color: 'var(--danger)' }}>{(r.detail || {}).claim_total || '—'}</Text> },
    { title: '折扣', key: 'discount', width: 70, render: (_, r) => <Text style={{ color: 'var(--danger)' }}>{(r.detail || {}).discount || '—'}</Text> },
    { title: '抵押物', key: 'collateral', width: 100, ellipsis: true, render: (_, r) => (r.detail || {}).collateral_type || '—' },
    { title: '地区', key: 'region', width: 90, render: (_, r) => (r.detail || {}).region || '—' },
    { title: '风险', key: 'risk', width: 80, render: (_, r) => <Tag color={riskColor((r.detail || {}).risk)}>{(r.detail || {}).risk ? riskLabel((r.detail || {}).risk) : '—'}</Tag> },
    {
      title: '操作', key: 'action', width: 100,
      render: (_, r) => <Button size="small" type="link" onClick={() => navigate(`/asset/${r.id}`)}>查看详情 →</Button>,
    },
  ]

  // 捡漏专区/热门捡漏：列表（无勾选、无批量尽调；尽调仅限精选债权）
  const pickColumns = [
    {
      title: '捡漏标的', dataIndex: 'title', key: 'title', width: 300,
      render: (v, r) => (
        <Space>
          <Tag color="orange" icon={<FireOutlined />}>捡漏</Tag>
          <span style={{ fontWeight: 600, fontSize: 13 }}>{v}</span>
        </Space>
      ),
    },
    { title: '本金', key: 'claim', width: 100, render: (_, r) => <Text strong style={{ color: 'var(--danger)' }}>{(r.detail || {}).claim_total || '—'}</Text> },
    { title: '折扣', key: 'discount', width: 80, render: (_, r) => <Text style={{ color: 'var(--danger)' }}>{(r.detail || {}).discount || '—'}</Text> },
    { title: '来源', key: 'source', width: 100, render: (_, r) => r.source || '—' },
    {
      title: '操作', key: 'action', width: 120,
      render: (_, r) => <Button size="small" type="link" onClick={() => navigate(`/asset/${r.id}`)}>查看详情 →</Button>,
    },
  ]

  const filterBar = (
    <Space wrap style={{ marginBottom: 16 }}>
      <Select value={section} style={{ width: 150 }} onChange={(v) => { setSection(v); setPage(1) }}
        options={[
          { value: 'featured', label: '精选债权（可尽调）' },
          { value: 'pick', label: '捡漏专区' },
          { value: 'bargain', label: '热门捡漏' },
          { value: 'notice', label: '债权公告' },
        ]} />
      <Select allowClear placeholder="地区" style={{ width: 130 }} value={region || undefined}
        onChange={(v) => { setRegion(v || ''); setPage(1) }} options={regions.map((r) => ({ value: r, label: r }))} />
      <Select allowClear placeholder="风险等级" style={{ width: 120 }} value={risk || undefined}
        onChange={(v) => { setRisk(v || ''); setPage(1) }}
        options={[{ value: 'low', label: '低风险' }, { value: 'medium', label: '中风险' }, { value: 'high', label: '高风险' }]} />
      <Select allowClear placeholder="折扣上限" style={{ width: 120 }} value={discount || undefined}
        onChange={(v) => { setDiscount(v || ''); setPage(1) }}
        options={[{ value: '3', label: '≤3折' }, { value: '4', label: '≤4折' }, { value: '5', label: '≤5折' }, { value: '7', label: '≤7折' }]} />
      <Input.Search allowClear placeholder="搜索标题/简介" style={{ width: 200 }} onSearch={(v) => { setKeyword(v); setPage(1) }} />
    </Space>
  )

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 80px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {isPick ? '捡漏专区' : section === 'bargain' ? '热门捡漏' : section === 'notice' ? '债权公告' : '精选债权'}
        </Typography.Title>
        <Text type="secondary" style={{ fontSize: 12 }}>共 {total} 条</Text>
      </div>

      {isPick && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message="捡漏专区：自动汇集「破产清算/重整」债权与精选债权中折扣 ≤4 折的低本金标的，适合个人投资者。" />
      )}

      {filterBar}

      {section === 'featured' && (
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlayCircleOutlined />} loading={ddLoading} onClick={startBatchDD}
            disabled={!token || selectedKeys.length === 0}>
            批量尽调（已选 {selectedKeys.length} 条，最多 5 条）
          </Button>
          {!token && <Text type="secondary" style={{ fontSize: 12 }}>登录后可发起尽调</Text>}
        </Space>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : items.length === 0 ? (
        <Empty description="暂无符合条件的债权" style={{ padding: 60 }} />
      ) : section === 'featured' ? (
        <Table
          rowKey="id"
          size="small"
          columns={tableColumns}
          dataSource={items}
          pagination={false}
          rowSelection={token ? {
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys.slice(0, 5)),
            preserveSelectedRowKeys: true,
          } : undefined}
          onRow={(r) => ({ style: { cursor: 'pointer' }, onClick: () => navigate(`/asset/${r.id}`) })}
        />
      ) : (
        <Table rowKey="id" size="small" columns={pickColumns} dataSource={items} pagination={false}
          onRow={(r) => ({ style: { cursor: 'pointer' }, onClick: () => navigate(`/asset/${r.id}`) })} />
      )}

      {items.length > 0 && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Pagination current={page} pageSize={pageSize} total={total}
            onChange={(p) => { setPage(p); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
            showSizeChanger showQuickJumper />
        </div>
      )}
    </div>
  )
}
