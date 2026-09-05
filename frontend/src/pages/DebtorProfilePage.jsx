import { useState } from 'react'
import { Card, Input, Button, Space, Typography, Modal, Alert, message } from 'antd'
import { SearchOutlined, IdcardOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { debtorProfileApi } from '../api'
import { useAuthStore } from '../store/auth'
import { useNavigate } from 'react-router-dom'

const { Title, Text } = Typography

const ORG_WORDS = ['有限公司', '股份', '集团', '公司', '有限合伙', '厂', '中心', '银行', '学校', '医院', '事务所', '合作社', '研究院']

function looksPerson(name) {
  const t = (name || '').trim()
  if (!t || t.length < 2 || t.length > 60) return false
  if (ORG_WORDS.some((w) => t.includes(w))) return false
  return /^[\u4e00-\u9fa5]{2,4}$/.test(t)
}

export default function DebtorProfilePage() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const [company, setCompany] = useState('')
  const [loading, setLoading] = useState(false)
  const [warning, setWarning] = useState(null)

  const onQuery = () => {
    const name = company.trim()
    if (!name) { message.warning('请输入企业名称'); return }
    if (!token) { message.warning('请先登录后查询'); navigate('/login', { state: { from: window.location.pathname + window.location.search } }); return }
    if (looksPerson(name)) {
      message.error('债务人画像仅支持企业。请填写企业工商全称（如“XX有限公司”），自然人不支持画像。')
      return
    }
    Modal.confirm({
      title: '确认生成企业速览报告？',
      content: (
        <div style={{ fontSize: 13 }}>
          <p style={{ marginBottom: 8 }}>将查询「{name}」并生成《{name}企业速览》PDF，涵盖：</p>
          <p style={{ color: '#595959', lineHeight: 1.9, marginBottom: 8 }}>
            工商登记 · 股东结构 · 实控人/受益所有人 · 主要人员 · 变更记录 · 对外投资/分支 · 年报财务 · 资质知产 · 司法风险（失信/被执行/限高/冻结/涉诉等）
          </p>
          <p style={{ fontSize: 12, color: '#8c8c8c' }}>已查询过的企业将直接复用结果，快速返回；报告将存入「我的报告」，可随时回看与重复下载。</p>
        </div>
      ),
      okText: '查询并生成',
      cancelText: '取消',
      onOk: () => doQuery(name),
    })
  }

  const doQuery = async (name) => {
    setLoading(true)
    setWarning(null)
    message.info('正在采集企业各维度信息并生成报告，首次查询约需 1-3 分钟，请勿关闭页面…', 6)
    try {
      const resp = await debtorProfileApi.query(name)   // 后端返回 {ok, report, summary, name_warning}
      if (resp?.ok && resp.report) {
        message.success('企业速览报告已生成')
        navigate(`/debtor-report/${resp.report.id}`)
      } else {
        message.error(resp?.error || '查询失败，请稍后重试')
      }
    } catch (e) {
      console.error('debtor profile query error:', e)
      message.error('查询失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 60px' }}>
      <Title level={3} style={{ marginBottom: 4 }}>债务人画像</Title>
      <Text type="secondary" style={{ fontSize: 13, display: 'block', marginBottom: 16 }}>
        输入债务人企业全称，一键生成《企业速览》正式报告（工商/股权/实控/变更/司法风险等维度，可下载 PDF，自动存入「我的报告」供随时回看与重复下载）。
      </Text>

      <Card style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%', maxWidth: 700 }}>
          <Input
            size="large"
            prefix={<IdcardOutlined style={{ color: 'var(--text-weak)' }} />}
            placeholder="输入企业工商全称，如：XX置业有限公司"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            onPressEnter={onQuery}
            allowClear
          />
          <Button size="large" type="primary" icon={<SearchOutlined />} loading={loading} onClick={onQuery}>
            查询并生成报告
          </Button>
        </Space.Compact>
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-weak)' }}>
          <SafetyCertificateOutlined /> 仅支持企业（自然人请用「财产线索」）；报告命名《XXX企业速览》，不包含"债务人画像"字样，适合正式场合使用。
        </div>
      </Card>

      {warning && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={warning} />}
    </div>
  )
}
