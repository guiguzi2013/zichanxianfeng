import { useEffect, useState } from 'react'
import { Input, Button, Tag, Row, Col, Spin, Empty, Table, Tabs, Space, Typography } from 'antd'
import {
  SearchOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
  RiseOutlined,
  PercentageOutlined,
  FireOutlined,
  RobotOutlined,
  FundOutlined,
  SwapOutlined,
  BankOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { dashboardApi } from '../api'
import MarketChart from '../components/MarketChart'
import { marketDemo } from '../data/marketDemo'

const { Text } = Typography

const KPI_ICONS = [<DatabaseOutlined />, <ThunderboltOutlined />, <RiseOutlined />, <PercentageOutlined />]

export default function HomePage() {
  const navigate = useNavigate()
  const [feed, setFeed] = useState({})
  const [notices, setNotices] = useState([])
  const [dash, setDash] = useState(null)
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    Promise.all([
      client.get('/feed?page_size=100').catch(() => ({ data: { items: [] } })),
      client.get('/notices').catch(() => ({ data: { notices: [] } })),
      dashboardApi.get().catch(() => ({ data: null })),
    ]).then(([feedResp, noticeResp, dashResp]) => {
      const grouped = {}
      ;(feedResp.data?.items || []).forEach((item) => {
        ;(grouped[item.section] = grouped[item.section] || []).push(item)
      })
      setFeed(grouped)
      setNotices(noticeResp.data?.notices || [])
      setDash(dashResp.data)
    }).finally(() => setLoading(false))
  }, [])

  const onSearch = () => navigate(keyword ? `/upload?q=${encodeURIComponent(keyword)}` : '/upload')

  const featuredItems = (feed.featured || []).slice(0, 15)
  const bargainItems = (feed.bargain || []).slice(0, 6)
  const noticeItems = (feed.notice || []).slice(0, 4)

  const DEMO_FEATURED = [
    { id: 'd1', title: '深圳恒达实业债权转让项目', summary: '深圳恒达实业有限公司不良债权，抵押物为龙岗区商业物业，已进入司法执行程序。', tags: ['债权转让', '深度折扣'], source: '债权转让', detail: { claim_total: '5000万', debtor_name: '深圳恒达实业有限公司', guaranty_type: '抵押担保', collateral_type: '商业物业', region: '广东-深圳', discount: '5.0折', risk: 'medium' } },
    { id: 'd2', title: '上海锦程贸易抵押资产包', summary: '上海锦程贸易有限公司抵押债权包，含浦东新区工业厂房及设备，抵押登记完备。', tags: ['债权转让', '核心城市'], source: '债权转让', detail: { claim_total: '3200万', debtor_name: '上海锦程贸易有限公司', guaranty_type: '抵押担保', collateral_type: '工业厂房', region: '上海-浦东', discount: '6.0折', risk: 'medium' } },
    { id: 'd3', title: '北京万通房地产破产清算项目', summary: '北京万通房地产开发有限公司破产清算债权，抵押物为大兴区住宅用地。', tags: ['破产清算', '破产捡漏'], source: '破产专区', detail: { claim_total: '12000万', debtor_name: '北京万通房地产开发有限公司', guaranty_type: '抵押担保', collateral_type: '住宅用地', region: '北京-大兴', discount: '4.0折', risk: 'high' } },
    { id: 'd4', title: '杭州利达电子债权转让', summary: '杭州利达电子科技有限公司不良贷款债权，抵押物为余杭区工业厂房。', tags: ['债权转让'], source: '债权转让', detail: { claim_total: '1800万', debtor_name: '杭州利达电子科技有限公司', guaranty_type: '抵押担保', collateral_type: '工业厂房', region: '浙江-杭州', discount: '7.0折', risk: 'low' } },
    { id: 'd5', title: '广州盛业物流抵押债权', summary: '广州盛业物流有限公司抵押债权，抵押物为黄埔区仓储用地及仓库。', tags: ['抵押资产'], source: '抵押资产', detail: { claim_total: '8000万', debtor_name: '广州盛业物流有限公司', guaranty_type: '抵押担保', collateral_type: '仓储用地', region: '广东-广州', discount: '5.0折', risk: 'medium' } },
    { id: 'd6', title: '成都天府置业破产重整项目', summary: '成都天府置业有限公司破产重整债权，抵押物为高新区商业综合体。', tags: ['破产重整', '深度折扣'], source: '破产专区', detail: { claim_total: '25000万', debtor_name: '成都天府置业有限公司', guaranty_type: '抵押担保', collateral_type: '商业综合体', region: '四川-成都', discount: '3.0折', risk: 'high' } },
  ]
  const DEMO_BARGAIN = [
    { id: 'b1', title: '恒大相关债权包拍卖（12笔债权总额超2.7亿元）', summary: '阿里资产平台值得关注的标的——恒大相关债权包拍卖，12笔债权总额超2.7亿元，起拍价9.9元到301元不等，其中一笔1.03亿元的债权起拍价仅99元，相当于不到一折。目前已有52人报名。这批全是未诉债权，买家拿到后需自行走法律途径实现权益，有一定门槛，但价格确实够低，属于典型的"以小博大"捡漏型标的。', tags: ['不到1折', '以小博大'], source: '阿里资产', detail: { claim_total: '2.7亿(12笔)', debtor_name: '恒大相关', guaranty_type: '—', collateral_type: '—', region: '—', discount: '不到1折', risk: 'medium', valuation: { conservative: '—', neutral: '—', optimistic: '—' }, recovery_cycle: '12-24个月', cautions: '未诉债权，需自行诉讼实现权益，门槛较高。', disposal_advice: '低价购入后集中诉讼催收，注意诉讼时效与成本。' } },
    { id: 'b2', title: '某集团债权（阿里拍卖）', summary: '小额债权拍卖，本金10.15万元，起拍价406元。', tags: ['0.4折', '小额'], source: '阿里拍卖', detail: { claim_total: '10.15万', debtor_name: '某集团', guaranty_type: '信用', collateral_type: '无', region: '—', discount: '0.4折', risk: 'low' } },
    { id: 'b3', title: '某建材商行信用卡债权', summary: '信用卡不良债权，本金8.60万元，起拍价344元。', tags: ['0.4折', '小额'], source: '阿里拍卖', detail: { claim_total: '8.60万', debtor_name: '某建材商行', guaranty_type: '信用', collateral_type: '无', region: '—', discount: '0.4折', risk: 'low' } },
    { id: 'b4', title: '某贸易公司担保债权', summary: '小额担保债权，本金15.0万元，起拍价750元。', tags: ['0.5折', '小额'], source: '阿里拍卖', detail: { claim_total: '15.0万', debtor_name: '某贸易公司', guaranty_type: '保证', collateral_type: '无', region: '—', discount: '0.5折', risk: 'low' } },
    { id: 'b5', title: '某餐饮个体户经营贷款债权', summary: '个体经营贷款不良债权，本金5.80万元，起拍价348元。', tags: ['0.6折', '小额'], source: '阿里拍卖', detail: { claim_total: '5.80万', debtor_name: '某餐饮个体户', guaranty_type: '信用', collateral_type: '无', region: '—', discount: '0.6折', risk: 'low' } },
    { id: 'b6', title: '某物流个体户经营贷债权', summary: '个体经营贷款不良债权，本金11.8万元，起拍价708元，折扣0.6折。', tags: ['0.6折', '小额'], source: '阿里拍卖', detail: { claim_total: '11.80万', debtor_name: '某物流个体户', guaranty_type: '信用', collateral_type: '无', region: '—', discount: '0.6折', risk: 'low' } },
  ]
  const DEMO_NOTICES = [
    { id: 'n1', title: '工商银行浙江省分行转让不良贷款债权，涉及本金3.2亿元', summary: '包含15户对公不良贷款，抵押物涵盖杭州、宁波、温州等地商业物业及工业厂房。', source: '消费日报A16版' },
    { id: 'n2', title: '东莞某制造企业厂房及土地拍卖，起拍价5800万元', summary: '建筑面积约12000㎡，占地面积25000㎡，位于松山湖高新区附近。', source: '阿里拍卖' },
    { id: 'n3', title: '信达资产江苏办事处批量转让23户不良债权，总额8.7亿元', summary: '抵押物包括南京、苏州多处商业地产和工业用地，部分已进入司法执行程序。', source: '信达资产' },
    { id: 'n4', title: '长城资产深圳分公司债务催收暨债权转让通知，涉及12户', summary: '债权总额4.56亿元，抵押物主要集中在深圳关外及东莞地区。', source: '长城资产' },
  ]

  const featured = featuredItems.length ? featuredItems : DEMO_FEATURED
  const bargain = bargainItems.length ? bargainItems : DEMO_BARGAIN
  const notices2 = noticeItems.length ? noticeItems : DEMO_NOTICES

  const macroItems = (dash?.macro?.length ? dash.macro : [
    { label: '不良贷款余额', value: '3.4', unit: '万亿' },
    { label: '不良率', value: '1.56', unit: '%' },
    { label: '持牌 AMC', value: '62', unit: '家' },
    { label: '年处置规模', value: '1.8', unit: '万亿' },
  ]).map((m, i) => ({ ...m, key: i }))

  const kpiItems = dash?.kpis?.length
    ? dash.kpis.map((k, i) => ({ ...k, icon: KPI_ICONS[i % 4] }))
    : [
        { label: '在拍总数', value: '12,847', unit: '笔', icon: KPI_ICONS[0], trend: '+8.3% 较上月', trend_up: 1 },
        { label: '今日新增', value: '156', unit: '笔', icon: KPI_ICONS[1], trend: '+12.5% 较昨日', trend_up: 1 },
        { label: '近一年成交', value: '286.5', unit: '亿', icon: KPI_ICONS[2], trend: '+15.2% 环比', trend_up: 1 },
        { label: '平均折扣率', value: '31.2', unit: '%', icon: KPI_ICONS[3], trend: '-2.1% 同比', trend_up: 0 },
      ]

  // 拍卖平台表
  const auctionData = (dash?.auction || [
    { platform: '京东拍卖', on_auction: 687, sold: 218, sold_rate: 24.1, amount: 39.2 },
    { platform: '中拍平台', on_auction: 601, sold: 189, sold_rate: 21.1, amount: 33.4 },
    { platform: '北交所', on_auction: 314, sold: 98, sold_rate: 11.0, amount: 18.1 },
    { platform: '权益云', on_auction: 198, sold: 63, sold_rate: 6.9, amount: 9.8 },
    { platform: '阿里拍卖', on_auction: 12847, sold: 8721, sold_rate: 36.7, amount: 186.0 },
  ]).map((a, i) => ({ key: i, ...a }))

  const auctionColumns = [
    { title: '平台', dataIndex: 'platform', key: 'platform' },
    { title: '新上拍', dataIndex: 'on_auction', key: 'on_auction', align: 'right' },
    { title: '成交', dataIndex: 'sold', key: 'sold', align: 'right' },
    { title: '成交率', dataIndex: 'sold_rate', key: 'sold_rate', align: 'right', render: (v) => `${v}%` },
    { title: '成交额(亿)', dataIndex: 'amount', key: 'amount', align: 'right', render: (v) => `${v}` },
  ]

  const amcNational = (dash?.amc?.national || [
    { org_name: '中国华融', market_share: 24.5 },
    { org_name: '中国信达', market_share: 23.2 },
    { org_name: '中国东方', market_share: 20.5 },
    { org_name: '中国长城', market_share: 18.8 },
    { org_name: '中国银河', market_share: 13.0 },
  ])
  const amcLocal = (dash?.amc?.local || [
    { org_name: '浙商资产', market_share: 18.4 },
    { org_name: '广东粤财资产', market_share: 15.6 },
    { org_name: '江苏资产', market_share: 14.8 },
    { org_name: '山东金融资产', market_share: 12.9 },
    { org_name: '上海国有资产', market_share: 11.3 },
  ])
  const renderAmcRank = (list) => (
    <ul className="rank-list">
      {list.map((r, i) => (
        <li key={r.id || r.org_name}>
          <span className={`rank-index ${i < 3 ? 'top' : ''}`}>{i + 1}</span>
          <span className="rank-name">{r.org_name}</span>
          <div className="rank-bar"><div className="rank-bar-inner" style={{ width: `${Math.min(r.market_share * 2.6, 100)}%` }} /></div>
          <span className="rank-pct">{r.market_share}%</span>
        </li>
      ))}
      {list.length === 0 && <li style={{ color: 'var(--text-weak)' }}>暂无数据，请在管理后台录入</li>}
    </ul>
  )

  // 精选债权卡片（查看详情即可，尽调入口在详情页/列表批量尽调）
  const renderFeaturedCard = (item) => {
    const d = item.detail || {}
    const riskColor = d.risk === 'high' ? 'red' : d.risk === 'medium' ? 'orange' : 'green'
    const riskTag = d.risk ? (
      <Tag color={riskColor} style={{ position: 'absolute', top: 10, right: 10, marginInlineEnd: 0, zIndex: 1 }}>
        {d.risk === 'high' ? '高风险' : d.risk === 'medium' ? '中风险' : '低风险'}
      </Tag>
    ) : null
    return (
      <Col xs={24} md={12} lg={8} key={item.id}>
        <div className="kpi-card" style={{ cursor: 'pointer', height: '100%', display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}
          onClick={() => navigate(`/asset/${item.id}`)}>
          {riskTag}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', paddingRight: 70 }}>
            {(item.tags || []).slice(0, 2).map((t, i) => <Tag key={i} color="blue">{t}</Tag>)}
            {d.region && <span style={{ fontSize: 11, color: 'var(--text-weak)' }}>{d.region}</span>}
          </div>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-main)', paddingRight: 70 }}>{item.title}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6, flex: 1 }}>
            {(item.summary || '暂无简介').slice(0, 60)}{(item.summary || '').length > 60 ? '…' : ''}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, flexWrap: 'wrap' }}>
            {d.claim_total && <span>本金 <Text strong style={{ color: 'var(--danger)' }}>{d.claim_total}</Text></span>}
            {d.discount && <span>折扣 <Text strong style={{ color: 'var(--danger)' }}>{d.discount}</Text></span>}
            {d.collateral_type && d.collateral_type !== '无' && <span>抵押物 <Text strong>{d.collateral_type}</Text></span>}
          </div>
        </div>
      </Col>
    )
  }

  // 热门捡漏卡片（内容参考"恒大债权包"模板：起拍价/报名/分析；无尽调入口）
  const renderBargainCard = (item) => {
    const d = item.detail || {}
    const riskColor = d.risk === 'high' ? 'red' : d.risk === 'medium' ? 'orange' : 'green'
    const riskTag = d.risk ? (
      <Tag color={riskColor} style={{ position: 'absolute', top: 10, right: 10, marginInlineEnd: 0, zIndex: 1 }}>
        {d.risk === 'high' ? '高风险' : d.risk === 'medium' ? '中风险' : '低风险'}
      </Tag>
    ) : null
    return (
      <Col xs={24} md={12} key={item.id}>
        <div className="kpi-card" style={{ cursor: 'pointer', height: '100%', display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}
          onClick={() => navigate(`/asset/${item.id}`)}>
          {riskTag}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', paddingRight: 70 }}>
            <Tag color="orange" icon={<FireOutlined />}>捡漏</Tag>
            {(item.tags || []).slice(0, 2).map((t, i) => <Tag key={i} color="blue">{t}</Tag>)}
          </div>
          <div style={{ fontWeight: 600, fontSize: 13.5, color: 'var(--text-main)', lineHeight: 1.4, paddingRight: 70 }}>{item.title}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.7, flex: 1, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
            {item.summary || '暂无简介'}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, flexWrap: 'wrap' }}>
            {d.claim_total && <span>本金 <Text strong style={{ color: 'var(--danger)' }}>{d.claim_total}</Text></span>}
            {d.discount && <span>折扣 <Text strong style={{ color: 'var(--danger)' }}>{d.discount}</Text></span>}
          </div>
        </div>
      </Col>
    )
  }

  // 版块标题 + 可选"更多"（morePath 为空则不显示；部分版块纯展示无更多）
  const SectionTitle = ({ icon, title, sub, morePath }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {icon}
        <span className="section-title-text" style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-main)' }}>{title}</span>
        {sub && <span style={{ fontSize: 12, color: 'var(--text-weak)', fontWeight: 400 }}>{sub}</span>}
      </div>
      {morePath && (
        <span className="section-more" style={{ fontSize: 13, color: 'var(--primary)', cursor: 'pointer' }} onClick={() => navigate(morePath)}>更多 →</span>
      )}
    </div>
  )

  return (
    <>
      {/* ===== Hero 区：搜索框 banner + 四个业务入口小块（白底，移入 banner 内下方）===== */}
      <div className="hero-section">
        <div className="page-container" style={{ paddingBottom: 12 }}>
          <div className="hero-title">不良资产智能尽调平台</div>
          <div className="hero-subtitle">债权筛选 · 债务人信息查询 · 综合研判 · 一键生成尽调报告</div>
          <div className="hero-search">
            <Input size="large" prefix={<SearchOutlined />} placeholder="搜索债务企业 / 债权 / 抵押物（回车进入尽调）"
              value={keyword} onChange={(e) => setKeyword(e.target.value)} onPressEnter={onSearch} style={{ maxWidth: 560 }} />
            <Button size="large" type="primary" onClick={onSearch}>搜索</Button>
          </div>
          {/* 四个业务入口小块（白底，放搜索框背景图下方空位）*/}
          <div style={{ marginTop: 16 }}>
            <Row gutter={[12, 12]}>
              {[
                { icon: <RobotOutlined />, label: '智能尽调', desc: '单笔/批量债权尽调', path: '/upload', color: '#1a5fb4' },
                { icon: <FundOutlined />, label: '财产线索', desc: '债务人/担保人财产调查', path: '/property-clues', color: '#389e0d' },
                { icon: <SwapOutlined />, label: '债权对比', desc: '2-4笔债权横向对比', path: '/compare', color: '#d48806' },
                { icon: <BankOutlined />, label: '捡漏专区', desc: '破产清算/重整债权', path: '/debts?feature=pick', color: '#722ed1' },
              ].map((e) => (
                <Col xs={12} md={6} key={e.label}>
                  <div className="kpi-card" style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', background: '#fff' }} onClick={() => navigate(e.path)}>
                    <div style={{ width: 36, height: 36, borderRadius: 8, background: `${e.color}1A`, color: e.color, fontSize: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      {e.icon}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{e.label}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>{e.desc}</div>
                    </div>
                  </div>
                </Col>
              ))}
            </Row>
          </div>
        </div>
      </div>

      <div className="page-container" style={{ marginTop: 20 }}>
        {/* ===== 公告条（保留原位置，加"更多"）===== */}
        {notices.length > 0 && (
          <div className="notice-bar" style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="notice-tag">公告</span>
            <span className="notice-text" style={{ flex: 1, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{notices[0].title} · {notices[0].content || ''}</span>
            <span style={{ color: 'var(--text-weak)', fontSize: 12, flexShrink: 0 }}>{notices[0].published_at?.slice(0, 10)}</span>
            <span className="section-more" style={{ fontSize: 13, color: 'var(--primary)', cursor: 'pointer', flexShrink: 0 }} onClick={() => navigate('/notices')}>更多 →</span>
          </div>
        )}

        {/* ===== 三栏一行：宏观市场洞察（图形）| KPI（文字）| 最新债权公告 ===== */}
        <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
          {/* 宏观市场洞察：图形展示（纯展示，无更多）*/}
          <Col xs={24} md={8}>
            <div className="section-card" style={{ height: '100%' }}>
              <SectionTitle icon={<DatabaseOutlined style={{ color: 'var(--primary)' }} />} title="宏观市场洞察" />
              <Row gutter={[8, 8]} style={{ marginBottom: 8 }}>
                {macroItems.map((m) => (
                  <Col span={12} key={m.key}>
                    <div style={{ textAlign: 'center', padding: '6px 0', background: 'var(--bg-soft, #F7F9FC)', borderRadius: 6 }}>
                      <div className="kpi-value" style={{ fontSize: 20 }}>{m.value}<span className="kpi-unit">{m.unit}</span></div>
                      <div className="kpi-label" style={{ justifyContent: 'center', fontSize: 11 }}>{m.label}</div>
                    </div>
                  </Col>
                ))}
              </Row>
              <MarketChart option={marketDemo.columns[0].chart} height={140} />
              <div style={{ fontSize: 11, color: 'var(--text-weak)', marginTop: 6 }}>不良资产市场趋势（模拟数据）</div>
            </div>
          </Col>

          {/* 市场行情：文字展示（纯展示，无更多）*/}
          <Col xs={24} md={8}>
            <div className="section-card" style={{ height: '100%' }}>
              <SectionTitle icon={<ThunderboltOutlined style={{ color: '#d48806' }} />} title="市场行情" />
              <Row gutter={[8, 8]}>
                {kpiItems.map((k) => (
                  <Col span={12} key={k.label}>
                    <div style={{ padding: '12px 8px', background: 'var(--bg-soft, #F7F9FC)', borderRadius: 6, textAlign: 'center' }}>
                      <div className="kpi-label"><span style={{ color: 'var(--primary)' }}>{k.icon}</span> {k.label}</div>
                      <div className="kpi-value" style={{ fontSize: 22 }}>{k.value}<span className="kpi-unit">{k.unit}</span></div>
                      {k.trend && <div className={`kpi-trend ${k.trend_up ? 'up' : 'down'}`}>{k.trend}</div>}
                    </div>
                  </Col>
                ))}
              </Row>
              <div style={{ fontSize: 11, color: 'var(--text-weak)', marginTop: 8 }}>在拍总数 / 今日新增 / 近一年成交 / 平均折扣率</div>
            </div>
          </Col>

          {/* 最新债权公告（"更多"在版块下方）*/}
          <Col xs={24} md={8}>
            <div className="section-card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
              <SectionTitle icon={<FileTextOutlined style={{ color: 'var(--primary)' }} />} title="最新债权公告" />
              <div style={{ flex: 1 }}>
                {notices2.map((n, i) => (
                  <div key={n.id || i} style={{ padding: '8px 4px', borderBottom: i < notices2.length - 1 ? '1px solid var(--border-light)' : 'none', cursor: 'pointer' }}
                    onClick={() => navigate(`/asset/${n.id}`)}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <Text strong style={{ fontSize: 12.5 }} ellipsis>{n.title}</Text>
                    </div>
                    {n.summary && <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{n.summary}</div>}
                    <div style={{ fontSize: 10.5, color: 'var(--text-weak)', marginTop: 2 }}>{n.source || ''}</div>
                  </div>
                ))}
              </div>
              <div style={{ textAlign: 'right', marginTop: 8 }}>
                <span className="section-more" style={{ fontSize: 13, color: 'var(--primary)', cursor: 'pointer' }} onClick={() => navigate('/notices')}>更多 →</span>
              </div>
            </div>
          </Col>
        </Row>

        {/* ===== 拍卖平台 + AMC 市场（移到公告下方）===== */}
        <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
          <Col xs={24} md={14}>
            <div className="section-card" style={{ height: '100%' }}>
              <SectionTitle icon={<DatabaseOutlined style={{ color: 'var(--primary)' }} />} title="拍卖平台成交" />
              <Table size="small" columns={auctionColumns} dataSource={auctionData} pagination={false}
                locale={{ emptyText: '暂无数据，请在管理后台录入' }} />
              <div style={{ fontSize: 11, color: 'var(--text-weak)', marginTop: 8 }}>合计上拍 {auctionData.reduce((s, a) => s + a.on_auction, 0).toLocaleString()} ｜ 成交率 68% ｜ 数据来源：各拍卖平台（模拟）</div>
            </div>
          </Col>
          <Col xs={24} md={10}>
            <div className="section-card" style={{ height: '100%' }}>
              <SectionTitle icon={<BankOutlined style={{ color: '#722ed1' }} />} title="AMC 市场分析" />
              <Tabs size="small" items={[
                { key: 'national', label: '五大国有 AMC 份额', children: renderAmcRank(amcNational) },
                { key: 'local', label: '地方 AMC 挂牌', children: renderAmcRank(amcLocal) },
              ]} />
              <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>国有 AMC 总规模 9700 亿（模拟数据）</div>
            </div>
          </Col>
        </Row>

        {/* ===== 精选债权（重点版块，"更多"在右下角）===== */}
        <div className="section-card" style={{ marginBottom: 20 }}>
          <div className="section-title">
            精选债权
            <span style={{ fontSize: 12, color: 'var(--text-weak)', fontWeight: 400, marginLeft: 8 }}>共 {featured.length} 条</span>
          </div>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
          ) : (
            <Row gutter={[16, 16]}>
              {featured.map((item) => renderFeaturedCard(item))}
            </Row>
          )}
          <div style={{ textAlign: 'right', marginTop: 12 }}>
            <span className="section-more" style={{ fontSize: 13, color: 'var(--primary)', cursor: 'pointer' }} onClick={() => navigate('/debts')}>更多 →</span>
          </div>
        </div>

        {/* ===== 热门捡漏（"更多"在右下角）===== */}
        <div className="section-card" style={{ borderColor: '#ffd591', marginBottom: 20 }}>
          <div className="section-title">
            <FireOutlined style={{ color: '#fa541c', marginRight: 6 }} />热门捡漏
            <span style={{ fontSize: 12, color: 'var(--text-weak)', fontWeight: 400, marginLeft: 8 }}>低本金 · 深折扣 · 适合个人投资者</span>
          </div>
          <Row gutter={[16, 16]}>
            {bargain.map((item) => renderBargainCard(item))}
          </Row>
          <div style={{ textAlign: 'right', marginTop: 12 }}>
            <span className="section-more" style={{ fontSize: 13, color: 'var(--primary)', cursor: 'pointer' }} onClick={() => navigate('/debts?feature=pick')}>更多 →</span>
          </div>
        </div>
      </div>
    </>
  )
}
