import { useEffect, useState } from 'react'
import { Card, Tabs, Button, Upload, message, Typography, Spin, Empty, Anchor, Tag, Table, List, Alert, Select, Space } from 'antd'
import { DownloadOutlined, InboxOutlined, RollbackOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { reportApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Title, Text, Paragraph } = Typography
const { Dragger } = Upload

// 九版块定义（与后端 schema 对应）
const SECTIONS = [
  { key: 'summary', title: '一、投资决策摘要' },
  { key: 'reminders', title: '二、重要提醒' },
  { key: 'claim_basic', title: '三、债权基本情况' },
  { key: 'debtor', title: '四、债务人调查' },
  { key: 'guarantor', title: '五、担保人调查' },
  { key: 'collateral', title: '六、抵押物分析' },
  { key: 'legal', title: '七、法律文书与法规依据' },
  { key: 'risk', title: '八、风控评估' },
  { key: 'disposal', title: '九、处置建议与投资决策' },
]

const fmt = (cents) => (cents != null ? `¥${(cents / 100).toLocaleString()}` : '⚠️ 需人工核实')

const UNKNOWN = <Tag color="orange">⚠️ 需人工核实</Tag>

function KV({ label, value, strong }) {
  return (
    <div style={{ marginBottom: 6, display: 'flex', gap: 8 }}>
      <Text strong style={{ minWidth: 110, flexShrink: 0 }}>{label}：</Text>
      <Text strong={strong}>{value || UNKNOWN}</Text>
    </div>
  )
}

function ListBlock({ title, items }) {
  if (!Array.isArray(items) || items.length === 0) return null
  return (
    <div style={{ marginBottom: 12 }}>
      <Text strong>{title}</Text>
      <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
        {items.map((x, i) => (
          <li key={i}><Text>{x}</Text></li>
        ))}
      </ul>
    </div>
  )
}

// ---- 各版块渲染 ----
function SummaryCard({ data }) {
  return (
    <>
      <KV label="综合评级" value={<Text style={{ color: '#d48806', fontSize: 18 }}>{data.rating || '—'}</Text>} />
      <KV label="建议买入价" value={data.suggested_buy_price_text || data.suggested_buy_ratio} />
      <KV label="预计回收率" value={data.expected_recovery_rate} />
      <KV label="预计回收周期" value={data.expected_recovery_cycle} />
      <ListBlock title="核心逻辑" items={data.core_logic} />
    </>
  )
}

function RemindersCard({ data }) {
  const items = data.items || []
  if (items.length === 0) return <Text type="secondary">未触发特殊提醒</Text>
  return (
    <Table
      size="small"
      rowKey="rule_id"
      pagination={false}
      dataSource={items}
      columns={[
        { title: '规则', dataIndex: 'rule_id', width: 80, render: (v) => <Tag color="blue">{v}</Tag> },
        { title: '触发条件', dataIndex: 'trigger', width: 220 },
        { title: '提醒内容', dataIndex: 'content' },
      ]}
    />
  )
}

function ClaimBasicCard({ data }) {
  const bt = data.basic_table || {}
  const idetail = data.interest_detail || {}
  return (
    <>
      <KV label="债务人名称" value={bt.debtor_name} />
      <KV label="债权本金" value={fmt(bt.principal_cents)} strong />
      <KV label="利息/罚息" value={fmt(bt.interest_cents)} />
      <KV label="担保类型" value={bt.guaranty_type} />
      <KV label="司法状态" value={bt.judicial_status} />
      {idetail.mode && idetail.mode !== 'none' && (
        <div style={{ marginTop: 12 }}>
          <Text strong>本息计算明细（{idetail.mode === 'with_judgment' ? '按判决书' : '按LPR估算'}）</Text>
          <Table
            size="small"
            rowKey="name"
            style={{ marginTop: 8 }}
            pagination={false}
            dataSource={idetail.items || []}
            columns={[
              { title: '项目', dataIndex: 'name' },
              { title: '金额', dataIndex: 'amount_cents', render: fmt },
              { title: '说明', dataIndex: 'note' },
            ]}
          />
          {idetail.basis_note && <Text type="secondary" style={{ fontSize: 12 }}>{idetail.basis_note}</Text>}
        </div>
      )}
    </>
  )
}

function DebtorCard({ data }) {
  const jr = data.judicial_risk || {}
  const reg = data.basic
  const factors = data.risk_factors || []
  const HIGH = ['被执行人', '失信信息', '限制高消费', '终本案件', '股权冻结']
  return (
    <>
      <KV label="债务人类型" value={data.type === 'person' ? '自然人' : '企业'} />
      {reg && typeof reg === 'object' ? (
        <>
          <KV label="企业名称" value={reg['企业名称']} strong />
          <KV label="登记状态" value={reg['登记状态']} />
          <KV label="法定代表人" value={reg['法定代表人']} />
          <KV label="注册资本" value={reg['注册资本']} />
          <KV label="成立日期" value={reg['成立日期']} />
          <KV label="统一社会信用代码" value={reg['统一社会信用代码']} />
          <KV label="注册地址" value={reg['注册地址']} />
        </>
      ) : reg ? (
        <KV label="工商信息" value={typeof reg === 'string' ? reg : JSON.stringify(reg)} />
      ) : (
        <KV label="工商信息" />
      )}
      {data.shareholders && (
        <KV
          label="股东信息"
          value={typeof data.shareholders === 'object' ? (data.shareholders['摘要'] || '已获取，详见明细') : data.shareholders}
        />
      )}
      {factors.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <Text strong>司法风险线索：</Text>
          <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
            {factors.map((f) => (
              <Tag key={f.label} color={HIGH.includes(f.label) ? 'red' : 'orange'}>
                {f.label} {f.count}
              </Tag>
            ))}
          </Space>
        </div>
      )}
      <KV label="司法风险" value={jr.note} />
      {jr.need_manual_verify && <Alert type="warning" showIcon message="司法数据需人工核实（免费渠道限制）" style={{ marginTop: 8 }} />}
    </>
  )
}

