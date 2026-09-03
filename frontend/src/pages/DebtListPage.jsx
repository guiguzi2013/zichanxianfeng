import { useEffect, useState, useMemo } from 'react'
import { Row, Col, Select, Input, Button, Tag, Empty, Spin, Pagination, Space, Typography, Table, message, Alert, Checkbox, Modal } from 'antd'
import { PlayCircleOutlined, FireOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore } from '../store/auth'
import { claimApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'
import { canDueDiligence } from '../utils/claimEligibility'

const { Text } = Typography

export default function DebtListPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const isPick = params.get('feature') === 'pick'
  const urlSection = params.get('section') // 支持 ?section=notice 直达债权公告
  const token = useAuthStore((s) => s.token)
  const setClaims = useClaimDraftStore((s) => s.setClaims)

  const [section, setSection] = useState(isPick ? 'pick' : (urlSection || 'featured'))
  const [allItems, setAllItems] = useState([]) // 当前栏目全量（未分页过滤）
  const [items, setItems] = useState([])      // 筛选+分页后的当前页
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [region, setRegion] = useState('')
  const [risk, setRisk] = useState('')
  const [discount, setDiscount] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [selectedKeys, setSelectedKeys] = useState([])
  const [ddLoading, setDdLoading] = useState(false)

  // 1) 加载栏目全量数据（精选/捡漏/公告 各自取全量）
  useEffect(() => {
    setSection(isPick ? 'pick' : (urlSection || 'featured'))
    setPage(1)
  }, [isPick, urlSection])

  useEffect(() => {
    setLoading(true)
    const loadAll = async () => {
      try {
        let list = []
        if (section === 'pick') {
          const [bank, featured] = await Promise.all([
            client.get('/feed?section=bargain&page_size=100').catch(() => ({ data: { items: [] } })),
            client.get('/feed?section=featured&page_size=100').catch(() => ({ data: { items: [] } })),
          ])
          const bankItems = bank.data?.items || []
          const featuredItems = (featured.data?.items || []).filter((it) => {
            const disc = (it.detail || {}).discount || ''
            return /[01234]\.?\d*折/.test(disc) || /破产|重整/.test((it.tags || []).join(''))
          })
          list = [...bankItems, ...featuredItems]
        } else {
          const resp = await client.get(`/feed?section=${section}&page_size=100`)
          list = resp.data?.items || []
        }
        setAllItems(list)
      } catch { /* 拦截器已提示 */ } finally {
        setLoading(false)
      }
    }
    loadAll()
  }, [section])

  // 2) 客户端筛选（条件变化即时生效）
  const filtered = useMemo(() => {
    let list = [...allItems]
    if (region) list = list.filter((it) => ((it.detail || {}).region || '').includes(region))
    if (risk) list = list.filter((it) => (it.detail || {}).risk === risk)
    if (discount) {
      const max = parseFloat(discount)
      list = list.filter((it) => {
        const m = ((it.detail || {}).discount || '').match(/([\d.]+)折/)
        return m ? parseFloat(m[1]) <= max : false
      })
    }
    if (keyword) {
      // 2026-09-02 增强：搜索覆盖 标题/摘要/债务人/抵押物/地区/转让方（原只搜标题+简介）
      const kw = keyword.toLowerCase()
      list = list.filter((it) => {
        const d = it.detail || {}
        const hay = `${it.title} ${it.summary || ''} ${d.debtor_name || ''} ${d.collateral_type || ''} ${d.collateral_desc || ''} ${d.region || ''} ${d.transferor || ''} ${d.short_title || ''}`.toLowerCase()
        return hay.includes(kw)
      })
    }
    return list
  }, [allItems, region, risk, discount, keyword])

  // 3) 分页切片
  useEffect(() => {
    const start = (page - 1) * pageSize
    setItems(filtered.slice(start, start + pageSize))
  }, [filtered, page, pageSize])

  // 筛选条件变化时回到第 1 页
  useEffect(() => { setPage(1) }, [region, risk, discount, keyword, section])

  const regions = useMemo(() => {
    const set = new Set()
    allItems.forEach((it) => { const r = (it.detail || {}).region; if (r && r !== '—') set.add(r) })
    return [...set]
  }, [allItems])

  // 批量尽调（仅精选债权可用；已尽调债权不可重复选取）
  const startBatchDD = async () => {
    if (!token) { message.warning('请先登录后发起尽调'); navigate('/login'); return }
    if (selectedKeys.length === 0) { message.warning('请至少勾选 1 条债权'); return }
    if (selectedKeys.length > 5) { message.warning('单次最多勾选 5 条'); return }
    setDdLoading(true)
    try {
      // 检查勾选债权是否已尽调（同债务人已有任务/报告 → 阻止并提示跳转）
      const selected = items.filter((it) => selectedKeys.includes(it.id))
      const names = selected.map((it) => (it.detail || {}).debtor_name || (it.title || '').slice(0, 30)).filter(Boolean)
      try {
        const check = await claimApi.checkExisted(names)
        const existed = check.data?.existed || []
        if (existed.length > 0) {
          message.warning(`「${existed[0].debtor_name}」已经在您的任务列表中，不能重复尽调`, 5)
          Modal.confirm({
            title: '该笔债权已经在您的任务列表中',
            content: `「${existed[0].debtor_name}」已尽调过，不能重复选取。可前往任务列表查看或修改后重新尽调。`,
            okText: '前往我的任务',
            cancelText: '知道了',
            onOk: () => navigate('/tasks'),
          })
          return
        }
      } catch { /* 检查失败不阻塞，继续走原流程 */ }
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

  // 可尽调判定（用户规则 2026-08-31 + 2026-09-02 细化）：债务人 + 债权本金 + 抵押物合格(房产类+描述具体) 三者齐备
  const canDD = (it) => canDueDiligence(it.detail)

  // 精选债权表格（恢复原模式：每行最前勾选框，多选批量尽调，最多 5 条；三要素不全禁勾选）
  // 列宽规范（约定20）：首列 340 / 数值列 120 / 短列 100，与捡漏表格一致
  const tableColumns = [
    {
      title: '债权', dataIndex: 'title', key: 'title', width: 340,
      render: (v, r) => {
        const d = r.detail || {}
        const st = d.auction_status || ''
        return (
          <div>
            <Space size={4} wrap style={{ marginBottom: 2 }}>
              {st && <Tag color={st === '进行中' ? 'orange' : 'blue'}>{st}</Tag>}
              {canDD(r) ? <Tag color="green">可尽调</Tag> : <Tag>信息不全</Tag>}
            </Space>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{v}</div>
            <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>{r.source || ''}</div>
          </div>
        )
      },
    },
    { title: '债务人', key: 'debtor', width: 150, ellipsis: true, render: (_, r) => (r.detail || {}).debtor_name || '—' },
    { title: '债权金额', key: 'claim', width: 120, render: (_, r) => <Text strong style={{ color: 'var(--danger)' }}>{(r.detail || {}).claim_total || '—'}</Text> },
    { title: '起拍价', key: 'listing', width: 120, render: (_, r) => <Text strong style={{ color: 'var(--danger)' }}>{(r.detail || {}).listing_price || '—'}</Text> },
    { title: '抵押物', key: 'collateral', width: 120, ellipsis: true, render: (_, r) => (r.detail || {}).collateral_type || '—' },
    { title: '地区', key: 'region', width: 100, render: (_, r) => (r.detail || {}).region || '—' },
  ]

  // 捡漏专区/热门捡漏/公告：列表（列宽与精选表格统一：首列 340 / 数值列 120 / 短列 100）
  // 2026-09-03 用户修改：公告列表删除无用列（折扣/挂牌价/地区 对公告全为"—"）；
  // 折扣/挂牌价/地区仅捡漏专区/热门捡漏有值，保留
  const isNoticeTab = section === 'notice'
  const pickColumns = [
    {
      title: isNoticeTab ? '公告' : '捡漏标的', dataIndex: 'title', key: 'title', width: 340,
      render: (v, r) => (
        <Space>
          {isNoticeTab
            ? <Tag color="blue">{r.source || '公告'}</Tag>
            : <Tag color="orange" icon={<FireOutlined />}>捡漏</Tag>}
          <span style={{ fontWeight: 600, fontSize: 13 }}>{v}</span>
        </Space>
      ),
    },
    { title: '债权金额', key: 'claim', width: 120, render: (_, r) => <Text strong style={{ color: 'var(--danger)' }}>{(r.detail || {}).claim_total || '—'}</Text> },
    // 公告无折扣/挂牌价/地区概念 → 不展示（用户 2026-09-03）
    ...(isNoticeTab ? [] : [
      { title: '折扣', key: 'discount', width: 90, render: (_, r) => <Text style={{ color: 'var(--danger)' }}>{(r.detail || {}).discount || '—'}</Text> },
      { title: '挂牌价', key: 'listing', width: 130, render: (_, r) => <Text strong style={{ color: 'var(--danger)' }}>{(r.detail || {}).listing_price || '—'}</Text> },
      { title: '地区', key: 'region', width: 100, render: (_, r) => (r.detail || {}).region || '—' },
    ]),
    { title: '来源', key: 'source', width: 100, render: (_, r) => r.source || '—' },
  ]

  const filterBar = (
    <Space wrap style={{ marginBottom: 16 }}>
      <Select value={section} style={{ width: 160 }} onChange={(v) => { setSection(v); setPage(1) }}
        options={[
          { value: 'featured', label: '精选债权（可尽调）' },
          { value: 'pick', label: '捡漏专区' },
          { value: 'bargain', label: '热门捡漏' },
          { value: 'notice', label: '债权公告' },
        ]} />
      {/* 2026-09-03：公告 tab 无 地区/风险/折扣 维度，隐藏无用筛选（公告数据无这些字段） */}
      {!isNoticeTab && (
        <>
          <Select allowClear placeholder="地区" style={{ width: 130 }} value={region || undefined}
            onChange={(v) => setRegion(v || '')} options={regions.map((r) => ({ value: r, label: r }))} />
          <Select allowClear placeholder="风险等级" style={{ width: 120 }} value={risk || undefined}
            onChange={(v) => setRisk(v || '')}
            options={[{ value: 'low', label: '低风险' }, { value: 'medium', label: '中风险' }, { value: 'high', label: '高风险' }]} />
          <Select allowClear placeholder="折扣上限" style={{ width: 120 }} value={discount || undefined}
            onChange={(v) => setDiscount(v || '')}
            options={[{ value: '3', label: '≤3折' }, { value: '4', label: '≤4折' }, { value: '5', label: '≤5折' }, { value: '7', label: '≤7折' }]} />
        </>
      )}
      <Input.Search allowClear placeholder="搜索债务人/抵押物/地区/标题" style={{ width: 240 }} onSearch={(v) => setKeyword(v)} />
    </Space>
  )

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 80px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {isPick ? '捡漏专区' : section === 'bargain' ? '热门捡漏' : section === 'notice' ? '债权公告' : '精选债权'}
        </Typography.Title>
        <Text type="secondary" style={{ fontSize: 12 }}>共 {filtered.length} 条</Text>
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
      ) : filtered.length === 0 ? (
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
            getCheckboxProps: (r) => ({ disabled: !canDD(r) }),  // 三要素不全禁勾选
          } : undefined}
          onRow={(r) => ({ style: { cursor: 'pointer' }, onClick: () => navigate(`/asset/${r.id}`) })}
        />
      ) : (
        <Table rowKey="id" size="small" columns={pickColumns} dataSource={items} pagination={false}
          onRow={(r) => ({ style: { cursor: 'pointer' }, onClick: () => navigate(`/asset/${r.id}`) })} />
      )}

      {filtered.length > 0 && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Pagination current={page} pageSize={pageSize} total={filtered.length}
            onChange={(p) => { setPage(p); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
            showSizeChanger showQuickJumper />
        </div>
      )}
    </div>
  )
}
