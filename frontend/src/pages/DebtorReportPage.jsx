import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Descriptions, Button, Space, Typography, Spin, Table, Tag, Empty, Divider, message } from 'antd'
import { DownloadOutlined, ArrowLeftOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import client from '../api/client'
import { debtorProfileApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Title, Text } = Typography

/** 企业速览 网页版报告（与尽调报告同流程：查看 + 下载 PDF）2026-09-04 */
export default function DebtorReportPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [dl, setDl] = useState(false)

  useEffect(() => {
    if (!token) return // 路由守卫已渲染"请登录"占位(2026-09-07 不再整页跳登录)
    debtorProfileApi.detail(id)   // 后端返回 {ok, report}
      .then((resp) => { if (resp?.ok && resp.report) setReport(resp.report); else message.error(resp?.error || '报告不存在') })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id, token])

  const download = async () => {
    setDl(true)
    try {
      // 原生 fetch + blob（与债权尽调报告下载同款，避免 axios 拦截器对二进制的干扰 2026-09-06）
      const resp = await fetch(`/api/debtor-profile/${id}/download`, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' })
      if (!resp.ok) throw new Error('下载失败')
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${(report?.company || '企业')}企业速览.pdf`
      document.body.appendChild(a)
      a.click()
      URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch { /* 拦截器已提示 */ } finally {
      setDl(false)
    }
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  if (!report) return <Empty description="报告不存在或已删除" style={{ padding: 100 }} />

  const sum = report.summary || {}
  const sections = report.sections || []

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 60px' }}>
      <Space style={{ marginBottom: 12 }}>
        <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ paddingLeft: 0 }}>返回</Button>
        <Tag color="blue">企业速览</Tag>
      </Space>

      {/* 头部 */}
      <Card style={{ marginBottom: 16, background: 'linear-gradient(135deg,#f0f6ff,#ffffff)' }}>
        <Title level={2} style={{ marginBottom: 4, color: '#0d3b73' }}>{report.company}企业速览</Title>
        {report.search_name && report.search_name !== report.company && (
          <Text type="secondary">（已更名：{report.search_name}）</Text>
        )}
        <Descriptions column={{ xs: 1, md: 3 }} size="small" style={{ marginTop: 8 }}>
          <Descriptions.Item label="法定代表人">{sum.legal_person || '—'}</Descriptions.Item>
          <Descriptions.Item label="登记状态">{sum.status || '—'}</Descriptions.Item>
          <Descriptions.Item label="成立日期">{sum.established || '—'}</Descriptions.Item>
          <Descriptions.Item label="注册资本">{sum.capital || '—'}</Descriptions.Item>
          <Descriptions.Item label="股东数">{sum.shareholder_count ?? '—'} 名</Descriptions.Item>
          <Descriptions.Item label="数据截至">{report.queried_at || '—'}</Descriptions.Item>
        </Descriptions>
        {sum.credit_code && <Text type="secondary" style={{ fontSize: 12 }}>统一社会信用代码：{sum.credit_code}</Text>}
        <div style={{ marginTop: 12 }}>
          <Text strong style={{ marginRight: 8 }}>司法风险概况：</Text>
          {(sum.risk_breakdown || []).length === 0
            ? <Text type="secondary">未发现失信/被执行/冻结等记录</Text>
            : (sum.risk_breakdown || []).map((r) => (
              <Tag key={r.label} color={r.count > 0 ? 'red' : 'default'}>{r.label} {r.count} 条</Tag>
            ))}
        </div>
        <Space style={{ marginTop: 16 }}>
          <Button type="primary" icon={<DownloadOutlined />} loading={dl} disabled={!report.download_url} onClick={download}>
            下载 PDF（{report.company}企业速览）
          </Button>
          {!report.download_url && <Text type="secondary">PDF 未生成，可稍后重试</Text>}
        </Space>
      </Card>

      {/* 章节正文 */}
      {sections.length === 0 && <Empty description="报告内容为空" />}
      {sections.map((sec, i) => {
        const kvs = sec.kvs || []
        const tables = sec.tables || []
        return (
          <Card key={i} size="small" style={{ marginBottom: 16 }} title={<Text strong style={{ fontSize: 15 }}>{sec.h}</Text>}>
            {kvs.length > 0 && (
              <Descriptions column={{ xs: 1, md: 2 }} size="small" bordered style={{ marginBottom: 12 }}
                labelStyle={{ width: 130, background: 'var(--bg-soft, #F7F9FC)' }}>
                {kvs.map(([k, v], j) => {
                  // 长文本(≥18个汉字)跨整行, 避免窄列竖排(2026-09-08 用户反馈列宽/竖排难看)
                  const cjkLen = String(v || '').replace(/[^\u4e00-\u9fa5]/g, '').length
                  return (
                    <Descriptions.Item key={j} label={k} span={cjkLen >= 18 ? 2 : undefined}>
                      <span style={{ whiteSpace: 'pre-wrap' }}>{v || '—'}</span>
                    </Descriptions.Item>
                  )
                })}
              </Descriptions>
            )}
            {tables.map((tb, ti) => (
              <Table key={ti} size="small" bordered pagination={false} style={{ marginBottom: 12 }}
                scroll={{ x: 'max-content' }}
                rowKey={(_, ri) => ri}
                columns={(tb.headers || []).map((h, hi) => {
                  // 列宽按表头语义分配（2026-09-06：避免"几个字占一行"）
                  const w = /案号|编号|文号/.test(h) ? 170
                    : /日期|时间|年度|比例/.test(h) ? 130
                    : /金额|标的|评估|起拍/.test(h) ? 130
                    : /法院|机关|地区|地址/.test(h) ? 180
                    : /标题|名称|企业|公司|案由|内容|描述|当事人|建议|备注/.test(h) ? 240
                    : 150
                  return {
                    title: h || `列${hi + 1}`, dataIndex: `c${hi}`, key: `c${hi}`,
                    width: w,
                    render: (v) => <span style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>{v || ''}</span>,
                  }
                })}
                dataSource={(tb.rows || []).map((r) => {
                  const o = {}
                  ;(tb.headers || []).forEach((_, hi) => { o[`c${hi}`] = r[hi] || '' })
                  return o
                })} />
            ))}
            {sec.note && <Text type="secondary" style={{ fontSize: 12 }}>{sec.note}</Text>}
            {kvs.length === 0 && tables.length === 0 && !sec.note && <Text type="secondary">暂无数据</Text>}
          </Card>
        )
      })}

      <Divider />
      <Text type="secondary" style={{ fontSize: 12, display: 'block', textAlign: 'center' }}>
        本报告由 NPL CN 平台基于企查查公开数据生成，数据截至 {report.queried_at}，仅供参考，不构成投资建议。
      </Text>
    </div>
  )
}