function GuarantorCard({ data }) {
  if (!data.present) return <Text type="secondary">无保证担保信息</Text>
  return (
    <>
      <KV label="担保人" value={data.guarantors ? data.guarantors.map((g) => g.name).join('、') : null} />
      {data.note && <Alert type="info" showIcon message={data.note} style={{ marginTop: 8 }} />}
    </>
  )
}

function CollateralCard({ data }) {
  if (!data.present) return <Text type="secondary">无抵押物信息</Text>
  return (
    <>
      {(data.items || []).map((item, i) => (
        <div key={i} style={{ marginBottom: 12 }}>
          <Paragraph style={{ marginBottom: 4 }}>{item.description}</Paragraph>
          {item.valuation?.data_insufficient && (
            <Text type="secondary" style={{ fontSize: 12 }}>估值数据不足，建议专业评估机构出具正式评估报告</Text>
          )}
          {item.valuation?.neutral && <KV label="中性估值" value={fmt(item.valuation.neutral.total_cents)} />}
        </div>
      ))}
    </>
  )
}

function LegalCard({ data }) {
  return (
    <>
      <KV label="裁判文书" value={data.documents?.not_found_note} />
      {data.statutes_note && <Alert type="warning" showIcon message={data.statutes_note} style={{ marginTop: 8 }} />}
    </>
  )
}

function RiskCard({ data }) {
  return (
    <>
      <ListBlock title="✅ 有利因素" items={data.favorable} />
      <ListBlock title="⚠️ 风险因素" items={data.risk} />
      <ListBlock title="📝 需人工核实事项" items={data.need_manual_verify} />
    </>
  )
}

function DisposalCard({ data }) {
  const plan = data.plan
  if (!plan) {
    return (
      <>
        <KV label="推荐处置路径" value={data.recommended_path} />
        <KV label="处置说明" value={data.note} />
        {Array.isArray(data.steps) && data.steps.length > 0 && <ListBlock title="操作步骤" items={data.steps} />}
      </>
    )
  }
  const PRIORITY = { high: { color: 'red', label: '🔴 优先' }, medium: { color: 'orange', label: '🟠 建议' }, info: { color: 'blue', label: '🔵 提示' } }
  return (
    <>
      <Alert
        type="info"
        showIcon
        message={`债权本息合计约 ${plan.debt_total_wan.toLocaleString()} 万元 · 追索紧迫度：${plan.priority_text}`}
        style={{ marginBottom: 12 }}
      />
      <Text strong>追索行动步骤（按顺序执行）：</Text>
      {(plan.actions || []).map((a) => {
        const pm = PRIORITY[a.priority] || PRIORITY.info
        return (
          <div key={a.step} style={{ display: 'flex', gap: 10, marginBottom: 10, background: '#FAFBFC', padding: 10, borderRadius: 6 }}>
            <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--primary)', color: '#fff', fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1 }}>
              {a.step}
            </div>
            <div style={{ flex: 1 }}>
              <Space size={8}>
                <Text strong>{a.title}</Text>
                <Tag color={pm.color} style={{ fontSize: 11 }}>{pm.label}</Tag>
              </Space>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>{a.detail}</div>
            </div>
          </div>
        )
      })}
      <div style={{ marginTop: 10 }}><Text strong>处置路径对比：</Text></div>
      {Object.values(plan.paths || {}).map((p, i) => (
        <div key={i} style={{ marginBottom: 10, padding: '8px 10px', background: '#F7F9FC', borderRadius: 6 }}>
          <Text strong style={{ fontSize: 13 }}>{p.title}</Text>
          {p.feasibility && <Tag style={{ marginLeft: 8 }} color="blue">{p.feasibility}</Tag>}
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 2 }}>{p.detail}</div>
          {p.risk && <div style={{ fontSize: 12, color: 'var(--warning)', marginTop: 2 }}>⚠️ {p.risk}</div>}
        </div>
      ))}
      {(plan.reminders || []).length > 0 && (
        <>
          <div style={{ marginTop: 8 }}><Text strong>重要提醒：</Text></div>
          {plan.reminders.map((r, i) => (
            <Alert key={i} type="warning" showIcon message={r} style={{ marginBottom: 6 }} />
          ))}
        </>
      )}
      {data.note && <Text type="secondary" style={{ fontSize: 12 }}>{data.note}</Text>}
    </>
  )
}

