import React, { useEffect, useState } from 'react'
import { Card, Tabs, Button, Upload, Input, message, Typography, Spin, Empty, Anchor, Tag, Table, List, Alert, Select, Space } from 'antd'
import { DownloadOutlined, InboxOutlined, RollbackOutlined, ArrowLeftOutlined, FileTextOutlined } from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { reportApi } from '../api'
import client from '../api/client'
import { useAuthStore } from '../store/auth'
import LoginModal from '../components/LoginModal'

const { Title, Text, Paragraph } = Typography
const { Dragger } = Upload

// 版块定义（与后端报告结构对应）
const SECTIONS = [
  { key: 'summary', title: '一、尽调结论摘要' },
  { key: 'reminders', title: '二、重要提醒' },
  { key: 'claim_basic', title: '三、债权基本情况' },
  { key: 'legal_completeness', title: '四、法律文件完备性' },
  { key: 'debtor', title: '五、债务人调查' },
  { key: 'guarantor', title: '六、担保人调查' },
  { key: 'collateral', title: '七、抵押物分析' },
  { key: 'legal', title: '八、法律文书与法规依据' },
  { key: 'execution_recovery', title: '九、司法执行与受偿分析' },
  { key: 'risk', title: '十、风控评估' },
  { key: 'disposal', title: '十一、处置方案' },
  { key: 'pending_supplements', title: '十二、待补充信息' },
  { key: 'supplement_info', title: '补充信息' },
]

const fmt = (cents) => (cents != null ? `¥${(cents / 100).toLocaleString()}` : '⚠️ 需人工核实')

const UNKNOWN = <Tag color="orange">⚠️ 需人工核实</Tag>

// 清洗系统内部技术性文案：异常类名/反爬/滑块/超时等不出现在用户界面
const TECHNICAL_PATTERNS = [/HTTP\w*Error/i, /HTTPStatus/i, /反爬/i, /滑块/i, /超时|timeout/i, /连接失败|Connection/i, /回退/i, /未启用/i]
function cleanNote(text) {
  if (!text) return text
  let s = String(text)
  for (const re of TECHNICAL_PATTERNS) {
    if (re.test(s)) return '暂未获取到，建议人工核实'
  }
  return s
}

