import { useState, useMemo } from 'react'
import { Card, Input, Button, Tag, Alert, Spin, Descriptions, Table, Space, Typography, Row, Col, Upload, Modal, message } from 'antd'
import { SearchOutlined, FundOutlined, FileTextOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { cluesApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Text, Title } = Typography

// 财产线索工具（从企查查全套数据中抽取与"财产"相关的维度）
const CLUE_TOOLS = [
  { key: 'get_external_investments', label: '对外投资' },
  { key: 'get_shareholder_info', label: '股东信息' },
  { key: 'get_branches', label: '分支机构' },
  { key: 'get_chattel_mortgage_info', label: '动产抵押' },
  { key: 'get_land_mortgage_info', label: '土地抵押' },
  { key: 'get_judicial_auction', label: '司法拍卖' },
]

// 风险因子（中文名 -> 关注等级）
const HIGH_RISK = ['被执行人', '失信信息', '限制高消费', '终本案件', '股权冻结', '股权出质']

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

function cellText(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function ClueTable({ data, empty }) {
  const arr = findArray(data)
  if (!arr || arr.length === 0) return <Text type="secondary" style={{ fontSize: 12 }}>{empty}</Text>
  const skip = new Set(['企业名称', '摘要', '关联分析', '提示', '搜索提示'])
  const keys = [...new Set(arr.flatMap((o) => Object.keys(o)))].filter((k) => !skip.has(k))
  if (keys.length === 0) return <Text type="secondary" style={{ fontSize: 12 }}>{JSON.stringify(arr).slice(0, 200)}</Text>
  return (
    <Table
      size="small"
      dataSource={arr.slice(0, 20)}
      pagination={arr.length > 20 ? { pageSize: 10, showSizeChanger: false } : false}
      scroll={{ x: 'max-content' }}
      rowKey={(_, i) => i}
      columns={keys.map((k) => ({
        title: k,
        dataIndex: k,
        key: k,
        ellipsis: true,
        render: (v) => <span style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{cellText(v)}</span>,
      }))}
    />
  )
}

// 追索分析（规则引擎）：把财产线索转成"可执行/可追索"的动作建议，服务律师与债权人追缴
function analyzeRecovery(data) {
  const items = []
  const biz = data.biz || {}
  const risk = data.risk || {}
  const factors = risk.scan?.ok ? (risk.scan.data['风险因子扫描'] || []) : []
  const factorCount = (name) => {
    const f = factors.find((x) => x['风险因子'] === name)
    return f?.['条目数'] || 0
  }
  const reg = biz.get_company_registration_info?.ok ? biz.get_company_registration_info.data : {}
  const status = reg['登记状态'] || ''

  const inv = findArray(biz.get_external_investments?.data) || []
  const shares = findArray(biz.get_shareholder_info?.data) || []
  const chattel = findArray(biz.get_chattel_mortgage_info?.data) || []
  const land = findArray(biz.get_land_mortgage_info?.data) || []
  const auction = findArray(biz.get_judicial_auction?.data) || []

  if (inv.length) items.push({ level: 'high', text: `对外投资 ${inv.length} 条：可申请冻结并执行其对外投资股权，这是重要执行标的` })
  if (shares.length) items.push({ level: 'high', text: `股东信息 ${shares.length} 条：股权属可执行财产，可申请查封、冻结、评估处置` })
  if (chattel.length) items.push({ level: 'medium', text: `动产抵押 ${chattel.length} 条：核实抵押物现状与受偿顺位后再决定执行路径` })
  if (land.length) items.push({ level: 'medium', text: `土地抵押 ${land.length} 条：核实土地权属现状，可通过拍卖变价受偿` })
  if (auction.length) items.push({ level: 'medium', text: `司法拍卖 ${auction.length} 条：相关资产已进入处置程序，关注进展并申请参与分配` })
  if (factorCount('被执行人')) items.push({ level: 'high', text: `被执行 ${factorCount('被执行人')} 条：可申请执行参与分配、查询履行情况，或追加/变更被执行人` })
  if (factorCount('失信信息')) items.push({ level: 'high', text: `失信 ${factorCount('失信信息')} 条：已入信用惩戒名单，可申请限制高消费、联动布控` })
  if (factorCount('限制高消费')) items.push({ level: 'medium', text: `限高 ${factorCount('限制高消费')} 条：已被限制消费，配合失信惩戒施压` })
  if (factorCount('终本案件')) items.push({ level: 'medium', text: `终本案件 ${factorCount('终本案件')} 条：前期执行未果，需通过律师调查令/财产报告令补充银行、不动产、车辆等线索` })
  if (factorCount('股权冻结')) items.push({ level: 'medium', text: `股权冻结 ${factorCount('股权冻结')} 条：他案已冻结，注意轮候查封并尽早申报债权` })
  if (factorCount('股权出质')) items.push({ level: 'medium', text: `股权出质 ${factorCount('股权出质')} 条：股权已质押，核实质权顺位与实现条件` })
  if (/吊销|注销|清算/.test(status)) items.push({ level: 'medium', text: `登记状态「${status}」：主体资格异常，追索重心转向保证人/关联方` })
  if (items.length === 0) {
    items.push({ level: 'info', text: '未发现明显可执行线索：建议申请律师调查令/法院财产报告令，查询银行账户、不动产、车辆、应收账款、到期债权等' })
  }
  return items
}

const LEVEL_COLOR = { high: 'error', medium: 'warning', info: 'info' }

// 名称形态判断：短名称且不带企业后缀 → 视为自然人（个人查询不套公司模板）
function isPersonName(name) {
  const t = (name || '').trim()
  if (t.length > 4) return false
  return !/(公司|集团|中心|银行|支行|分行|事务所|厂|合作社|工作室|有限|股份|控股|汽车)$/.test(t)
}

export default function PropertyCluesPage() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin' // 强制刷新仅管理员可用
  const [names, setNames] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState('')
  const [results, setResults] = useState([]) // [{ company, data }]
  const [error, setError] = useState('')
  const [recognized, setRecognized] = useState(null) // 判决书识别结果 { entities, method }
  const [parseLoading, setParseLoading] = useState(false)
  const [verifyModal, setVerifyModal] = useState(null) // { bad: [{name, warnings}] }
  const [pendingFiles, setPendingFiles] = useState([]) // 待识别文件 [{uid, name, file}]
  const [confirmOpen, setConfirmOpen] = useState(false) // 查询前"核对遗漏"确认框
  const [pendingNames, setPendingNames] = useState([]) // 待查询主体清单
  const [caseReport, setCaseReport] = useState(null) // 综合分析报告
  const [caseLoading, setCaseLoading] = useState(false)
  const [resolveLoading, setResolveLoading] = useState(false)
  const [resolveResult, setResolveResult] = useState(null) // {name, matched, registered_name, calls_used}
  const [refreshLoading, setRefreshLoading] = useState(null) // 正在单条强制刷新的企业名

  // 名称变体解析（查无此名时）：尝试常见变体，找到现用名即停
  const resolveName = async (name) => {
    const est = 6 * 8 // 最多 6 个变体 × 8 分
    const ok = window.confirm(`「${name}」查询结果为空，可能使用了曾用名/简称。\n将尝试最多 6 个常见名称变体（每个约 8 分，命中即停），预计最多消耗 ${est} 分。\n确认继续？`)
    if (!ok) return
    setResolveLoading(true)
    try {
      const resp = await cluesApi.resolveName(name)
      setResolveResult({ name, ...resp.data })
      if (resp.data?.matched_name) {
        message.success(`已找到现用名称：${resp.data.registered_name}（新增 ${resp.data.calls_used} 次调用）`)
      } else {
        message.warning('常见变体均未命中，请人工核对准确名称')
      }
    } catch (e) {
      message.error(e.message || '解析失败')
    } finally {
      setResolveLoading(false)
    }
  }

  const applyResolvedName = () => {
    if (resolveResult?.matched_name) {
      const lines = names.split('\n').map((s) => s.trim()).filter(Boolean)
      const idx = lines.findIndex((l) => l === resolveResult.name)
      if (idx >= 0) lines[idx] = resolveResult.matched_name
      setNames(lines.join('\n'))
      message.success('已用现用名称替换输入框中的旧名称，可重新查询（缓存命中零积分）')
    }
    setResolveResult(null)
  }

  // ---- 深度调查（付费进阶）：财产线索不满意时触发 ----
  const [deepLoading, setDeepLoading] = useState(null) // 正在深度调查的企业名
  const [deepResult, setDeepResult] = useState(null) // { company, report }
  const [deepConfirm, setDeepConfirm] = useState(null) // 确认弹窗 { company, estimate }

  const startDeepInvestigation = (company, estimate) => {
    setDeepConfirm({ company, estimate })
  }

  const runDeepInvestigation = async () => {
    const { company } = deepConfirm || {}
    if (!company) return
    setDeepConfirm(null)
    setDeepLoading(company)
    try {
      const resp = await cluesApi.deepInvestigation(company)
      setDeepResult({ company, ...resp.data })
      if (resp.data?.matched) {
        message.success(resp.message || '深度调查完成')
      } else {
        message.warning(resp.data?.reason || '深度调查未能完成')
      }
    } catch (e) {
      message.error(e.message || '深度调查失败')
    } finally {
      setDeepLoading(null)
    }
  }

  // 单条强制刷新：删除该企业全部缓存后重新实查（会重新消耗积分），仅影响该企业
  const refreshCompany = async (company) => {
    try {
      setRefreshLoading(company)
      const resp = await client.post('/qcc/refresh', { company, mode: 'clues' })
      if (resp.ok) {
        // 用新结果替换该企业在结果列表中的条目
        setResults((prev) => prev.map((r) => {
          if (r.company === company) {
            return { ...r, data: { ...resp.data, cached: false }, refreshed: true }
          }
          return r
        }))
        message.success(`已重新查询「${company}」（删除 ${resp.deleted ?? 0} 条缓存）`)
      } else {
        message.error(resp.error || `刷新「${company}」失败`)
      }
    } catch (e) {
      message.error(e.message || `刷新「${company}」失败`)
    } finally {
      setRefreshLoading(null)
    }
  }

  // 预计积分消耗（企业 × 8，缓存与自然人不计）
  const estimatedCredits = (() => {
    const list = (pendingNames.length ? pendingNames : names.split('\n').map((s) => s.trim()).filter(Boolean))
    return list.filter((n) => !isPersonName(n)).length * 8
  })()

  // 生成综合分析报告：融合全部主体（借款人+保证人+关联人）的查询结果
  const generateCaseReport = async () => {
    const list = names.split('\n').map((s) => s.trim()).filter(Boolean)
    if (list.length === 0) {
      message.warning('请先输入主体名称')
      return
    }
    // 从识别结果带角色
    const roleMap = {}
    ;(recognized?.entities || []).forEach((e) => { roleMap[e.name] = e.role })
    setCaseLoading(true)
    try {
      const resp = await cluesApi.caseReport(list.map((n) => ({ name: n, role: roleMap[n] || '相关主体' })))
      setCaseReport(resp.data)
      message.success(resp.message || '综合分析完成')
    } catch (e) {
      message.error(e.message || '分析失败')
    } finally {
      setCaseLoading(false)
    }
  }

  // 深度对比版综合分析报告：原版 + 每家企业深度调查（对比深度查询是否有增量价值）
  const [deepCaseLoading, setDeepCaseLoading] = useState(false)
  const [deepCaseReport, setDeepCaseReport] = useState(null) // { standard, deep, stats }
  const [deepCaseEstimate, setDeepCaseEstimate] = useState(0)

  const generateCaseReportDeep = async () => {
    const list = names.split('\n').map((s) => s.trim()).filter(Boolean)
    if (list.length === 0) {
      message.warning('请先输入主体名称')
      return
    }
    const companies = list.filter((n) => !isPersonName(n))
    if (companies.length === 0) {
      message.warning('主体均为自然人，深度调查仅适用于企业，请直接使用综合分析报告')
      return
    }
    const est = companies.length * 16 // 每家企业深度调查预估约 8-22 分，取中值提示
    const ok = window.confirm(
      `将生成「深度对比版」综合分析报告：\n` +
      `对 ${companies.length} 家企业逐一深度调查（原版财产追踪 + 资产维度/变现难度/变现路径/线下指引）。\n` +
      `预计消耗约 ${est} 企查查积分（已缓存企业零新增，实际可能更少）。\n` +
      `确认继续？`
    )
    if (!ok) return
    setDeepCaseLoading(true)
    setDeepCaseEstimate(est)
    try {
      const resp = await cluesApi.caseReportDeep(list.map((n) => ({ name: n, role: (recognized?.entities || []).find((e) => e.name === n)?.role || '相关主体' })))
      setDeepCaseReport(resp.data)
      setDeepCaseEstimate(resp.data?.stats?.deep_estimate_total || est)
      message.success(resp.message || '深度对比报告完成')
    } catch (e) {
      message.error(e.message || '深度对比分析失败')
    } finally {
      setDeepCaseLoading(false)
    }
  }

  // 拖/选文件：只累积展示，不自动识别（等用户点"开始识别"）；同名文件去重
  const uploadJudgment = (file) => {
    const dup = pendingFiles.some((f) => f.name === file.name)
    if (dup) {
      message.warning(`文件「${file.name}」已添加，请勿重复选择`)
      return false
    }
    setPendingFiles((prev) => [...prev, { uid: file.uid, name: file.name, file }])
    return false
  }

  const removePending = (uid) => {
    setPendingFiles((prev) => prev.filter((f) => f.uid !== uid))
  }

  const runParse = async () => {
    if (pendingFiles.length === 0) {
      message.warning('请先选择文件')
      return
    }
    setParseLoading(true)
    try {
      const resp = await cluesApi.parseJudgment(pendingFiles.map((f) => f.file))
      setRecognized(resp.data)
      // 自动填入名称（每行一个）
      setNames(resp.data.entities.map((e) => e.name).join('\n'))
      setPendingFiles([])
      message.success(resp.message || `识别完成（${resp.data.file_count || pendingFiles.length} 个文件），请核对`)
    } catch (e) {
      message.error(e.message || '识别失败')
    } finally {
      setParseLoading(false)
    }
  }

  const applyRecognized = () => {
    if (recognized) setNames(recognized.entities.map((e) => e.name).join('\n'))
  }

  // 点"开始查询"：先弹"核对遗漏"确认框，再执行校验与查询
  const onStartClick = () => {
    const list = names.split('\n').map((s) => s.trim()).filter(Boolean)
    if (list.length === 0) {
      setError('请先输入企业名称（每行一个），或上传判决书自动识别')
      return
    }
    setPendingNames(list)
    setConfirmOpen(true)
  }

  const run = async (skipVerify) => {
    const list = pendingNames
    if (list.length === 0) {
      setError('请先输入企业名称（每行一个），或上传判决书自动识别')
      return
    }
    // 未登录：可浏览页面/识别主体，但发起企查查查询需先登录（保护积分成本）
    if (!token) {
      Modal.confirm({
        title: '登录后即可查询',
        content: '财产线索查询需要消耗企查查积分，请先登录后再发起查询。（未登录可上传材料识别主体、浏览页面）',
        okText: '去登录',
        cancelText: '取消',
        onOk: () => navigate('/login'),
      })
      return
    }
    // 查询前规则校验（免费）：有可疑名称时先让用户确认，避免浪费企查查积分
    if (!skipVerify) {
      try {
        const vr = await cluesApi.verifyNames(list)
        const bad = (vr.data?.results || []).filter((r) => !r.ok)
        if (bad.length > 0) {
          setVerifyModal({ bad, names: list })
          return
        }
      } catch { /* 校验服务异常时直接放行 */ }
    }
    setVerifyModal(null)
    setLoading(true)
    setError('')
    setResults([])
    // 自然人跳过企查查（个人无企业数据，避免浪费积分）：直接进结果列表走自然人模板
    const persons = list.filter(isPersonName)
    const companies = list.filter((n) => !isPersonName(n))
    const out = persons.map((n) => ({ company: n, isPerson: true, data: null }))
    setResults([...out])
    if (persons.length > 0) {
      setProgress(`自然人（${persons.join('、')}）跳过企查查（零积分），仅查询企业…`)
    }
    const CONCURRENCY = 2 // 2 家并行，提速且避免触发企查查限流
    for (let i = 0; i < companies.length; i += CONCURRENCY) {
      const batch = companies.slice(i, i + CONCURRENCY)
      const batchLabel = batch.length > 1 ? `${batch[0]} 等 ${batch.length} 家` : batch[0]
      setProgress(`正在查询 ${Math.min(i + CONCURRENCY, companies.length)}/${companies.length}：${batchLabel}…`)
      const batchResults = await Promise.all(
        batch.map(async (name) => {
          try {
            // mode=clues：轻量查询（约8次调用/企业，比全量省70%积分）
            const resp = await client.post('/qcc/query', { company: name, mode: 'clues' })
            return { company: name, data: resp }
          } catch (e) {
            return { company: name, data: null, error: e.message || '查询失败' }
          }
        })
      )
      out.push(...batchResults)
      setResults([...out])
    }
    setProgress('')
    setLoading(false)
  }

  // 汇总统计
  const stats = (() => {
    let withRisk = 0
    let investCount = 0
    let execCount = 0
    let executable = 0 // 有可执行财产线索（对外投资/股权/抵押）的主体数
    for (const r of results) {
      const data = r.data
      if (!data) continue
      const risk = data.risk
      const factors = risk?.scan?.ok ? (risk.scan.data['风险因子扫描'] || []) : []
      const hasRisk = factors.some((f) => (f['条目数'] || 0) > 0)
      if (hasRisk) withRisk++
      const invBiz = data.biz?.get_external_investments
      if (invBiz?.ok) investCount += (findArray(invBiz.data) || []).length
      for (const f of factors) {
        if (f['风险因子'] === '被执行人') execCount += f['条目数'] || 0
      }
      const biz = data.biz || {}
      const hasClue = ['get_external_investments', 'get_shareholder_info', 'get_chattel_mortgage_info', 'get_land_mortgage_info', 'get_judicial_auction']
        .some((t) => biz[t]?.ok && (findArray(biz[t].data) || []).length > 0)
      if (hasClue) executable++
    }
    return { total: results.length, withRisk, investCount, execCount, executable }
  })()

  // 交叉验证：自然人与企业的身份关联（法定代表人/股东）——把"重名风险"升级为"身份确认"
  const crossRefs = useMemo(() => {
    const map = {}
    results.forEach((r) => {
      if (!r.data || isPersonName(r.company)) return
      const reg = r.data.biz?.get_company_registration_info
      const regData = reg?.ok && typeof reg.data === 'object' ? reg.data : {}
      const legal = regData['法定代表人']
      if (legal) {
        ;(map[legal] = map[legal] || []).push({ company: r.company, role: '法定代表人' })
      }
      const shrArr = findArray(r.data.biz?.get_shareholder_info?.data) || []
      shrArr.forEach((s) => {
        const n = (s['股东名称'] || s['股东'] || '').trim()
        if (n) {
          ;(map[n] = map[n] || []).push({ company: r.company, role: '股东' })
        }
      })
    })
    return map
  }, [results])

  const renderEntity = (r) => {
    // 自然人：跳过企查查，直接渲染自然人模板（无企业数据）
    if (r.isPerson) {
      const cref = crossRefs[r.company] || []
      return (
        <Card style={{ marginBottom: 16 }} title={<Space><span style={{ fontWeight: 700 }}>{r.company}</span><Tag color="purple">自然人</Tag></Space>}>
          <div style={{ marginBottom: 12 }}>
            <Alert
              type="info"
              showIcon
              message={`自然人「${r.company}」：未消耗企查查积分（个人无企业数据）。个人资产需通过律师调查令、法院财产报告令等方式线下查询。`}
            />
          </div>
          {cref.length > 0 && (
            <div style={{ marginBottom: 12, padding: 10, background: '#EFFAF5', borderRadius: 6, border: '1px solid #B7EBD6' }}>
              <Text strong style={{ fontSize: 13, color: 'var(--success)' }}>✅ 身份关联（交叉验证）：</Text>
              <div style={{ marginTop: 6 }}>
                {cref.map((c, i) => (
                  <Tag key={i} color="green" style={{ fontSize: 12 }}>{r.company} ↔ {c.company}（{c.role}）</Tag>
                ))}
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>若材料中的自然人与上述企业存在该职务关联，可据此确认身份、显著降低重名风险。</Text>
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            <Text strong style={{ fontSize: 13 }}>追索分析：</Text>
            <div style={{ marginTop: 8 }}>
              <Alert
                type="info"
                showIcon
                message={`自然人「${r.company}」的个人财产（银行账户/不动产/车辆/证券等）无法通过公开企业数据查询。追索路径：① 申请法院调查令/财产报告令查询其名下资产；② 若其为某企业法定代表人或股东，可通过冻结/执行其股权或分红权施压${cref.length ? '（见上方身份关联）' : ''}。`}
              />
            </div>
          </div>
        </Card>
      )
    }
    if (r.error || !r.data) {
      return (
        <Card title={r.company} style={{ marginBottom: 16 }}>
          <Alert type="error" showIcon message={r.error || '查询失败（请确认网络/企查查凭证）'} />
        </Card>
      )
    }
    const data = r.data
    const reg = data.biz?.get_company_registration_info
    const regData = reg?.ok && typeof reg.data === 'object' ? reg.data : {}
    const factors = data.risk?.scan?.ok ? (data.risk.scan.data['风险因子扫描'] || []) : []
    const riskFactors = factors.filter((f) => (f['条目数'] || 0) > 0)
    const cluePresent = CLUE_TOOLS.some((t) => data.biz?.[t.key]?.ok && findArray(data.biz[t.key].data))
    const isPerson = isPersonName(r.company)

    return (
      <Card
        style={{ marginBottom: 16 }}
        title={
          <Space>
            <span style={{ fontWeight: 700 }}>{r.company}</span>
            {isPerson && <Tag color="purple">自然人</Tag>}
            {data.cached && <Tag color="blue">缓存</Tag>}
            {!isPerson && regData['登记状态'] && (
              <Tag color={regData['登记状态'] === '存续' || regData['登记状态'] === '在业' || regData['登记状态'] === '在营（开业）企业' ? 'green' : 'red'}>
                {regData['登记状态']}
              </Tag>
            )}
          </Space>
        }
        extra={
          !isPerson && regData['企业名称'] && (
            <Space size={4}>
              <Button
                size="small"
                type="primary"
                ghost
                icon={<FundOutlined />}
                loading={deepLoading === r.company}
                onClick={() => startDeepInvestigation(r.company, 16)}
              >
                深度调查
              </Button>
              {isAdmin && (
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={refreshLoading === r.company}
                  onClick={() => refreshCompany(r.company)}
                  title="强制刷新：删除该企业缓存后重新实查（会重新消耗积分，仅管理员可用）"
                >
                  强制刷新
                </Button>
              )}
            </Space>
          )
        }
      >
        {/* 自然人：不套用公司工商模板，无数据留空 */}
        {!isPerson && (
          (regData['法定代表人'] || regData['注册资本'] || regData['成立日期']) && (
            <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
              {regData['法定代表人'] && <Descriptions.Item label="法定代表人">{regData['法定代表人']}</Descriptions.Item>}
              {regData['注册资本'] && <Descriptions.Item label="注册资本">{regData['注册资本']}</Descriptions.Item>}
              {regData['成立日期'] && <Descriptions.Item label="成立日期">{regData['成立日期']}</Descriptions.Item>}
            </Descriptions>
          )
        )}
        {isPerson && (
          <div style={{ marginBottom: 12 }}>
            <Alert type="info" showIcon message={`「${r.company}」为自然人：系统不展示公司工商/财产信息（企查查查询结果多为同名企业，不代表个人名下资产）。个人资产需通过律师调查令、法院财产报告令等方式线下查询。`} />
          </div>
        )}
        {/* 自然人身份关联（交叉验证）：同名自然人与查询企业的法定代表人/股东匹配 → 身份确认 */}
        {isPerson && crossRefs[r.company] && crossRefs[r.company].length > 0 && (
          <div style={{ marginBottom: 12, padding: 10, background: '#EFFAF5', borderRadius: 6, border: '1px solid #B7EBD6' }}>
            <Text strong style={{ fontSize: 13, color: 'var(--success)' }}>✅ 身份关联（交叉验证）：</Text>
            <div style={{ marginTop: 6 }}>
              {crossRefs[r.company].map((c, i) => (
                <Tag key={i} color="green" style={{ fontSize: 12 }}>
                  {r.company} ↔ {c.company}（{c.role}）
                </Tag>
              ))}
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              若材料中的自然人与上述企业存在该职务关联，可据此确认身份、显著降低重名风险。
            </Text>
          </div>
        )}

        {/* 企业更名提示（2026-08-31：已按现名自动重查） */}
        {!isPerson && data.renamed && data.renamed.new_name && (
          <Alert
            type="info"
            showIcon
            message={`企业已更名：由「${data.renamed.old_name}」更名为「${data.renamed.new_name}」，已按现名查询财产线索`}
            style={{ marginBottom: 12 }}
          />
        )}

        {/* 名称与工商不符提示（曾用名/简称） */}
        {!isPerson && data.name_ok === false && (
          <Alert
            type="warning"
            showIcon
            message={data.name_warning || '该名称可能已变更或与工商登记不符（如曾用名/简称），查询结果可能无效'}
            action={
              <Button size="small" loading={resolveLoading} onClick={() => resolveName(r.company)}>
                尝试名称变体解析
              </Button>
            }
            style={{ marginBottom: 12 }}
          />
        )}

        {/* 风险因子（仅企业展示；自然人查询结果多为同名企业数据，不展示以免误导） */}
        {!isPerson && (
          <div style={{ marginBottom: 12 }}>
            <Text strong style={{ fontSize: 13 }}>司法/风险线索：</Text>
            {riskFactors.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>无记录</Text>
            ) : (
              <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
                {riskFactors.map((f) => {
                  const n = f['条目数'] || 0
                  const high = HIGH_RISK.includes(f['风险因子'])
                  return (
                    <Tag key={f['风险因子']} color={n > 0 ? (high ? 'red' : 'orange') : 'green'}>
                      {f['风险因子']} {n}
                    </Tag>
                  )
                })}
              </Space>
            )}
          </div>
        )}

        {/* 财产线索明细（仅企业展示） */}
        {!isPerson && (
          <>
            <Text strong style={{ fontSize: 13 }}>财产线索明细：</Text>
            {!cluePresent ? (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>未查询到对外投资/抵押等财产线索（可能无记录或查询受限）</Text>
              </div>
            ) : (
              CLUE_TOOLS.map((t) => {
                const r2 = data.biz?.[t.key]
                if (!r2?.ok) return null
                const arr = findArray(r2.data)
                if (!arr || arr.length === 0) return null
                return (
                  <div key={t.key} style={{ marginTop: 10 }}>
                    <Text strong style={{ fontSize: 12, color: 'var(--primary)' }}>
                      {t.label}（{arr.length} 条）
                    </Text>
                    <div style={{ marginTop: 4 }}>
                      <ClueTable data={r2.data} empty="" />
                    </div>
                  </div>
                )
              })
            )}
          </>
        )}
        {/* 追索分析 */}
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border-light)' }}>
          <Text strong style={{ fontSize: 13 }}>追索分析：</Text>
          <div style={{ marginTop: 8 }}>
            {isPerson ? (
              <Alert
                type="info"
                showIcon
                message={`自然人「${r.company}」的个人财产（银行账户/不动产/车辆/证券等）无法通过公开企业数据查询。追索路径：① 申请法院调查令/财产报告令查询其名下资产；② 若其为某企业法定代表人或股东，可通过冻结/执行其股权或分红权施压（见上方身份关联）。`}
              />
            ) : (
              analyzeRecovery(data).map((a, i) => (
                <Alert key={i} type={LEVEL_COLOR[a.level]} showIcon message={a.text} style={{ marginBottom: 6 }} />
              ))
            )}
          </div>
        </div>
      </Card>
    )
  }

  return (
    <div className="page-container">
      <div className="section-card" style={{ marginBottom: 20 }}>
        <div className="section-title">
          <FundOutlined /> 财产线索查询
        </div>
        <Text type="secondary">
          输入债务人、保证人、关联企业名称（每行一个），系统逐个查询企查查：对外投资 / 股东 / 分支机构 / 动产抵押 / 土地抵押 / 司法拍卖 + 被执行 / 失信 / 限高 / 终本 / 股权冻结等风险线索。同一企业 24 小时内重复查询走缓存（零积分）。
        </Text>
        <Alert
          style={{ marginTop: 10 }}
          type="info"
          showIcon
          message="合规声明：数据来自公开渠道（司法公开 / 信用公示 / 企查查），仅供合法债权追偿、诉讼等正当用途，禁止用于骚扰、人肉、恐吓等非法目的；自然人身份锚点仅用于区分重名，请勿滥用。"
        />
        <Input.TextArea
          rows={6}
          style={{ marginTop: 12, fontSize: 13 }}
          placeholder={'每行一个企业全称，例如：\n济南森智汽车销售服务有限公司\n山东林润汽车销售服务有限公司\n临沂市杭标摩擦材料有限公司'}
          value={names}
          onChange={(e) => setNames(e.target.value)}
        />
        <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
          <Button size="large" icon={<FileTextOutlined />} loading={caseLoading} onClick={generateCaseReport}>
            综合分析报告{estimatedCredits > 0 ? `（预计~${estimatedCredits}分）` : ''}
          </Button>
          <Button size="large" icon={<FundOutlined />} loading={deepCaseLoading} onClick={generateCaseReportDeep}>
            深度对比版{deepCaseEstimate > 0 ? `（预计~${deepCaseEstimate}分）` : ''}
          </Button>
          <Button type="primary" size="large" icon={<SearchOutlined />} loading={loading} onClick={onStartClick}>
            开始查询（{names.split('\n').filter((s) => s.trim()).length} 家）
          </Button>
        </div>
        <Upload.Dragger
            accept=".doc,.docx,.pdf,.txt,.md,.jpg,.jpeg,.png,.webp,.bmp"
            multiple
            showUploadList={false}
            beforeUpload={uploadJudgment}
            style={{ marginTop: 12, background: '#fff' }}
          >
            <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
              <FileTextOutlined style={{ fontSize: 28, color: 'var(--primary)' }} />
            </p>
            <p className="ant-upload-text" style={{ fontSize: 13 }}>
              点击或拖拽材料文件到这里（判决书 / 裁定书 / 情况说明 / 尽调说明等，支持 Word / PDF / TXT / 图片）
            </p>
            <p className="ant-upload-hint" style={{ fontSize: 12 }}>
              支持多文件、多页材料（如判决书多页扫描件、逐页拍照）；可先多次选择/拖入文件，确认后点击「开始识别」，自动识别债务人、保证人、关联人；图片请尽量清晰端正
            </p>
          </Upload.Dragger>
          {/* 待识别文件列表（只累积，不自动识别） */}
          {pendingFiles.length > 0 && (
            <div style={{ marginTop: 10, padding: 10, background: '#fff', border: '1px solid var(--border)', borderRadius: 6 }}>
              <Space size={[4, 4]} wrap>
                {pendingFiles.map((f) => (
                  <Tag
                    key={f.uid}
                    closable
                    onClose={() => removePending(f.uid)}
                    style={{ fontSize: 12 }}
                  >
                    {f.name}
                  </Tag>
                ))}
              </Space>
              <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                <Button type="primary" size="small" icon={<SearchOutlined />} loading={parseLoading} onClick={runParse}>
                  开始识别（{pendingFiles.length} 个文件）
                </Button>
                <Button size="small" onClick={() => setPendingFiles([])}>清空</Button>
                {parseLoading && <Text type="secondary" style={{ fontSize: 12 }}>正在识别（多页材料约需十几秒~数十秒）…</Text>}
              </div>
            </div>
          )}

        {/* 材料识别结果 */}
        {recognized && (
          <div style={{ marginTop: 14, padding: 14, background: '#F7F9FC', borderRadius: 8, border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <FileTextOutlined style={{ color: 'var(--primary)' }} />
              <Text strong>材料识别结果（{recognized.method === 'llm' ? '系统识别' : '规则识别'} · {recognized.entities.length} 个主体）</Text>
              <Button size="small" style={{ marginLeft: 'auto' }} onClick={applyRecognized}>重新填入输入框</Button>
            </div>
            <Space size={[6, 6]} wrap>
              {recognized.entities.map((e, i) => {
                const idt = e.identity || {}
                const idParts = [
                  idt.gender && (idt.gender === '男' ? '♂男' : '♀女'),
                  idt.birth && `出生${idt.birth}`,
                  idt.address && `住${idt.address}`,
                  idt.id_tail && `证件尾号${idt.id_tail}`,
                  idt.binding && `与${idt.binding}绑定`,
                ].filter(Boolean)
                const noIdentity = e.type === 'person' && idParts.length === 0
                return (
                  <Tag
                    key={i}
                    color={e.ok === false ? 'red' : e.type === 'person' ? 'purple' : e.confidence === 'high' ? 'blue' : 'orange'}
                    style={{ fontSize: 12 }}
                    title={(e.warnings || []).join('；') || [idt.context, ...idParts].filter(Boolean).join(' | ') || e.confidence}
                  >
                    {e.name}（{e.role}）
                    {e.type === 'person' && idParts.length > 0 && <span style={{ opacity: 0.75 }}> {idParts.slice(0, 2).join('·')}</span>}
                    {e.ok === false && ' ⚠️'}
                    {noIdentity && ' ⚠️重名风险'}
                  </Tag>
                )
              })}
            </Space>
            {recognized.entities.some((e) => e.type === 'person' && !Object.values(e.identity || {}).some((v) => v && v !== '')) && (
              <Alert
                style={{ marginTop: 8 }}
                type="warning"
                showIcon
                message="存在未获取身份标识的自然人：姓名可能重名，查询结果可能涉及多个同名者。建议补充出生日期/证件尾号/关联企业等信息确认身份，避免查错人。"
              />
            )}
            {recognized.entities.some((e) => e.ok === false) && (
              <Alert
                style={{ marginTop: 8 }}
                type="warning"
                showIcon
                message={`${recognized.entities.filter((e) => e.ok === false).length} 个名称疑似有误（红标），查询前请核对，避免浪费企查查积分`}
              />
            )}
            {recognized.note && <Text type="secondary" style={{ fontSize: 12 }}>{recognized.note}</Text>}
            <Alert
              style={{ marginTop: 8 }}
              type="info"
              showIcon
              message="识别完整性提醒：若材料照片未拍全整页（尤其左右边缘），开头/结尾的主体可能不在识别结果中。如发现缺少主体，请补拍完整页面重新识别，或直接在输入框手动补充。"
            />
          </div>
        )}

        {error && <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} />}
        {loading && (
          <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
            <Spin size="small" />
            <Text>{progress}</Text>
          </div>
        )}

        {/* 查询前"核对遗漏"确认弹窗 */}
        <Modal
          title="查询前核对"
          open={confirmOpen}
          onCancel={() => setConfirmOpen(false)}
          onOk={() => {
            setConfirmOpen(false)
            run(false)
          }}
          okText="就这些了，开始查询"
          cancelText="返回修改"
          width={600}
        >
          <Alert
            type="warning"
            showIcon
            message="请仔细核对：债务人和担保人/关联人是否都已列出？材料（尤其照片/扫描件）可能漏识别主体，若有遗漏请返回修改后重新查询。"
            style={{ marginBottom: 12 }}
          />
          <Alert
            type="info"
            showIcon
            message={`预计消耗约 ${estimatedCredits} 积分（${pendingNames.filter((n) => !isPersonName(n)).length} 家企业 × 8 分；缓存命中与自然人不计）。`}
            style={{ marginBottom: 12 }}
          />
          <Text strong>即将查询（{pendingNames.length} 家）：</Text>
          <div style={{ marginTop: 8, maxHeight: 220, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 12px' }}>
            {pendingNames.map((n, i) => (
              <div key={i} style={{ padding: '5px 0', borderBottom: i < pendingNames.length - 1 ? '1px solid var(--border-light)' : 'none', fontSize: 13 }}>
                {i + 1}. {n}
              </div>
            ))}
          </div>
        </Modal>

        {/* 综合分析报告弹窗 */}
        <Modal
          title="案件综合分析报告（追索策略）"
          open={caseReport != null}
          onCancel={() => setCaseReport(null)}
          footer={<Button type="primary" onClick={() => setCaseReport(null)}>关闭</Button>}
          width={760}
        >
          {caseReport && (
            <>
              <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value">{caseReport.subject_count}<span className="kpi-unit">个</span></div><div className="kpi-label">案件主体</div></div></Col>
                <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value" style={{ color: 'var(--danger)' }}>{caseReport.n_high_risk}<span className="kpi-unit">家</span></div><div className="kpi-label">涉被执行/失信</div></div></Col>
                <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value" style={{ color: 'var(--success)' }}>{caseReport.n_priority}<span className="kpi-unit">家</span></div><div className="kpi-label">可优先追索</div></div></Col>
                <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value" style={{ color: 'var(--primary)' }}>{caseReport.n_with_clues}<span className="kpi-unit">家</span></div><div className="kpi-label">有财产线索</div></div></Col>
              </Row>

              <div style={{ marginBottom: 8 }}><Text strong>追索优先级排序（分数越高越值得优先追索）：</Text></div>
              {(caseReport.ordered || []).map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', marginBottom: 6, background: i % 2 ? '#FAFBFC' : '#fff', borderRadius: 6, border: '1px solid var(--border)' }}>
                  <span style={{ width: 22, height: 22, borderRadius: '50%', background: s.score >= 2 ? 'var(--success)' : s.score >= 0 ? 'var(--warning)' : 'var(--danger)', color: '#fff', fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    {i + 1}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{s.name} <Tag style={{ fontSize: 11 }}>{s.role}</Tag></div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                      {s.status || '—'} ｜ 被执行 {s.risk['被执行人']} / 失信 {s.risk['失信信息']} / 限高 {s.risk['限制高消费']} / 终本 {s.risk['终本案件']} ｜ 财产线索 {s.clue_count} 条
                    </div>
                  </div>
                  <Tag color={s.score >= 2 ? 'green' : s.score >= 0 ? 'orange' : 'red'} style={{ flexShrink: 0 }}>{s.priority}（{s.score}）</Tag>
                </div>
              ))}
              {caseReport.not_queried && caseReport.not_queried.length > 0 && (
                <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                  未走企查查查询的主体（多为自然人）：{caseReport.not_queried.map((s) => `${s.name}（${s.role}）`).join('、')}——个人资产需线下调查，可结合其企业任职线索追索。
                </div>
              )}

              <div style={{ marginTop: 14 }}><Text strong>综合建议：</Text></div>
              {(caseReport.advice || []).map((a, i) => (
                <Alert key={i} type="info" showIcon message={a} style={{ marginBottom: 6 }} />
              ))}

              {/* 案例场景风险提醒（知识库匹配） */}
              {caseReport.reminders?.length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <Text strong style={{ color: '#d48806' }}>⚠️ 案例场景风险提醒（知识库匹配）：</Text>
                  <div style={{ marginTop: 8 }}>
                    {caseReport.reminders.map((r, i) => (
                      <div key={i} style={{ marginBottom: 8, border: '1px solid #ffe58f', background: '#fffbe6', borderRadius: 6, padding: 8 }}>
                        <Space wrap style={{ marginBottom: 4 }}>
                          <Tag color="orange">{r.scenario}</Tag>
                          <Text strong style={{ fontSize: 12 }}>{r.title}</Text>
                        </Space>
                        <div style={{ fontSize: 12 }}>{r.summary}</div>
                        {r.approach && (
                          <div style={{ fontSize: 12, marginTop: 4 }}>
                            <Text strong>处理思路：</Text>{r.approach}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <Text type="secondary" style={{ fontSize: 12 }}>
                报告说明：本次新增企查查调用 {caseReport.stats?.new_calls ?? 0} 次，缓存命中 {caseReport.stats?.cached_hits ?? 0} 次，自然人跳过 {caseReport.stats?.skipped_persons ?? 0} 人。数据来自公开渠道，仅供合法债权追偿使用。
              </Text>
            </>
          )}
        </Modal>

        {/* 深度对比版综合分析报告弹窗：原版 + 深度调查 */}
        <Modal
          title="深度对比版综合分析报告（原版财产追踪 + 深度调查）"
          open={deepCaseReport != null}
          onCancel={() => setDeepCaseReport(null)}
          footer={<Button onClick={() => setDeepCaseReport(null)}>关闭</Button>}
          width={900}
        >
          {deepCaseReport && (
            <>
              <Alert type="success" showIcon message={deepCaseReport.deep?.summary} style={{ marginBottom: 12 }} />

              {/* 深度调查增量对比 */}
              <div style={{ marginBottom: 12 }}>
                <Text strong>深度调查新增线索（原版之外的维度）：</Text>
                {(deepCaseReport.deep?.diff || []).length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>无新增维度</Text>
                ) : (
                  (deepCaseReport.deep?.diff || []).map((d, i) => (
                    <div key={i} style={{ padding: '8px 10px', marginBottom: 6, border: '1px solid var(--border)', borderRadius: 6, background: '#FFFBE6' }}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>
                        {d.name} <Tag color="orange">新增 {d.added.length} 个维度</Tag>
                        {d.best_difficulty && <Tag color="blue">最易变现：{d.best_difficulty}</Tag>}
                      </div>
                      <div style={{ fontSize: 12, marginTop: 4 }}>{d.added.join('、')}</div>
                      <Text type="secondary" style={{ fontSize: 12 }}>{d.summary}</Text>
                    </div>
                  ))
                )}
              </div>

              {/* 原版财产追踪（与综合分析报告一致） */}
              <div style={{ borderTop: '1px solid var(--border-light)', paddingTop: 12 }}>
                <Text strong>一、财产追踪（原版）：</Text>
                {(deepCaseReport.standard?.ordered || []).map((s, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', marginBottom: 6, background: i % 2 ? '#FAFBFC' : '#fff', borderRadius: 6, border: '1px solid var(--border)' }}>
                    <span style={{ width: 22, height: 22, borderRadius: '50%', background: s.score >= 2 ? 'var(--success)' : s.score >= 0 ? 'var(--warning)' : 'var(--danger)', color: '#fff', fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      {i + 1}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{s.name} <Tag style={{ fontSize: 11 }}>{s.role}</Tag></div>
                      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        {s.status || '—'} ｜ 被执行 {s.risk['被执行人']} / 失信 {s.risk['失信信息']} / 限高 {s.risk['限制高消费']} / 终本 {s.risk['终本案件']} ｜ 财产线索 {s.clue_count} 条
                      </div>
                    </div>
                    <Tag color={s.score >= 2 ? 'green' : s.score >= 0 ? 'orange' : 'red'} style={{ flexShrink: 0 }}>{s.priority}（{s.score}）</Tag>
                  </div>
                ))}
              </div>

              {/* 深度调查明细：每家企业 */}
              <div style={{ borderTop: '1px solid var(--border-light)', paddingTop: 12 }}>
                <Text strong>二、深度调查明细（每家企业）：</Text>
                {Object.entries(deepCaseReport.deep?.reports || {}).map(([name, dr]) => (
                  <Card key={name} size="small" style={{ marginBottom: 10 }} title={name}
                    extra={dr.matched ? <Tag color="green">深度调查完成{dr.cached ? '（缓存）' : ''}</Tag> : <Tag color="red">未完成</Tag>}>
                    {!dr.matched ? (
                      <Text type="secondary" style={{ fontSize: 12 }}>{dr.reason}</Text>
                    ) : (
                      <>
                        <Alert type="info" showIcon message={dr.report?.summary} style={{ marginBottom: 8 }} />
                        {(dr.report?.dimensions || []).map((d, i) => (
                          <div key={i} style={{ marginBottom: 8, border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}>
                            <Space wrap style={{ marginBottom: 4 }}>
                              <Text strong style={{ fontSize: 12 }}>{d.name}</Text>
                              <Tag color={d.difficulty === '低' ? 'green' : d.difficulty === '中' ? 'blue' : d.difficulty === '中高' ? 'orange' : 'red'}>变现难度：{d.difficulty}</Tag>
                            </Space>
                            <div style={{ fontSize: 12 }}>{d.summary}</div>
                            <Text type="secondary" style={{ fontSize: 12 }}>变现路径：{d.path}</Text>
                          </div>
                        ))}
                      </>
                    )}
                  </Card>
                ))}
              </div>

              <Text type="secondary" style={{ fontSize: 12 }}>
                积分说明：原版新增 {deepCaseReport.stats?.standard?.new_calls ?? 0} 次调用；深度调查缓存命中 {deepCaseReport.stats?.deep_cached ?? 0} 家、新查 {deepCaseReport.stats?.deep_calls ?? 0} 家（预估约 {deepCaseReport.stats?.deep_estimate_total ?? 0} 积分）。数据来自公开渠道，仅供合法债权追偿使用。
              </Text>
            </>
          )}
        </Modal>

        {/* 名称变体解析结果弹窗 */}
        <Modal
          title="名称变体解析结果"
          open={resolveResult != null}
          onCancel={() => setResolveResult(null)}
          footer={
            resolveResult?.matched_name ? (
              <Space>
                <Button onClick={() => setResolveResult(null)}>关闭</Button>
                <Button type="primary" onClick={applyResolvedName}>用现用名称替换并重新查询</Button>
              </Space>
            ) : (
              <Button onClick={() => setResolveResult(null)}>关闭</Button>
            )
          }
          width={560}
        >
          {resolveResult?.matched_name ? (
            <>
              <Alert type="success" showIcon message={`已找到现用名称：${resolveResult.registered_name}`} style={{ marginBottom: 12 }} />
              <Text>解析过程（尝试 {resolveResult.tried?.length} 个变体，新增 {resolveResult.calls_used} 次调用）：</Text>
              <div style={{ marginTop: 8, maxHeight: 200, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 12px' }}>
                {resolveResult.tried?.map((t, i) => (
                  <div key={i} style={{ padding: '4px 0', fontSize: 13 }}>
                    {i + 1}. {t.name} {t.name === resolveResult.matched_name ? '✅ 命中' : t.used_cache ? '（缓存）' : t.negative ? '（近期查无，已跳过）' : '（未命中）'}
                  </div>
                ))}
              </div>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                该名称已在缓存中，用现用名称查询零积分。
              </Text>
            </>
          ) : (
            <Alert type="warning" showIcon message="尝试全部常见变体均未命中，请人工核对准确名称（可参考天眼查/企查查网页搜索）。" />
          )}
        </Modal>

        {/* 深度调查确认弹窗（付费进阶，提示积分消耗） */}
        <Modal
          title="深度调查（付费进阶）"
          open={deepConfirm != null}
          onCancel={() => setDeepConfirm(null)}
          onOk={runDeepInvestigation}
          okText="确认深度调查"
          cancelText="取消"
          confirmLoading={deepLoading != null}
        >
          <Alert
            type="warning"
            showIcon
            message={`将对「${deepConfirm?.company}」进行深度调查，预计消耗约 ${deepConfirm?.estimate ?? 16} 企查查积分（有缓存时更少，约 8-22 分）。`}
            description="深度调查在财产线索基础上追加：对外应收债权/未来收入（作为原告的涉诉）、询价评估、财产悬赏、股权冻结/出质、担保、终本、年报/财务/发票等维度，并给出每类资产的变现难度与变现路径、线下查询指引。"
            style={{ marginBottom: 12 }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            同企业 24 小时内重复深度调查零新增积分（结果缓存）。若名称与工商不符（曾用名/简称），请先"尝试名称变体解析"核对后再调查，避免浪费积分。
          </Text>
        </Modal>

        {/* 深度调查报告弹窗 */}
        <Modal
          title={deepResult?.company ? `深度调查报告 — ${deepResult.company}` : '深度调查报告'}
          open={deepResult != null}
          onCancel={() => setDeepResult(null)}
          footer={<Button onClick={() => setDeepResult(null)}>关闭</Button>}
          width={760}
        >
          {deepResult && !deepResult.matched && (
            <Alert type="warning" showIcon message={deepResult.reason || '深度调查未能完成'} style={{ marginBottom: 12 }} />
          )}
          {deepResult?.report && (
            <>
              <Alert
                type={deepResult.report.dimensions?.length ? 'success' : 'info'}
                showIcon
                message={deepResult.report.summary}
                style={{ marginBottom: 12 }}
              />
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                本次调用：{deepResult.cached ? '缓存命中，0 积分' : `约 ${deepResult.estimate ?? deepResult.report.calls_used ?? 16} 积分`}。
                {deepResult.report.scan_summary ? `风险扫描：${deepResult.report.scan_summary}` : ''}
              </Text>

              {deepResult.report.dimensions?.map((d, i) => (
                <Card key={i} size="small" style={{ marginBottom: 12 }} title={d.name}
                  extra={<Tag color={d.difficulty === '低' ? 'green' : d.difficulty === '中' ? 'blue' : d.difficulty === '中高' ? 'orange' : 'red'}>变现难度：{d.difficulty}</Tag>}>
                  <Alert type="info" showIcon message={d.summary} style={{ marginBottom: 8 }} />
                  <div style={{ marginBottom: 8 }}>
                    <Text strong style={{ fontSize: 12 }}>变现路径：</Text>
                    <Text style={{ fontSize: 12 }}>{d.path}</Text>
                  </div>
                  {d.items?.length > 0 && (
                    <ClueTable data={{ data: d.items }} empty="" />
                  )}
                </Card>
              ))}

              {/* 案例场景风险提醒（知识库匹配） */}
              {deepResult.report.reminders?.length > 0 && (
                <Card size="small" title="⚠️ 案例场景风险提醒（知识库匹配）" style={{ marginBottom: 12, borderColor: '#faad14' }}>
                  {deepResult.report.reminders.map((r, i) => (
                    <div key={i} style={{ marginBottom: 10, borderBottom: i < deepResult.report.reminders.length - 1 ? '1px dashed var(--border-light)' : 'none', paddingBottom: 10 }}>
                      <Space wrap style={{ marginBottom: 4 }}>
                        <Tag color="orange">{r.scenario}</Tag>
                        <Text strong style={{ fontSize: 12 }}>{r.title}</Text>
                      </Space>
                      <div style={{ fontSize: 12 }}>{r.summary}</div>
                      {r.approach && (
                        <div style={{ fontSize: 12, marginTop: 4 }}>
                          <Text strong>处理思路：</Text>{r.approach}
                        </div>
                      )}
                    </div>
                  ))}
                </Card>
              )}

              {/* 线下查询指引 */}
              <Card size="small" title="线下查询指引（公开数据查不到的资产类型）" style={{ marginBottom: 12 }}>
                {deepResult.report.offline_guides?.map((g, i) => (
                  <div key={i} style={{ marginBottom: 8, borderBottom: i < deepResult.report.offline_guides.length - 1 ? '1px dashed var(--border-light)' : 'none', paddingBottom: 8 }}>
                    <Text strong style={{ fontSize: 12 }}>{g['类型']}</Text>
                    <div style={{ fontSize: 12 }}>渠道：{g['渠道']}</div>
                    <Text type="secondary" style={{ fontSize: 12 }}>{g['说明']}</Text>
                  </div>
                ))}
              </Card>
            </>
          )}
        </Modal>

        {/* 名称校验确认弹窗 */}
        <Modal
          title="名称校验提示"
          open={verifyModal != null}
          onCancel={() => setVerifyModal(null)}
          onOk={() => run(true)}
          okText="仍然查询（自负风险）"
          cancelText="返回修改"
        >
          <Alert type="warning" showIcon message="以下名称可能存在误差，直接查询可能浪费企查查积分：" style={{ marginBottom: 12 }} />
          {(verifyModal?.bad || []).map((b, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <Tag color="red">{b.name}</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>{b.warnings.join('；')}</Text>
            </div>
          ))}
        </Modal>
      </div>

      {/* 汇总 */}
      {!loading && results.length > 0 && (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
            <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value">{stats.total}<span className="kpi-unit">家</span></div><div className="kpi-label">查询主体</div></div></Col>
            <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value" style={{ color: 'var(--success)' }}>{stats.executable}<span className="kpi-unit">家</span></div><div className="kpi-label">有可执行财产线索</div></div></Col>
            <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value" style={{ color: 'var(--primary)' }}>{stats.investCount}<span className="kpi-unit">条</span></div><div className="kpi-label">对外投资线索</div></div></Col>
            <Col xs={12} md={6}><div className="kpi-card"><div className="kpi-value" style={{ color: 'var(--danger)' }}>{stats.execCount}<span className="kpi-unit">条</span></div><div className="kpi-label">被执行记录</div></div></Col>
          </Row>

          {/* 追索策略建议 */}
          <div className="section-card" style={{ marginBottom: 20 }}>
            <div className="section-title">追索策略建议</div>
            {(() => {
              const advice = []
              if (stats.executable > 0) advice.push(`有 ${stats.executable} 家主体存在可执行财产线索（对外投资/股权/抵押），建议优先对其实施财产保全与执行（诉前保全 → 诉讼 → 申请执行）`)
              else advice.push('未发现可执行财产线索的主体，建议通过律师调查令/财产报告令深挖银行账户、不动产、车辆、应收账款等')
              if (stats.execCount > 0) advice.push(`共 ${stats.execCount} 条被执行记录：关注在办执行案件，及时申请参与分配、债权申报`)
              if (stats.withRisk > 0) advice.push(`${stats.withRisk} 家主体有司法风险记录，追索时可同步申请限高、失信惩戒与联动布控施压`)
              if (advice.length === 0) advice.push('查询结果为空，请确认企业名称准确（需完整全称）后重试')
              return advice.map((t, i) => (
                <Alert key={i} type="info" showIcon message={t} style={{ marginBottom: 8 }} />
              ))
            })()}
            <Text type="secondary" style={{ fontSize: 12 }}>
              通用追索路径：诉前财产保全 → 诉讼/仲裁 → 申请强制执行 → 追加/变更被执行人 → 执行参与分配；对保证人可主张连带责任（需核对保证合同）。
            </Text>
          </div>
        </>
      )}

      {/* 逐主体结果 */}
      {results.map((r) => renderEntity(r))}
    </div>
  )
}