const RENDERERS = {
  summary: SummaryCard,
  reminders: RemindersCard,
  claim_basic: ClaimBasicCard,
  debtor: DebtorCard,
  guarantor: GuarantorCard,
  collateral: CollateralCard,
  legal: LegalCard,
  risk: RiskCard,
  disposal: DisposalCard,
}

function SectionCard({ section, data }) {
  if (!data) {
    return (
      <Card title={section.title} style={{ marginBottom: 16 }} id={section.key}>
        <Text type="secondary">该版块暂无数据（⚠️ 需人工核实）</Text>
      </Card>
    )
  }
  const Renderer = RENDERERS[section.key]
  return (
    <Card title={section.title} style={{ marginBottom: 16 }} id={section.key}>
      <Renderer data={data} />
    </Card>
  )
}

export default function ReportPage() {
  const { taskId } = useParams()
  const [reports, setReports] = useState([])
  const [activeKey, setActiveKey] = useState('0')
  const [loading, setLoading] = useState(true)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [versions, setVersions] = useState([])      // 历史版本列表
  const [viewing, setViewing] = useState(null)      // { version, content } 正在查看的历史版本
  const [restoring, setRestoring] = useState(false)

  const loadReports = async (tId) => {
    const resp = await reportApi.get(tId)
    setReports(resp.data.reports || [])
    return resp.data.reports || []
  }

  const loadVersions = async (reportId) => {
    try {
      const resp = await reportApi.versions(reportId)
      setVersions(resp.data?.versions || [])
    } catch { setVersions([]) }
  }

  useEffect(() => {
    const load = async () => {
      try {
        await loadReports(taskId)
        setActiveKey('0')
      } catch { /* 拦截器已提示 */ } finally {
        setLoading(false)
      }
    }
    load()
  }, [taskId])

  // 当前报告变化时加载历史版本
  const currentReportId = reports[Number(activeKey)]?.id
  useEffect(() => {
    if (currentReportId) {
      setViewing(null)
      loadVersions(currentReportId)
    }
  }, [currentReportId])

  // 补充材料后轮询等待报告版本更新
  const refreshAfterRegenerate = async (tId) => {
    const before = reports[Number(activeKey)] || {}
    const beforeVersion = before.version || 1
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const list = await loadReports(tId)
        const cur = list[Number(activeKey)] || {}
        if ((cur.version || 1) > beforeVersion) {
          message.success('报告已更新（新版本）', 2)
          return
        }
      } catch { /* 重新生成中，继续等 */ }
    }
    message.warning('报告更新较慢，请稍后刷新页面查看')
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  if (reports.length === 0) return <Empty style={{ padding: 80 }} description="暂无报告" />

  const report = reports[Number(activeKey)] || reports[0]
  const content = (viewing ? viewing.content : report.content) || {}
  const meta = content.report_meta || {}
  const sections = content.sections || {}

  const downloadPdf = async () => {
    setPdfLoading(true)
    try {
      await reportApi.pdf(report.id)
      message.success('PDF 已生成，正在下载…')
      // 后台生成需要一点时间，轮询下载接口直到就绪
      for (let i = 0; i < 10; i++) {
        await new Promise((r) => setTimeout(r, 1000))
        const ok = await tryDownloadPdf(report.id)
        if (ok) break
      }
    } catch { /* 拦截器已提示 */ } finally {
      setPdfLoading(false)
    }
  }

  const tryDownloadPdf = async (id) => {
    try {
      const token = useAuthStore.getState().token
      const resp = await fetch(`/api/reports/${id}/pdf/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!resp.ok) return false
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `债权尽调报告_${id}.pdf`
      a.click()
      URL.revokeObjectURL(url)
      return true
    } catch {
      return false
    }
  }

  // ---- 版本切换 ----
  const SOURCE_LABEL = { ai: 'AI生成', supplement: '补充材料触发', manual: '手动回退' }

  const onSelectVersion = async (v) => {
    if (v === report.version) {
      setViewing(null)
      return
    }
    try {
      const resp = await reportApi.versionDetail(report.id, v)
      setViewing({ version: v, content: resp.data?.content || null })
    } catch { /* 拦截器已提示 */ }
  }

  const onRestore = async () => {
    if (!viewing) return
    setRestoring(true)
    try {
      const resp = await reportApi.restoreVersion(report.id, viewing.version)
      message.success(resp.message || '已回退')
      setViewing(null)
      await loadReports(taskId)
      await loadVersions(report.id)
    } catch { /* 拦截器已提示 */ } finally {
      setRestoring(false)
    }
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 16px' }}>
      {/* 报告头 */}
      <Card style={{ marginBottom: 16, background: '#e8f0fe', border: 'none' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <Title level={4} style={{ marginBottom: 4 }}>债权尽职调查报告</Title>
            <Text type="secondary">
              债务人：{meta.debtor_name || '未知'}　|　报告编号：{meta.report_no || '—'}　|　生成时间：{meta.generated_at || '—'}
            </Text>
          </div>
          <Space>
            <Text type="secondary" style={{ fontSize: 13 }}>版本</Text>
            <Select
              value={viewing ? viewing.version : report.version}
              style={{ width: 200 }}
              onChange={onSelectVersion}
              options={[
                { value: report.version, label: `v${report.version}（当前）` },
                ...versions.map((v) => ({
                  value: v.version,
                  label: `v${v.version}（${SOURCE_LABEL[v.source] || v.source}）`,
                })),
              ]}
            />
          </Space>
        </div>
        {/* 历史版本查看提示条 */}
        {viewing && (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            message={`正在查看历史版本 v${viewing.version}（报告当前为 v${report.version}）`}
            action={
              <Space>
                <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => setViewing(null)}>
                  返回当前版本
                </Button>
                <Button size="small" type="primary" danger icon={<RollbackOutlined />} loading={restoring} onClick={onRestore}>
                  回退到此版本
                </Button>
              </Space>
            }
          />
        )}
      </Card>

      {/* 多债权切换 */}
      <Tabs
        activeKey={activeKey}
        onChange={setActiveKey}
        items={reports.map((r, i) => ({ key: String(i), label: r.content?.report_meta?.debtor_name || `债权${i + 1}` }))}
      />

      {/* 九版块 */}
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1 }}>
          {SECTIONS.map((s) => (
            <SectionCard key={s.key} section={s} data={sections[s.key]} />
          ))}
        </div>
        <div style={{ width: 200, position: 'sticky', top: 80, alignSelf: 'flex-start' }}>
          <Anchor
            items={SECTIONS.map((s) => ({ key: s.key, href: `#${s.key}`, title: s.title }))}
          />
        </div>
      </div>

      {/* 免责声明 */}
      <Card style={{ marginTop: 16, background: '#f5f7fa' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          本报告由资产先锋平台基于公开信息和AI分析自动生成，仅供参考，不构成投资建议。
          报告中的估值基于公开市场数据粗估，不替代专业评估机构出具的正式评估报告。
          投资决策请结合专业律师意见和实地尽调结果。
        </Text>
      </Card>

      {/* 底部：补充材料 + 下载PDF */}
      <Card style={{ marginTop: 16 }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 300 }}>
            <Paragraph strong>补充材料上传</Paragraph>
            <Dragger
              multiple
              accept=".doc,.docx,.txt,.pdf"
              beforeUpload={() => false}
              onChange={async ({ fileList }) => {
                const files = fileList.filter((f) => f.originFileObj).map((f) => f.originFileObj)
                if (files.length) {
                  try {
                    const resp = await reportApi.supplements(report.id, files)
                    const parsedCount = resp.data?.parsed?.length || 0
                    message.success(`已上传 ${files.length} 份（识别 ${parsedCount} 份），重新生成报告中…`)
                    // 轮询刷新报告（后台重新生成约需数秒）
                    await refreshAfterRegenerate(taskId, setReports, setActiveKey)
                  } catch { /* 拦截器已提示 */ }
                }
              }}
              showUploadList={false}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">上传判决书 / 评估报告 / 尽调说明等补充材料</p>
              <p className="ant-upload-hint">支持 Word / TXT / PDF，AI 自动识别并分发到对应版块</p>
            </Dragger>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <Button type="primary" size="large" icon={<DownloadOutlined />} loading={pdfLoading} onClick={downloadPdf}>
              下载报告 PDF
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