function KV({ label, value, strong }) {
  // value 为 React 元素时透传（如星级 <Text>），仅字符串做技术文案清洗
  const display = typeof value === 'string' ? (cleanNote(value) || UNKNOWN) : (value || UNKNOWN)
  return (
    <div style={{ marginBottom: 6, display: 'flex', gap: 8 }}>
      <Text strong style={{ minWidth: 110, flexShrink: 0 }}>{label}：</Text>
      <Text strong={strong}>{display}</Text>
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
          <li key={i}><Text>{typeof x === 'string' ? x : (x.reason ? `${x.field}：${x.reason}` : JSON.stringify(x))}</Text></li>
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
  const val = idetail.validation || {}
  return (
    <>
      <KV label="债务人名称" value={bt.debtor_name} />
      <KV label="债权人" value={bt.creditor || bt.loan_bank} />
      {bt.debt_type && <KV label="债权类型" value={bt.debt_type} />}
      <KV label="债权本金" value={fmt(bt.principal_cents)} strong />
      <KV label="利息/罚息" value={fmt(bt.interest_cents)} />
      {bt.interest_method && <KV label="利息计算方式" value={bt.interest_method} />}
      <KV label="担保类型" value={bt.guaranty_type} />
      <KV label="司法状态" value={bt.judicial_status} />
      {bt.judgment_result && <KV label="是否胜诉" value={bt.judgment_result} />}
      {/* 本息校验（利息异常告警）*/}
      {val.interest_suspicious && <Alert type="warning" showIcon style={{ marginTop: 8 }} message={val.interest_suspicious} />}
      {idetail.mode && idetail.mode !== 'none' && (
        <div style={{ marginTop: 12 }}>
          <Text strong>本息计算明细（{idetail.mode === 'with_judgment' ? '按判决书利率' : idetail.mode === 'cutoff_continue' ? '截止日利息 + LPR续算' : idetail.mode === 'no_info' ? '按录入利息' : '按LPR估算'}）</Text>
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
          {/* 图2位置：利息说明（basis_note）*/}
          {idetail.basis_note && (
            <Alert type="info" showIcon style={{ marginTop: 8 }} message={idetail.basis_note} />
          )}
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
  const kyb = data.kyb || {}
  return (
    <>
      <KV label="债务人类型" value={data.type === 'person' ? '自然人' : '企业'} />
      {/* KYB 式主体核验摘要（借鉴企查查官方 SKILL） */}
      {kyb && (kyb.company_name || kyb.reg_status) && (
        <div style={{ marginBottom: 10, padding: '8px 10px', background: '#F6F8FA', borderRadius: 6 }}>
          <Text strong style={{ fontSize: 13 }}>主体核验：</Text>
          {data.data_as_of && <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>（企查查数据截至 {data.data_as_of}）</Text>}
          <div style={{ fontSize: 12, marginTop: 4 }}>
            {kyb.company_name && <div>企业名称：{kyb.company_name}</div>}
            {kyb.uscc && <div>统一社会信用代码：{kyb.uscc}</div>}
            {kyb.reg_status && <div>登记状态：{kyb.reg_status}</div>}
            {kyb.legal_rep && <div>法定代表人：{kyb.legal_rep}</div>}
            {kyb.established && <div>成立日期：{kyb.established}</div>}
          </div>
        </div>
      )}
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
          {factors.filter((f) => f.sample).length > 0 && (
            <div style={{ marginTop: 6, fontSize: 12, color: '#666', lineHeight: 1.7 }}>
              {factors.filter((f) => f.sample).map((f) => (
                <div key={`s-${f.label}`}>
                  <Text type="secondary">示例（{f.label}）：</Text>
                  <Text>{f.sample}</Text>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <KV label="司法风险" value={cleanNote(jr.note)} />
      {jr.need_manual_verify && <Alert type="warning" showIcon message="司法数据暂未获取到，建议人工核实" style={{ marginTop: 8 }} />}
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
  if (!data.present) return <Text type="secondary">无抵押物信息（待补充）</Text>
  const val = data.valuation || {}
  const cov = data.coverage_vs_interest || {}
  return (
    <>
      <KV label="抵押物描述" value={data.collateral_desc} />
      {/* 2026-09-02：房产证/抵押物明细（证上有的字段全部提取展示） */}
      {data.collateral_type && <KV label="抵押物类型" value={data.collateral_type} />}
      {data.property_cert_no && <KV label="产权证号" value={data.property_cert_no} />}
      {data.property_owner && <KV label="权利人" value={data.property_owner} />}
      {data.property_use && <KV label="房屋用途" value={data.property_use} />}
      {data.mortgage_reg_no && <KV label="抵押登记编号" value={data.mortgage_reg_no} />}
      {data.land_area_sqm && <KV label="土地面积" value={`${data.land_area_sqm}㎡`} />}
      {data.building_area_sqm && <KV label="建筑面积" value={`${data.building_area_sqm}㎡`} />}
      {data.build_year && <KV label="建成年份" value={data.build_year} />}
      {data.structure_type && <KV label="建筑结构" value={data.structure_type} />}
      {val.data_insufficient && <Alert type="warning" showIcon message={val.note || '估值数据不足，建议专业评估机构出具正式评估报告'} style={{ marginTop: 8, marginBottom: 8 }} />}
      {!val.data_insufficient && val.unit_price_range && (
        <>
          <KV label="估值区间（粗估）" value={`${(val.conservative_cents / 100 / 10000).toFixed(4)} ~ ${(val.optimistic_cents / 100 / 10000).toFixed(4)} 万元`} strong />
          <KV label="单价参考" value={val.unit_price_range} />
          <KV label="面积" value={val.area_sqm ? `${val.area_sqm}㎡` : null} />
          {data.valuation_method === 'cost' && (
            <Alert type="info" showIcon style={{ marginTop: 8, marginBottom: 8 }} message="成本法粗估：土地出让价 + 厂房建安造价×折旧" description={
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {(data.valuation_notes || []).map((n, i) => <li key={i} style={{ fontSize: 12, lineHeight: 1.8 }}>{n}</li>)}
              </ul>
            } />
          )}
          <Alert type="info" showIcon style={{ marginTop: 8, marginBottom: 8 }} message={val.estimate_note || '市场价格无法确定，估值仅为粗估，不替代专业评估'} />
        </>
      )}
      {cov.interest_total_cents && (
        <div style={{ marginTop: 12 }}>
          <Text strong>覆盖参考（债权人角度：本息合计 ÷ 抵押物估值）：</Text>
          <div style={{ marginTop: 8, display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <div style={{ padding: '10px 16px', background: '#F7F9FC', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: 'var(--text-weak)' }}>{cov.collateral_label || '抵押物主参考估值'}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--primary)' }}>{(cov.collateral_cents / 100 / 10000).toFixed(4)}万</div>
            </div>
            <div style={{ padding: '10px 16px', background: '#F7F9FC', borderRadius: 6, textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: 'var(--text-weak)' }}>本息合计</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--danger)' }}>{(cov.interest_total_cents / 100 / 10000).toFixed(4)}万</div>
            </div>
            {cov.coverage_ratio != null && (
              <div style={{ padding: '10px 16px', background: cov.covered ? '#f6ffed' : '#fff7e6', borderRadius: 6, textAlign: 'center', border: `1px solid ${cov.covered ? '#b7eb8f' : '#ffd591'}` }}>
                <div style={{ fontSize: 12, color: 'var(--text-weak)' }}>覆盖比例（本息/抵押物）</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: cov.covered ? '#389e0d' : '#d46b08' }}>{cov.coverage_ratio}%</div>
                <div style={{ fontSize: 12, color: cov.covered ? '#389e0d' : '#d46b08' }}>{cov.covered ? '覆盖' : '未覆盖'}</div>
              </div>
            )}
          </div>
          {cov.note && <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>{cov.note}</Text>}
        </div>
      )}
      {data.liquidity && <Alert type="info" showIcon style={{ marginTop: 8 }} message={data.liquidity} />}
      {data.ai_note && (
        <Alert type="info" showIcon style={{ marginTop: 8, background: '#eef4ff', border: '1px solid #b8d4f5' }} message="解读" description={<Text style={{ fontSize: 13 }}>{data.ai_note}</Text>} />
      )}
    </>
  )
}

function LegalCard({ data }) {
  const statutes = data.statutes || []
  return (
    <>
      <KV label="裁判文书" value={data.documents?.not_found_note} />
      {statutes.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          <Text strong>法规依据（依据现行有效法规）：</Text>
          <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
            {statutes.map((s, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                <Text strong>《{s.name}》</Text>
                {s.doc_no && <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>（{s.doc_no}）</Text>}
                {s.summary && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{s.summary}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>暂无适用的法规依据（如需引用请补充判决书/裁定书等材料）</Text>
      )}
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
  const paths = data.paths || []
  const actions = data.actions || []
  const PRIORITY = { high: { color: 'red', label: '🔴 优先' }, medium: { color: 'orange', label: '🟠 建议' }, info: { color: 'blue', label: '🔵 提示' } }
  return (
    <>
      <Alert
        type="info"
        showIcon
        message="以下处置路径由系统根据尽调数据自动生成，并列供参考；用户自行判断选择，不构成投资建议。"
        style={{ marginBottom: 12 }}
      />
      {/* 多路径并列（形式A）*/}
      <Text strong>处置路径（并列对比，请自行评估选择）：</Text>
      {paths.map((p, i) => (
        <div key={i} style={{ marginBottom: 12, padding: '10px 12px', background: '#F7F9FC', borderRadius: 6, border: '1px solid var(--border)' }}>
          <Space wrap>
            <Text strong style={{ fontSize: 14 }}>{p.name}</Text>
            {p.feasibility && <Tag color="blue">{p.feasibility}</Tag>}
          </Space>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>{p.detail}</div>
          {p.cycle_estimate && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>⏱ {p.cycle_estimate}</div>}
          {p.risk && <div style={{ fontSize: 12, color: 'var(--warning)', marginTop: 2 }}>⚠️ {p.risk}</div>}
        </div>
      ))}
      {/* 操作步骤指引 */}
      {actions.length > 0 && (
        <>
          <div style={{ marginTop: 8 }}><Text strong>操作步骤指引（按需执行）：</Text></div>
          {actions.map((a) => {
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
        </>
      )}
      {data.note && <Text type="secondary" style={{ fontSize: 12 }}>{data.note}</Text>}
      {data.coverage_warning && (
        <Alert type="warning" showIcon style={{ marginTop: 10 }} message="覆盖提示" description={<Text style={{ fontSize: 13 }}>{data.coverage_warning}</Text>} />
      )}
      {data.ai_note && (
        <Alert type="info" showIcon style={{ marginTop: 10, background: '#eef4ff', border: '1px solid #b8d4f5' }} message="解读" description={<Text style={{ fontSize: 13 }}>{data.ai_note}</Text>} />
      )}
    </>
  )
}

// 法律文件完备性（新）
function LegalCompletenessCard({ data }) {
  if (!data?.present) return <Text type="secondary">暂无法律文件信息（待补充）</Text>
  return (
    <>
      <Table
        size="small"
        rowKey="item"
        pagination={false}
        dataSource={data.items || []}
        columns={[
          { title: '文件/事项', dataIndex: 'item' },
          { title: '状态', dataIndex: 'status', width: 100, render: (v) => <Tag color={v === '已具备' ? 'green' : v === '待补充' ? 'orange' : 'default'}>{v}</Tag> },
          { title: '说明', dataIndex: 'note' },
        ]}
      />
      {data.note && <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>{data.note}</Text>}
    </>
  )
}

// 司法执行与受偿分析（新）
function ExecutionRecoveryCard({ data }) {
  if (!data) return null
  const er = data.execution_records || {}
  return (
    <>
      <KV label="司法状态" value={data.judicial_status} />
      <KV label="抵押顺位" value={data.mortgage_rank} />
      <KV label="查封情况" value={data.seizure} />
      {(er.executed || er.dishonest || er.limited_consumption) && (
        <div style={{ marginBottom: 8 }}>
          <Text strong>执行记录：</Text>
          <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
            {er.executed > 0 && <Tag color="red">被执行人 {er.executed}</Tag>}
            {er.dishonest > 0 && <Tag color="red">失信 {er.dishonest}</Tag>}
            {er.limited_consumption > 0 && <Tag color="orange">限高 {er.limited_consumption}</Tag>}
          </Space>
        </div>
      )}
      {data.repayment_priority_note && <Alert type="info" showIcon style={{ marginBottom: 8 }} message={data.repayment_priority_note} />}
      {data.execution_objection_risk && (
        <Alert type="warning" showIcon style={{ marginBottom: 8 }}
          message={data.execution_objection_risk.risk}
          description={data.execution_objection_risk.law_ref ? `法律依据：${data.execution_objection_risk.law_ref}` : undefined}
        />
      )}
      {data.ai_note && (
        <Alert type="info" showIcon style={{ marginBottom: 8, background: '#eef4ff', border: '1px solid #b8d4f5' }} message="解读" description={<Text style={{ fontSize: 13 }}>{data.ai_note}</Text>} />
      )}
    </>
  )
}

// 待补充信息清单（新）
function PendingSupplementsCard({ data }) {
  const items = Array.isArray(data) ? data : []
  if (items.length === 0) return <Text type="secondary">暂无待补充信息</Text>
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 8 }} message="以下信息补充后，报告将自动更新到对应版块（产生新版本）：" />
      {items.map((it, i) => (
        <div key={i} style={{ padding: '8px 10px', marginBottom: 6, background: '#FAFBFC', borderRadius: 6 }}>
          <Text strong style={{ fontSize: 13 }}>{it.field}</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>{it.reason}</Text>
        </div>
      ))}
    </>
  )
}

const RENDERERS = {
  summary: SummaryCard,
  reminders: RemindersCard,
  claim_basic: ClaimBasicCard,
  legal_completeness: LegalCompletenessCard,
  debtor: DebtorCard,
  guarantor: GuarantorCard,
  collateral: CollateralCard,
  legal: LegalCard,
  execution_recovery: ExecutionRecoveryCard,
  risk: RiskCard,
  disposal: DisposalCard,
  pending_supplements: PendingSupplementsCard,
  supplement_info: SupplementInfoCard,
}

// 补充信息章节：用户补充的文字说明 + 上传材料清单
function SupplementInfoCard({ data }) {
  if (!data || (!data.user_notes?.length && !data.file_count)) {
    return <Text type="secondary">暂无补充信息</Text>
  }
  return (
    <>
      {data.summary && <Alert type="success" showIcon message={data.summary} style={{ marginBottom: 12 }} />}
      {data.user_notes && data.user_notes.length > 0 && (
        <>
          <Text strong>用户补充说明：</Text>
          <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
            {data.user_notes.map((n, i) => (
              <li key={i} style={{ marginBottom: 6 }}><Text>{n}</Text></li>
            ))}
          </ul>
        </>
      )}
      {data.file_count > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text strong>补充材料：</Text>{' '}
          <Text type="secondary">已上传 {data.file_count} 份材料（判决书/评估报告/尽调说明等），已结合到本报告分析中</Text>
        </div>
      )}
    </>
  )
}

// 章节渲染错误边界：单个章节崩溃不影响整页（显示错误提示而非白屏）
class SectionBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  componentDidCatch(error) {
    console.error('section render error:', error)
  }
  render() {
    if (this.state.hasError) {
      return (
        <Card title={this.props.title} style={{ marginBottom: 16 }}>
          <Text type="secondary">该版块渲染异常，请尝试刷新或联系客服</Text>
        </Card>
      )
    }
    return this.props.children
  }
}

function SectionCard({ section, data }) {
  if (!data || (typeof data === 'object' && !Array.isArray(data) && Object.keys(data).length === 0)) {
    return (
      <Card title={section.title} style={{ marginBottom: 16 }} id={section.key}>
        <Text type="secondary">该版块暂无数据（⚠️ 需人工核实）</Text>
      </Card>
    )
  }
  const Renderer = RENDERERS[section.key]
  return (
    <SectionBoundary title={section.title}>
      <Card title={section.title} style={{ marginBottom: 16 }} id={section.key}>
        <Renderer data={data} />
      </Card>
    </SectionBoundary>
  )
}

export default function ReportPage() {
  const { taskId, reportId } = useParams()
  const navigate = useNavigate()
  const currentUser = useAuthStore((s) => s.user)
  const token = useAuthStore((s) => s.token)
  const isEditorView = currentUser?.role === 'editor' || currentUser?.role === 'admin' // 管理后台查看（员工不能下载）
  const [reports, setReports] = useState([])
  const [currentReportId, setCurrentReportId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [versions, setVersions] = useState([])      // 历史版本列表
  const [viewing, setViewing] = useState(null)      // { version, content } 正在查看的历史版本
  const [restoring, setRestoring] = useState(false)
  const [supplementNote, setSupplementNote] = useState('')   // 补充文字
  const [supplementFiles, setSupplementFiles] = useState([]) // 补充文件
  const [regenerating, setRegenerating] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [pendingUrl, setPendingUrl] = useState(null) // 登录后待下载的附件 URL

  const loadReports = async (tId) => {
    const resp = await reportApi.get(tId)
    const list = resp.data.reports || []
    setReports(list)
    return list
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
        const list = await loadReports(taskId)
        // 优先按 URL 的 reportId 定位；无则取第一份
        const target = list.find((r) => String(r.id) === String(reportId)) || list[0]
        setCurrentReportId(target ? target.id : null)
      } catch { /* 拦截器已提示 */ } finally {
        setLoading(false)
      }
    }
    load()
  }, [taskId, reportId])

  // 当前报告变化时加载历史版本
  useEffect(() => {
    if (currentReportId) {
      setViewing(null)
      loadVersions(currentReportId)
    }
  }, [currentReportId])

  // 补充材料后轮询等待报告版本更新
  const refreshAfterRegenerate = async (tId) => {
    const before = reports.find((r) => r.id === currentReportId) || {}
    const beforeVersion = before.version || 1
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const list = await loadReports(tId)
        const cur = list.find((r) => r.id === currentReportId) || {}
        if ((cur.version || 1) > beforeVersion) {
          message.success('报告已更新（新版本）', 2)
          return
        }
      } catch { /* 重新生成中，继续等 */ }
    }
    message.warning('报告更新较慢，请稍后刷新页面查看')
  }

  // 附件下载（2026-09-01：未登录先弹登录框，登录后留在原页自动继续下载；
  // 拦截器已解包 resp.data，resp 即 Blob——勿再取 resp.data 否则生成 9 字节坏文件）
  const doDownload = async (url) => {
    try {
      const resp = await client.get(url.replace(/^\/api/, ''), { responseType: 'blob' })
      const blob = resp
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = `附件_${url.split('/').pop()}`
      document.body.appendChild(a)
      a.click()
      URL.revokeObjectURL(objUrl)
      document.body.removeChild(a)
    } catch (e) {
      if (e?.response?.status === 401) {
        setPendingUrl(url)
        setLoginOpen(true)
      } else {
        message.error(e?.response?.data?.detail || e.message || '下载失败')
      }
    }
  }

  const downloadAttachment = (url) => {
    if (!token) {
      setPendingUrl(url)
      setLoginOpen(true)
      return
    }
    doDownload(url)
  }

  const onLoginSuccess = () => {
    if (pendingUrl) {
      const u = pendingUrl
      setPendingUrl(null)
      doDownload(u)
    }
  }

  // 提交补充信息（文字 + 文件），触发重新生成
  const submitSupplements = async () => {
    if (!supplementNote.trim() && supplementFiles.length === 0) return
    setRegenerating(true)
    try {
      const resp = await reportApi.supplements(report.id, supplementFiles, supplementNote.trim() || null)
      message.success('补充信息已提交，报告重新生成中…')
      setSupplementNote('')
      setSupplementFiles([])
      // 轮询等待新版本
      const before = report.version || 1
      for (let i = 0; i < 15; i++) {
        await new Promise((r) => setTimeout(r, 2000))
        try {
          const list = await loadReports(taskId)
          const cur = list.find((r) => r.id === report.id) || {}
          if ((cur.version || 1) > before) {
            message.success(`报告已更新为 v${cur.version}`, 2)
            return
          }
        } catch { /* 重新生成中，继续等 */ }
      }
      message.warning('报告更新较慢，请稍后刷新页面查看')
    } catch { /* 拦截器已提示 */ } finally {
      setRegenerating(false)
    }
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  if (reports.length === 0) return <Empty style={{ padding: 80 }} description="暂无报告" />

  const report = reports.find((r) => r.id === currentReportId) || reports[0]
  const content = (viewing ? viewing.content : report.content) || {}
  const meta = content.report_meta || {}
  const sections = content.sections || {}
  const conclusion = content.conclusion_bar || {}

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
  const SOURCE_LABEL = { ai: '系统生成', supplement: '补充材料触发', manual: '手动回退' }

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
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 48px' }}>
      {/* 报告头：正式渐变风格 */}
      <div style={{
        borderRadius: 12, padding: '28px 32px', marginBottom: 16, color: '#fff',
        background: 'linear-gradient(135deg, #0d3b73 0%, #1a5fb4 55%, #3d8bf5 100%)',
        boxShadow: '0 4px 16px rgba(26,95,180,.25)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap',
      }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: 1, marginBottom: 8 }}>债权尽职调查报告</div>
          <div style={{ fontSize: 13, opacity: .9, lineHeight: 1.9 }}>
            债务人：{meta.debtor_name || '未知'}<br />
            报告编号：{meta.report_no || '—'}　|　生成时间：{meta.generated_at ? String(meta.generated_at).replace('T', ' ').slice(0, 16) : '—'}
          </div>
        </div>
        <Space align="center" size={12}>
          <Space>
            <Text style={{ color: '#fff', opacity: .85, fontSize: 13 }}>版本</Text>
            <Select
              value={viewing ? viewing.version : report.version}
              style={{ width: 180 }}
              tooltip="版本说明：v1 为首次系统生成；每次上传补充材料（判决书/评估报告等）或补充信息后系统自动重新生成，版本+1，历史版本可查看/回退。"
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
          <Button
            type="primary"
            size="large"
            icon={<DownloadOutlined />}
            loading={pdfLoading}
            onClick={downloadPdf}
            style={{ background: '#fff', color: '#1a5fb4', border: 'none', fontWeight: 600 }}
          >
            下载报告 PDF
          </Button>
        </Space>
      </div>
      {/* 历史版本查看提示条 */}
      {viewing && (
        <Alert
          style={{ marginBottom: 16 }}
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

      {/* 顶部结论条：关键数字（正式卡片风格）*/}
      {conclusion.rating && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          {[
            { label: '本金', value: conclusion.principal_text || '—', color: '#222', size: 20 },
            { label: `本息合计（${conclusion.interest_basis_label || '截止今日'}）`, value: `≈ ${conclusion.interest_total_text || '—'}`, color: '#cf1322', size: 20 },
            { label: '抵押物估值（粗估）', value: String(conclusion.collateral_valuation_text || '—').split('（')[0], color: '#1a5fb4', size: 16 },
          ].map((item) => (
            <div key={item.label} style={{
              flex: 1, minWidth: 160, background: '#fff', borderRadius: 10,
              padding: '14px 18px', boxShadow: '0 2px 8px rgba(0,0,0,.06)', border: '1px solid #f0f0f0',
            }}>
              <div style={{ fontSize: 12, color: 'var(--text-weak)', marginBottom: 6 }}>{item.label}</div>
              <div style={{ fontSize: item.size, fontWeight: 700, color: item.color, lineHeight: 1.3 }}>{item.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* 主体 + 侧边栏：报告主体（含补充信息区块）在左，侧边栏独立在右，互不干扰 */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* 左侧大区块：报告主体 + 免责声明 + 补充信息输入区 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {SECTIONS.map((s) => (
            <SectionCard key={s.key} section={s} data={sections[s.key]} />
          ))}

          {/* 免责声明 */}
          <Card style={{ marginTop: 16, background: '#f5f7fa' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              本报告由 NPL CN 平台基于公开信息和系统分析自动生成，仅供参考，不构成投资建议。
              报告中的估值基于公开市场数据粗估，不替代专业评估机构出具的正式评估报告。
              投资决策请结合专业律师意见和实地尽调结果。
            </Text>
          </Card>

          {/* 补充信息输入区：文字输入框 + 材料上传 + 重新生成报告（与报告主体同区块） */}
          <Card style={{ marginTop: 16, border: '1px solid #b7eb8f' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Paragraph strong style={{ margin: 0, fontSize: 15 }}>补充信息</Paragraph>
              <Text type="secondary" style={{ fontSize: 12 }}>可补充文字说明和/或上传材料，系统将结合原信息重新分析生成报告（版本+1）</Text>
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 320 }}>
                <Input.TextArea
                  rows={3}
                  placeholder="补充文字说明，如：已取得判决书（案号…）、抵押物实际占用情况、新增财产线索等…"
                  value={supplementNote}
                  onChange={(e) => setSupplementNote(e.target.value)}
                />
                <div style={{ marginTop: 8 }}>
                  <Dragger
                    multiple
                    accept=".doc,.docx,.txt,.pdf,.jpg,.jpeg,.png"
                    beforeUpload={() => false}
                    onChange={({ fileList }) => setSupplementFiles(fileList.filter((f) => f.originFileObj).map((f) => f.originFileObj))}
                    showUploadList={{ maxCount: 5 }}
                    style={{ padding: '8px 0' }}
                  >
                    <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}><InboxOutlined /></p>
                    <p style={{ fontSize: 13, margin: 0 }}>上传判决书 / 评估报告 / 尽调说明 / 图片等补充材料（可选）</p>
                  </Dragger>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <Button
                  type="primary"
                  size="large"
                  icon={<RollbackOutlined />}
                  loading={regenerating}
                  disabled={!supplementNote.trim() && supplementFiles.length === 0}
                  onClick={submitSupplements}
                >
                  重新生成报告
                </Button>
              </div>
            </div>
          </Card>

          {/* 重要文件（2026-09-01：尽调债权关联的公告附件，可下载） */}
          {(() => {
            const links = (sections.claim_basic || {}).basic_table?.attachment_links || []
            if (links.length === 0) return null
            return (
              <Card title={<Space><FileTextOutlined />重要文件</Space>} style={{ marginTop: 16, border: '1px solid #b7eb8f' }}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                  该债权原公告附有信息文件（资产清单/抵押物清单/判决书等），已保存到平台，可下载查看：
                </Text>
                <Space direction="vertical" style={{ width: '100%' }} size={6}>
                  {links.map((url, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, padding: '6px 10px', background: '#EFFAF5', borderRadius: 6, border: '1px solid #B7EBD6' }}>
                      <Text style={{ fontSize: 13 }}>公告附件 {i + 1}</Text>
                      <Button size="small" type="primary" icon={<DownloadOutlined />}
                        onClick={() => downloadAttachment(url)}>
                        下载
                      </Button>
                    </div>
                  ))}
                </Space>
              </Card>
            )
          })()}
        </div>

        {/* 右侧边栏：大纲 + 按钮（独立区块） */}
        <div style={{ width: 220, position: 'sticky', top: 80, alignSelf: 'flex-start' }}>
          <div style={{
            background: '#fff', borderRadius: 10, border: '1px solid #f0f0f0',
            boxShadow: '0 2px 8px rgba(0,0,0,.06)', padding: '12px 8px',
          }}>
            <Anchor
              items={SECTIONS.map((s) => ({ key: s.key, href: `#${s.key}`, title: s.title }))}
            />
            {/* 下载按钮 + 返回我的报告（与大纲同一容器，一起滚动） */}
            <div style={{ padding: '10px 4px 0', borderTop: '1px solid #f0f0f0', marginTop: 8 }}>
              <Button type="primary" block size="large" icon={<DownloadOutlined />} loading={pdfLoading} onClick={downloadPdf}>
                下载报告 PDF
              </Button>
              <div style={{ marginTop: 6, textAlign: 'center' }}>
                <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/tasks?tab=reports')}>返回 我的报告</Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 登录弹窗：未登录下载附件时弹出，登录后留在原页自动继续下载 */}
      <LoginModal open={loginOpen} onClose={() => { setLoginOpen(false); setPendingUrl(null) }} onSuccess={onLoginSuccess} />
    </div>
  )
}
