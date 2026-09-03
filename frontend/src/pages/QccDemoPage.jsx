import { useEffect, useState } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { Card, Input, Button, Descriptions, Alert, Spin, Space, Tag, Collapse, Table, Typography, Drawer, List } from 'antd'
import { SearchOutlined, HistoryOutlined } from '@ant-design/icons'
import client from '../api/client'

const { Title, Text } = Typography

const LS_KEY = 'qcc_last_result'

// 从返回数据里递归找第一个非空数组
function findArray(obj) {
  if (!obj || typeof obj !== 'object') return null
  for (const [k, v] of Object.entries(obj)) {
    if (Array.isArray(v) && v.length > 0) return v
    if (v && typeof v === 'object') {
      const inner = findArray(v)
      if (inner) return inner
    }
  }
  return null
}

// 单元格安全渲染：对象/数组转 JSON 字符串，避免 React 崩溃
function cellText(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function ToolTable({ data, empty = '无记录' }) {
  const arr = findArray(data)
  if (!arr || arr.length === 0) return <Text type="secondary">{empty}</Text>
  const skip = new Set(['企业名称', '摘要', '关联分析', '提示', '搜索提示'])
  const keys = [...new Set(arr.flatMap((o) => Object.keys(o)))]
  const cols = keys.filter((k) => !skip.has(k))
  if (cols.length === 0) return <Text type="secondary">{JSON.stringify(arr).slice(0, 200)}</Text>
  return (
    <Table
      size="small"
      dataSource={arr}
      pagination={{ pageSize: 10, showSizeChanger: false }}
      scroll={{ x: 'max-content' }}
      rowKey={(_, i) => i}
      columns={cols.map((k) => ({
        title: k,
        dataIndex: k,
        key: k,
        ellipsis: true,
        render: (v) => <span style={{ whiteSpace: 'pre-wrap' }}>{cellText(v)}</span>,
      }))}
    />
  )
}

function ToolCard({ title, result }) {
  if (!result) return null
  if (!result.ok) return <Alert type="warning" showIcon message={`${title}：${result.error || '查询失败'}`} style={{ marginBottom: 12 }} />
  return (
    <Card size="small" title={title} style={{ marginBottom: 12 }}>
      <ToolTable data={result.data} />
    </Card>
  )
}

const BIZ_ORDER = [
  'get_shareholder_info', 'get_actual_controller', 'get_beneficial_owners', 'get_key_personnel',
  'get_branches', 'get_change_records', 'get_annual_reports', 'get_financial_data',
  'get_contact_info', 'get_external_investments', 'get_listing_info',
]

const RISK_LABELS = {
  get_high_consumption_restriction: '限制高消费',
  get_terminated_cases: '终本案件',
  get_judicial_documents: '裁判文书',
  get_case_filing_info: '立案信息',
  get_hearing_notice: '开庭公告',
  get_court_notice: '法院公告',
  get_dishonest_info: '失信信息',
  get_judgment_debtor_info: '被执行人',
  get_bankruptcy_reorganization: '破产重整',
  get_judicial_auction: '司法拍卖',
  get_equity_freeze: '股权冻结',
  get_equity_pledge_info: '股权出质',
  get_chattel_mortgage_info: '动产抵押',
  get_land_mortgage_info: '土地抵押',
  get_guarantee_info: '对外担保',
  get_administrative_penalty: '行政处罚',
  get_tax_abnormal: '税收非正常户',
  get_tax_arrears_notice: '欠税公告',
  get_business_exception: '经营异常',
  get_serious_violation: '严重违法',
  get_default_info: '违约信息',
  get_exit_restriction: '出入境限制',
  get_pre_litigation_mediation: '诉前调解',
}

export default function QccDemoPage() {
  const { mode } = useParams() // 'biz' | 'risk'
  const isBiz = mode !== 'risk'
  const [searchParams, setSearchParams] = useSearchParams()
  const [company, setCompany] = useState('')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)

  // 挂载时：优先按 URL ?company= 自动查询；否则恢复上次查询结果（localStorage）
  useEffect(() => {
    const urlCompany = searchParams.get('company')
    if (urlCompany) {
      setCompany(urlCompany)
      run(urlCompany)
    } else {
      try {
        const saved = JSON.parse(localStorage.getItem(LS_KEY))
        if (saved?.company && saved?.data) {
          setCompany(saved.company)
          setData(saved.data)
        }
      } catch (e) { /* ignore */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function run(q) {
    const name = (q !== undefined ? q : company).trim()
    if (!name) {
      setError('请输入企业名称')
      return
    }
    setLoading(true)
    setError('')
    try {
      const resp = await client.post('/qcc/query', { company: name })
      setData(resp)
      setSearchParams({ company: name }, { replace: true })
      try {
        localStorage.setItem(LS_KEY, JSON.stringify({ company: name, data: resp }))
      } catch (e) { /* ignore */ }
    } catch (e) {
      setError(e.message || '查询失败')
    } finally {
      setLoading(false)
    }
  }

  async function openHistory() {
    setHistoryOpen(true)
    setHistoryLoading(true)
    try {
      const resp = await client.get('/qcc/history')
      setHistory(resp.list || [])
    } catch (e) {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }

  const biz = data?.biz
  const risk = data?.risk
  const registration = biz?.['get_company_registration_info']
  const scan = risk?.scan
  const details = risk?.details || {}
  const factors = scan?.ok ? (scan.data['风险因子扫描'] || []) : []

  const bizFields = [
    '企业名称', '统一社会信用代码', '法定代表人', '登记状态', '成立日期', '注册资本',
    '实缴资本', '企业类型', '营业期限', '人员规模', '参保人数', '所属地区', '登记机关',
    '国标行业', '企业简称', '注册地址', '经营范围',
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
      <Title level={3} style={{ marginBottom: 4 }}>
        {isBiz ? '企业尽调报告' : '司法风险报告'} · 企查查 Demo
      </Title>
      <Text type="secondary">
        数据源：企查查 Agent API（MCP）｜工商全套 + 35维风险扫描 + 有记录维度明细｜
        <Link to={isBiz ? '/demo/risk' : '/demo/biz'}>{isBiz ? '→ 司法风险报告' : '→ 企业尽调报告'}</Link>
      </Text>

      <div style={{ display: 'flex', gap: 8, margin: '20px 0' }}>
        <Input
          size="large"
          placeholder="请输入完整企业全称，如：青岛多元房地产开发有限公司"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          onPressEnter={() => run()}
        />
        <Button size="large" type="primary" icon={<SearchOutlined />} loading={loading} onClick={() => run()}>
          查询
        </Button>
        <Button size="large" icon={<HistoryOutlined />} onClick={openHistory}>
          查询记录
        </Button>
      </div>

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

      {loading && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
          <div style={{ marginTop: 12, color: '#888' }}>正在全量查询企查查（工商 12 项 + 35维风险 + 明细）…约 10-20 秒</div>
        </div>
      )}

      {!loading && data && (
        <>
          {data.cached && (
            <Alert
              type="info"
              showIcon
              message="本次为缓存结果（24 小时内已查询过同一企业，零积分消耗、秒出）"
              style={{ marginBottom: 16 }}
            />
          )}
          <Card title={`工商登记 · ${data.company || ''}`} style={{ marginBottom: 16 }}>
            {registration?.ok && typeof registration.data === 'object' ? (
              <Descriptions bordered column={2} size="small">
                {bizFields
                  .filter((k) => registration.data[k] !== undefined && registration.data[k] !== '')
                  .map((k) => (
                    <Descriptions.Item key={k} label={k}>
                      {cellText(registration.data[k])}
                    </Descriptions.Item>
                  ))}
              </Descriptions>
            ) : (
              <Alert type="warning" showIcon message={registration?.error || '工商登记查询失败'} />
            )}
          </Card>

          {isBiz && (
            <>
              <Card size="small" title="风险概览" style={{ marginBottom: 16 }}>
                {scan?.ok ? (
                  <div>
                    <Alert
                      type={scan.data['有记录因子数'] > 0 ? 'warning' : 'success'}
                      showIcon
                      message={scan.data['摘要'] || ''}
                      style={{ marginBottom: 12 }}
                    />
                    <Space size={[4, 4]} wrap>
                      {factors.map((f) => {
                        const n = f['条目数'] || 0
                        return (
                          <Tag key={f['风险因子']} color={n > 0 ? 'red' : 'green'}>
                            {f['风险因子']} {n}
                          </Tag>
                        )
                      })}
                    </Space>
                  </div>
                ) : (
                  <Alert type="warning" showIcon message={scan?.error || '风险扫描失败'} />
                )}
              </Card>
              <Collapse
                items={BIZ_ORDER.map((tool) => ({
                  key: tool,
                  label: biz[tool]?.label || tool,
                  children: <ToolCard title="" result={biz[tool]} />,
                }))}
              />
            </>
          )}

          {!isBiz && (
            <>
              <Card title="35 维风险扫描" size="small" style={{ marginBottom: 16 }}>
                {scan?.ok ? (
                  <>
                    <Alert
                      type={scan.data['有记录因子数'] > 0 ? 'warning' : 'success'}
                      showIcon
                      message={scan.data['摘要'] || ''}
                      style={{ marginBottom: 12 }}
                    />
                    <Space size={[4, 4]} wrap>
                      {factors.map((f) => {
                        const n = f['条目数'] || 0
                        return (
                          <Tag key={f['风险因子']} color={n > 0 ? 'red' : 'green'}>
                            {f['风险因子']} {n}
                          </Tag>
                        )
                      })}
                    </Space>
                  </>
                ) : (
                  <Alert type="warning" showIcon message={scan?.error || '风险扫描失败'} />
                )}
              </Card>

              <Title level={5} style={{ margin: '16px 0 8px' }}>
                有记录维度明细（{Object.keys(details).length} 项）
              </Title>
              {Object.keys(details).length === 0 && (
                <Text type="secondary">该企业 35 个风险维度均无记录</Text>
              )}
              {Object.entries(details).map(([tool, v]) => (
                <ToolCard key={tool} title={RISK_LABELS[tool] || v.label || tool} result={v} />
              ))}
            </>
          )}
        </>
      )}

      <Drawer
        title="我的查询记录（网站共享缓存，点击直接查看）"
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        width={480}
      >
        <List
          loading={historyLoading}
          dataSource={history}
          locale={{ emptyText: '还没有查询记录，先在上方输入企业名查询一次' }}
          renderItem={(item) => (
            <List.Item
              style={{ cursor: 'pointer' }}
              onClick={() => {
                setHistoryOpen(false)
                setCompany(item.company)
                run(item.company)
              }}
            >
              <List.Item.Meta
                title={item.company}
                description={
                  <>
                    {item.created_at?.slice(0, 16).replace('T', ' ') || ''}
                    {'　'}
                    <Tag color="blue">工商 {item.biz_count}</Tag>
                    <Tag color="red">风险明细 {item.risk_records}</Tag>
                  </>
                }
              />
            </List.Item>
          )}
        />
      </Drawer>
    </div>
  )
}
