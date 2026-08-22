import { useEffect, useState } from 'react'
import { Card, Descriptions, Tag, Button, Typography, Spin, Alert, message, Row, Col, Space, Table, Statistic } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import { RobotOutlined, ArrowLeftOutlined, FundOutlined, ClockCircleOutlined, WarningOutlined, SolutionOutlined } from '@ant-design/icons'
import client from '../api/client'
import { claimApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'

const { Title, Text, Paragraph } = Typography

export default function AssetDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const setClaims = useClaimDraftStore((s) => s.setClaims)
  const [item, setItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [extracting, setExtracting] = useState(false)

  useEffect(() => {
    client.get(`/feed/${id}`)
      .then((resp) => setItem(resp.data))
      .catch(() => { /* 拦截器已提示 */ })
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  if (!item) return <div style={{ textAlign: 'center', padding: 80 }}><Title level={4}>内容不存在</Title></div>

  const detail = item.detail || {}
  const isBargain = item.section === 'bargain'

  // 估值三档（detail 或默认演示）
  const valuation = detail.valuation || { conservative: '—', neutral: '—', optimistic: '—' }

  const startDD = async () => {
    setExtracting(true)
    try {
      const sourceText = `${item.title}\n${item.summary || ''}\n${JSON.stringify(detail || {})}`
      const resp = await claimApi.importText(sourceText)
      setClaims(resp.data.claims)
      message.success('已提取字段，请确认后尽调')
      navigate('/preview')
    } catch { /* 拦截器已提示 */ } finally {
      setExtracting(false)
    }
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 16px' }}>
      <Space style={{ marginBottom: 12 }}>
        <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ paddingLeft: 0 }}>返回</Button>
        {isBargain ? <Tag color="orange" icon={<FundOutlined />}>捡漏标的</Tag> : <Tag color="green">债权信息</Tag>}
        {detail.discount && <Tag color="red">{detail.discount}</Tag>}
      </Space>
      <Title level={3} style={{ marginTop: 0 }}>{item.title}</Title>
      <Text type="secondary">来源：{item.source || '—'}</Text>

      <Row gutter={[16, 16]} style={{ marginTop: 20 }}>
        {/* 左栏：案件信息 + 招商原文 */}
        <Col xs={24} lg={15}>
          {/* 案件基本信息（截图3样式）*/}
          <Card title="案件基本信息" style={{ marginBottom: 16 }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="案号">{detail.case_no || '待补充'}</Descriptions.Item>
              <Descriptions.Item label="案由">{detail.cause || '—'}</Descriptions.Item>
              <Descriptions.Item label="本息">{detail.claim_total || '—'}</Descriptions.Item>
              <Descriptions.Item label="罚息">{detail.penalty || '—'}</Descriptions.Item>
              <Descriptions.Item label="判决结果">{detail.judgment || '待补充'}</Descriptions.Item>
              <Descriptions.Item label="执行状态">
                <Tag color={detail.execution === '执行中' ? 'orange' : detail.execution === '已判决' ? 'blue' : 'default'}>{detail.execution || '—'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="债务人" span={2}>{detail.debtor_name || item.tags?.[0] || '—'}</Descriptions.Item>
              <Descriptions.Item label="担保方式" span={2}>{detail.guaranty_type || '—'}</Descriptions.Item>
              <Descriptions.Item label="抵押物" span={2}>{detail.collateral_type || '—'}{detail.collateral_location ? `（${detail.collateral_location}）` : ''}</Descriptions.Item>
              <Descriptions.Item label="地区" span={2}>{detail.region || '—'}</Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 招商信息原文 */}
          <Card title="招商信息原文" style={{ marginBottom: 16 }}>
            <Paragraph>{item.summary || '暂无简介'}</Paragraph>
            {detail.sections && Object.entries(detail.sections).map(([k, v]) => (
              <div key={k} style={{ marginBottom: 12 }}>
                <Text strong>{k}</Text>
                <Paragraph style={{ marginBottom: 0 }}>{typeof v === 'string' ? v : JSON.stringify(v)}</Paragraph>
              </div>
            ))}
            {item.source_url && (
              <Button type="link" onClick={() => window.open(item.source_url, '_blank')}>查看原始公告 →</Button>
            )}
          </Card>
        </Col>

        {/* 右栏：快速信息 + 尽调评估 + 操作 */}
        <Col xs={24} lg={9}>
          {/* 快速信息 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>快速信息</div>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="债权转让方">{detail.transferor || item.source || '—'}</Descriptions.Item>
              <Descriptions.Item label="挂牌价">{detail.listing_price || detail.claim_total || '—'}</Descriptions.Item>
              <Descriptions.Item label="折扣率">{detail.discount || '—'}</Descriptions.Item>
            </Descriptions>
          </Card>

          {/* 尽调评估摘要（截图3）*/}
          <Card size="small" style={{ marginBottom: 16 }} title={<Space><FundOutlined style={{ color: 'var(--primary)' }} />尽调评估摘要</Space>}>
            <Row gutter={[8, 8]}>
              <Col span={8}><Statistic title="保守" value={valuation.conservative} valueStyle={{ fontSize: 16 }} /></Col>
              <Col span={8}><Statistic title="中性" value={valuation.neutral} valueStyle={{ fontSize: 16, color: 'var(--primary)' }} /></Col>
              <Col span={8}><Statistic title="乐观" value={valuation.optimistic} valueStyle={{ fontSize: 16, color: 'var(--success)' }} /></Col>
            </Row>
            <div style={{ marginTop: 12, fontSize: 13 }}>
              <Space><ClockCircleOutlined style={{ color: 'var(--primary)' }} />回收周期估算：<Text strong>{detail.recovery_cycle || '6-12个月'}</Text></Space>
            </div>
          </Card>

          {/* 注意事项 */}
          <Card size="small" style={{ marginBottom: 16, borderColor: '#faad14' }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}><WarningOutlined style={{ color: '#faad14', marginRight: 6 }} />注意事项</div>
            <Text style={{ fontSize: 12 }}>{detail.cautions || '建议关注司法进展和抵押物变现能力，注意优先债权和多重查封风险，综合评估后谨慎决策。'}</Text>
          </Card>

          {/* 处置建议 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}><SolutionOutlined style={{ color: 'var(--success)', marginRight: 6 }} />处置建议</div>
            <Text style={{ fontSize: 12 }}>{detail.disposal_advice || '建议等待诉讼结果后通过司法拍卖处置，或评估债权转让变现。'}</Text>
          </Card>

          {/* 操作 */}
          <Button type="primary" size="large" block icon={<RobotOutlined />} loading={extracting} onClick={startDD} style={{ marginBottom: 8 }}>
            一键尽调分析
          </Button>
          <Alert type="info" showIcon message="尽调流程" style={{ fontSize: 12 }}
            description="系统将提取债权要素 → 查询债务人工商/司法/抵押数据 → 生成九版块尽调报告（含估值与处置建议）。" />
        </Col>
      </Row>
    </div>
  )
}
