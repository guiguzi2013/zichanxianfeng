import { useEffect, useState } from 'react'
import { Input, Button, Tag, Row, Col, Spin, Empty, Typography, Space, Card, Alert, Divider } from 'antd'
import { SearchOutlined, FileTextOutlined, FundOutlined, RobotOutlined, FireOutlined, ArrowRightOutlined, BankOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import client from '../api/client'

const { Title, Text } = Typography

const SECTION_LABELS = { featured: '精选债权', bargain: '热门捡漏', notice: '债权公告' }

export default function SearchPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const q = params.get('q') || ''
  const [input, setInput] = useState(q)
  const [groups, setGroups] = useState({})
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!q) { setLoading(false); return }
    setLoading(true)
    client.get(`/search?q=${encodeURIComponent(q)}`).then((resp) => {
      setGroups(resp.data?.groups || {})
      setTotal(resp.data?.total || 0)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [q])

  const doSearch = () => {
    const kw = input.trim()
    if (kw) navigate(`/search?q=${encodeURIComponent(kw)}`)
  }

  const sectionKeys = ['featured', 'bargain', 'notice'].filter((k) => (groups[k] || []).length > 0)

  const renderCard = (item, isBargain) => {
    const d = item.detail || {}
    return (
      <Col xs={24} sm={12} lg={8} key={item.id}>
        <div className="kpi-card" style={{ cursor: 'pointer', height: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}
          onClick={() => navigate(`/asset/${item.id}`)}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {isBargain && <Tag color="orange" icon={<FireOutlined />}>捡漏</Tag>}
            {(item.tags || []).slice(0, 2).map((t, i) => <Tag key={i} color="blue">{t}</Tag>)}
            {d.region && <span style={{ fontSize: 11, color: 'var(--text-weak)' }}>{d.region}</span>}
          </div>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-main)' }}>{item.title}</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6, flex: 1 }}>
            {(item.summary || '暂无简介').slice(0, 60)}{(item.summary || '').length > 60 ? '…' : ''}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, flexWrap: 'wrap' }}>
            {d.claim_total && <span>本金 <Text strong style={{ color: 'var(--danger)' }}>{d.claim_total}</Text></span>}
            {d.discount && <span>折扣 <Text strong style={{ color: 'var(--danger)' }}>{d.discount}</Text></span>}
            {isBargain && d.listing_price && <span>挂牌 <Text strong style={{ color: 'var(--danger)' }}>{d.listing_price}</Text></span>}
          </div>
        </div>
      </Col>
    )
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 80px' }}>
      {/* 搜索框 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, maxWidth: 720 }}>
        <Input
          size="large"
          prefix={<SearchOutlined />}
          placeholder="搜索债权 / 债务人 / 抵押物 / 地区"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={doSearch}
        />
        <Button size="large" type="primary" onClick={doSearch}>搜索</Button>
      </div>

      {!q ? (
        <Empty description="请输入关键词搜索" style={{ padding: 80 }} />
      ) : loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : total > 0 ? (
        <>
          <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
            搜索「{q}」，找到 <Text strong>{total}</Text> 条结果
          </Text>
          {sectionKeys.map((sec) => (
            <div key={sec} style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                {sec === 'featured' ? <FundOutlined style={{ color: 'var(--primary)' }} /> : sec === 'bargain' ? <FireOutlined style={{ color: '#fa541c' }} /> : <FileTextOutlined style={{ color: 'var(--primary)' }} />}
                {SECTION_LABELS[sec]}（{groups[sec].length}）
              </div>
              {sec === 'notice' ? (
                <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '4px 16px' }}>
                  {groups[sec].map((n, i) => (
                    <div key={n.id} style={{ padding: '10px 0', borderBottom: i < groups[sec].length - 1 ? '1px solid var(--border-light)' : 'none', cursor: 'pointer' }}
                      onClick={() => navigate(`/asset/${n.id}`)}>
                      <Text strong style={{ fontSize: 13.5 }}>{n.title}</Text>
                      {n.summary && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{n.summary.slice(0, 80)}</div>}
                      <Text type="secondary" style={{ fontSize: 11 }}>{n.source || ''}</Text>
                    </div>
                  ))}
                </div>
              ) : (
                <Row gutter={[16, 16]}>
                  {groups[sec].map((item) => renderCard(item, sec === 'bargain'))}
                </Row>
              )}
            </div>
          ))}
        </>
      ) : (
        /* ===== 无结果引导页 ===== */
        <Card style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', padding: '20px 0 8px' }}>
            <SearchOutlined style={{ fontSize: 48, color: 'var(--text-weak)' }} />
            <Title level={4} style={{ marginTop: 12 }}>未找到与「{q}」相关的内容</Title>
            <Text type="secondary">本站暂未收录该信息，可能属于以下两种情况：</Text>
          </div>

          <Row gutter={[16, 16]} style={{ marginTop: 20 }}>
            {/* 卡片1：这是你的债权？→ 智能尽调 */}
            <Col xs={24} md={12}>
              <Card hoverable style={{ height: '100%', textAlign: 'center' }}>
                <RobotOutlined style={{ fontSize: 32, color: 'var(--primary)' }} />
                <div style={{ fontSize: 15, fontWeight: 700, margin: '10px 0 4px' }}>🧾 这是你的债权？</div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
                  上传文件或粘贴文本，系统自动提取要素并生成尽调报告
                </Text>
                <Space>
                  <Button type="primary" onClick={() => navigate('/upload')}>上传/粘贴尽调 <ArrowRightOutlined /></Button>
                </Space>
              </Card>
            </Col>
            {/* 卡片2：想查债务人？→ 财产线索 */}
            <Col xs={24} md={12}>
              <Card hoverable style={{ height: '100%', textAlign: 'center' }}>
                <BankOutlined style={{ fontSize: 32, color: 'var(--success)' }} />
                <div style={{ fontSize: 15, fontWeight: 700, margin: '10px 0 4px' }}>🏢 想查债务人？</div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
                  查询债务人和担保人的工商、司法与财产线索，评估追偿可能
                </Text>
                <Space>
                  <Button type="primary" onClick={() => navigate('/property-clues')}>财产线索查询 <ArrowRightOutlined /></Button>
                </Space>
              </Card>
            </Col>
          </Row>

          <Divider />
          <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--text-secondary)' }}>
            或者浏览本站全部内容：
            <Button type="link" onClick={() => navigate('/debts')}>精选债权</Button>
            <Button type="link" onClick={() => navigate('/debts?feature=pick')}>捡漏专区</Button>
            <Button type="link" onClick={() => navigate('/notices')}>债权公告</Button>
          </div>
        </Card>
      )}
    </div>
  )
}
