import { useEffect, useRef, useState } from 'react'
import { Card, Input, Button, Upload, Typography, message, Alert, Modal, Space, Tag, List, Spin, Progress } from 'antd'
import { InboxOutlined, FileTextOutlined, DeleteOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { claimApi, taskApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'
import { useAuthStore } from '../store/auth'

const { TextArea } = Input
const { Dragger } = Upload
const { Title, Text, Paragraph } = Typography

// 脱敏示例（微透明显示在输入框内；关键信息以 XXX 代替，仅示意录入格式，不作为输入内容）
const SAMPLE_PLACEHOLDER = `请复制债权相关的文字信息，粘贴到此处；也可在上传文件区上传判决书 / 裁定书 / 债权介绍 / 债权列表等文件，由系统自动识别。\n\n录入示例（以下内容仅为示例，可按自己的方式自由填写，写得越详细，尽调结果越精准）：\n债务人：青岛XXX商贸有限公司（在业），债权本金XXX万元，债权利息XXX万元。\n保证人：XXX珠宝有限公司（在业）、XXX（2025年被吊销）、XXX等。\n抵押物：XXX名下位于青岛市市北区XXX路24号商业房产，证号青房地权市字第XXX号，建筑面积约XXX㎡。\n执行法院：市南法院。`

const SIZE_FMT = (n) => {
  if (n == null) return ''
  if (n < 1024) return `${n}B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`
  return `${(n / 1024 / 1024).toFixed(1)}MB`
}

export default function UploadPage() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const setClaims = useClaimDraftStore((s) => s.setClaims)
  const [text, setText] = useState('')
  const [textLoading, setTextLoading] = useState(false)

  // 材料识别：待识别文件队列 + 识别状态机
  // phase: idle(待识别) / running(识别中) / done(完成) / error(失败)
  const [docQueue, setDocQueue] = useState([]) // [{uid, name, size, file}]
  const [phase, setPhase] = useState('idle')
  const [elapsed, setElapsed] = useState(0)
  const [done, setDone] = useState(null) // 最近一次识别结果 {claims, file_names, is_single}
  const [locked, setLocked] = useState(false) // 识别出多条债权(清单) → 锁定，不再收文件
  const [lastError, setLastError] = useState('')
  const timerRef = useRef(null)
  const uidRef = useRef(0)

  const recognizing = phase === 'running'
  useEffect(() => () => clearInterval(timerRef.current), [])

  // 未登录：可浏览尽调输入页面，发起提取/导入需先登录
  const requireLogin = () => {
    if (token) return true
    Modal.confirm({
      title: '登录后即可尽调',
      content: '智能尽调将生成尽调任务与报告，请先登录。（未登录可浏览输入页面与示例）',
      okText: '去登录',
      cancelText: '取消',
      onOk: () => navigate('/login', { state: { from: window.location.pathname + window.location.search } }),
    })
    return false
  }

  const goPreview = (claims, warnings, dedup) => {
    setClaims(claims, warnings, dedup)
    navigate('/preview')
  }

  // 统一处理导入结果：检查重复提醒后直接进预览
  const handleImportResult = (resp, mode) => {
    const dedup = resp.data.dedup || {}
    const dupMsgs = []
    if (dedup.file_duplicate) dupMsgs.push('该文件此前已上传过，建议去「我的任务」查看已有记录')
    if (dedup.removed > 0) dupMsgs.push(`本次导入剔除 ${dedup.removed} 条重复债务人（同名只保留第一条）`)
    if ((dedup.batch_dups || []).length > 0) dupMsgs.push(`同一批内有 ${dedup.batch_dups.length} 条重复债务人，只能勾选其中一条`)
    if ((dedup.existing_dups || []).length > 0) dupMsgs.push(`其中 ${dedup.existing_dups.length} 条与您历史债权/报告中的债务人重复，建议先去「我的报告」查看`)

    if (dupMsgs.length) message.warning(dupMsgs.join('；'), 4)
    goPreview(resp.data.claims, resp.data.input_warnings, dedup)
  }

  // ---- 粘贴文本（空输入点「开始」按空内容提示）----
  const handleText = async () => {
    if (!text.trim()) return message.warning('请粘贴债权信息，或在上传区上传文件')
    if (text.trim().length < 10) return message.warning('请粘贴更完整的债权信息')
    if (!requireLogin()) return
    setTextLoading(true)
    try {
      const resp = await claimApi.importText(text)
      handleImportResult(resp, 'text')
    } catch { /* 拦截器已提示 */ } finally {
      setTextLoading(false)
    }
  }

  // ---- Excel 债权清单：并入统一识别（2026-09-05 起 Excel 与 Word/PDF 一样按内容识别，
  //      可能是债权列表/抵押物清单/无关表，不再单独走批量导入）----

  // ---- 单上传框：拖入文件只进队列（不触发后端），用户统一点「开始识别」----
  const addToQueue = (file) => {
    if (!requireLogin()) return false
    if (locked) {
      message.warning('本次上传已识别完成，不能再追加文件；如需补充材料，请在发起尽调生成报告后到报告页上传')
      return false
    }
    if (recognizing) {
      message.warning('正在识别中，请稍候…（无需重复添加）')
      return false
    }
    const dup = docQueue.find((q) => q.name === file.name && q.size === file.size)
    if (dup) {
      message.warning(`「${file.name}」已在待识别列表中，无需重复添加`)
      return false
    }
    const uid = `doc-${Date.now()}-${uidRef.current++}`
    setDocQueue((prev) => [...prev, { uid, name: file.name || '未命名', size: file.size, file }])
    setPhase('idle')
    setDone(null)
    return false
  }

  const removeFromQueue = (uid) => {
    if (recognizing) return
    setDocQueue((prev) => prev.filter((q) => q.uid !== uid))
    setPhase('idle')
  }

  const clearQueue = () => {
    if (recognizing) return
    setDocQueue([])
    setDone(null)
    setLocked(false)
    setPhase('idle')
    setLastError('')
  }

  const startTimer = () => {
    setElapsed(0)
    clearInterval(timerRef.current)
    timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000)
  }

  const stopTimer = () => {
    clearInterval(timerRef.current)
    timerRef.current = null
  }

  // 统一识别（2026-09-05）：全部文件（Excel/Word/PDF/图片）一起提交，系统按内容分流——
  //  债权清单(多行)→多条勾选；单份债权材料→单条；抵押物/租赁物清单→并入对应债权；无关文件→ignored
  // 状态机：点一次 → running(先上传进度 → 再轮询识别: 逐文件进度) → done(结果卡) / error
  const [jobLabel, setJobLabel] = useState('') // 轮询阶段文案
  const [jobProgress, setJobProgress] = useState(0)
  const [fileStates, setFileStates] = useState([]) // [{name, status, percent}]
  const [ignoredFiles, setIgnoredFiles] = useState([]) // [{name, reason}] 与本债权无关的文件
  const [fileClasses, setFileClasses] = useState([]) // [{name, level:1|2|3, type}] 每份文件重要等级
  // 上传进度（2026-09-05 用户确认 A 项：服务器上大文件上传可能明显慢于本地，需真实百分比）
  const [uploadPct, setUploadPct] = useState(null) // 0-100；null=不在上传
  const [uploadedText, setUploadedText] = useState('')

  const LEVEL_META = {
    1: { color: 'red', label: '一级·权威/合同' },
    2: { color: 'orange', label: '二级·机构出具' },
    3: { color: 'default', label: '三级·佐证' },
  }
  const levelTag = (fc) => {
    const m = LEVEL_META[fc?.level] || { color: 'default', label: '未定级' }
    return <Tag color={m.color} style={{ marginInlineEnd: 0 }} title={fc?.type || ''}>{m.label}</Tag>
  }

  const recognize = async () => {
    if (docQueue.length === 0) return message.warning('请先拖入或选择文件')
    if (recognizing) return
    setPhase('running')
    setDone(null)
    setLastError('')
    setIgnoredFiles([])
    setJobLabel('正在上传文件…')
    setJobProgress(1)
    setFileStates(docQueue.map((q) => ({ name: q.name, status: '未开始', percent: 0 })))
    setUploadPct(0)
    setUploadedText('')
    startTimer()
    try {
      // 1) 提交任务：先显示上传进度（onUploadProgress），传完立即拿到 job_id
      const submitResp = await claimApi.importDoc(
        docQueue.map((q) => q.file),
        (e) => {
          if (e && e.total > 0) {
            const pct = Math.min(99, Math.round((e.loaded / e.total) * 100))
            setUploadPct(pct)
            setUploadedText(`${(e.loaded / 1024 / 1024).toFixed(1)}/${(e.total / 1024 / 1024).toFixed(1)} MB`)
          }
        }
      )
      setUploadPct(100)
      const jobId = submitResp?.data?.job_id
      if (!jobId) throw new Error('任务提交失败，请重试')
      setUploadPct(null) // 上传完成 → 进入识别进度
      // 2) 轮询任务进度：显示每个文件进度条，直到 done/error
      let data = null
      let status = 'running'
      while (status === 'running') {
        await new Promise((r) => setTimeout(r, 1200))
        const pollResp = await claimApi.docJobStatus(jobId)
        data = pollResp?.data || {}
        status = data.status || 'running'
        if (data.file_states) setFileStates(data.file_states)
        setJobLabel(data.label || '正在识别中…')
        setJobProgress(data.progress || 0)
      }
      if (status === 'error') {
        setPhase('error')
        setLastError(data.error || '识别失败，请重试')
        return
      }
      const claims = (data.result && data.result.claims) || []
      const ignored = (data.result && data.result.ignored_files) || []
      if (claims.length === 0) {
        // 全部文件都未能识别为债权：如果存在被忽略的文件，让用户说明关联性后重试
        if (ignored.length > 0) {
          setPhase('done')
          setIgnoredFiles(ignored)
          setDone({ claims: [], ignored_only: true })
          return
        }
        setPhase('error')
        setLastError('未能识别到有效债权，请检查文件内容是否含债务人/本金/抵押物等信息')
        return
      }
      // 识别到债权：记录忽略文件（供"说明关联性→采纳重新分析"）与每份文件等级
      setIgnoredFiles(ignored)
      setFileClasses((data.result && data.result.file_classes) || [])
      // 点识别后锁定上传框：不再追加文件；补充材料一律在尽调报告生成后到报告页做（用户确认 2026-09-05）
      setLocked(true)
      if (claims.length === 1) {
        // 单条债权：进入结果卡（可发起尽调/去核对）
        setDone({ claims, file_names: data.result.file_names || [], warnings: data.result.input_warnings || [], dedup: data.result.dedup || {} })
        setPhase('done')
        message.success('已识别 1 条债权')
      } else {
        // 多条 = 债权清单/混合 → 弹选择列表（跳信息预处理勾选页）
        setDone({ claims, file_names: data.result.file_names || [], warnings: data.result.input_warnings || [], dedup: data.result.dedup || {}, is_multi: true })
        setPhase('done')
        message.success(`识别出 ${claims.length} 条债权，请勾选要尽调的记录`)
      }
    } catch (e) {
      setPhase('error')
      setUploadPct(null)
      let msg = ''
      try {
        const d = e?.response?.data?.detail
        msg = typeof d === 'string' ? d : Array.isArray(d) && d[0] ? (d[0].msg || JSON.stringify(d[0])) : (e?.message || '')
      } catch { msg = e?.message || '' }
      setLastError(msg || '识别失败，请重试（大文件可能需要更长时间）')
    } finally {
      stopTimer()
    }
  }

  // 忽略文件的关联说明：用户说明与本案有关 → 重新带说明识别（后端将说明并入该文件再分析）
  const [relationNotes, setRelationNotes] = useState({}) // {fileName: 说明}
  const [adopting, setAdopting] = useState(false)

  const adoptIgnored = async () => {
    // 将用户填写了关联说明的文件 + 说明，重新提交识别（说明并入文件名提示模型关联本案）
    const withNote = Object.entries(relationNotes)
      .filter(([, v]) => v && v.trim())
      .map(([name]) => docQueue.find((q) => q.name === name))
      .filter(Boolean)
    if (withNote.length === 0) {
      // 没填说明：全部直接忽略
      setIgnoredFiles([])
      setRelationNotes({})
      if ((done?.claims || []).length === 0) {
        // 没有任何债权被识别 → 回到待上传状态
        message.info('未填写关联说明的文件已忽略；如需重新上传请清空后再试')
        clearQueue()
      } else {
        message.info('未填写关联说明的文件已忽略')
      }
      return
    }
    setAdopting(true)
    startTimer()
    try {
      // 重新识别：只提交被采纳的文件（说明写入文件名提示，后端按内容重新判断归属）
      const resp = await claimApi.importDoc(
        withNote.map((q) => new File([q.file], `${q.name}（用户说明：${relationNotes[q.name]}）`, { type: q.file.type }))
      )
      const jobId = resp?.data?.job_id
      if (!jobId) throw new Error('任务提交失败')
      let data = null
      let status = 'running'
      while (status === 'running') {
        await new Promise((r) => setTimeout(r, 1200))
        const pollResp = await claimApi.docJobStatus(jobId)
        data = pollResp?.data || {}
        status = data.status || 'running'
        setJobLabel(data.label || '重新分析中…')
      }
      if (status === 'error') {
        setPhase('error')
        setLastError(data.error || '重新分析失败')
        return
      }
      const extraClaims = (data.result && data.result.claims) || []
      // 与被采纳文件一同识别的无关文件（仍无关）→ 保持忽略
      const stillIgnored = (data.result && data.result.ignored_files) || []
      if (extraClaims.length > 0) {
        // 采纳成功：与已有债权按债务人去重合并（采纳产生的 claim 已落库，直接采用）
        const existed = new Set((done?.claims || []).map((c) => c.debtor_name))
        const merged = [...(done?.claims || []), ...extraClaims.filter((c) => !existed.has(c.debtor_name))]
        setDone({ claims: merged, is_multi: merged.length > 1,
                  file_names: [...(done?.file_names || []), ...(data.result.file_names || [])], warnings: [], dedup: {} })
        setLocked(true)
        setIgnoredFiles(stillIgnored)
        setRelationNotes({})
        message.success(`已采纳 ${extraClaims.length} 条债权`)
      } else {
        message.warning('说明后仍未识别出有效债权，该文件忽略')
        setIgnoredFiles(stillIgnored.length ? stillIgnored : [])
        if (!(done?.claims || []).length) clearQueue()
      }
    } catch (e) {
      setPhase('error')
      setLastError(e?.message || '重新分析失败')
    } finally {
      stopTimer()
      setAdopting(false)
    }
  }

  // 清单（多条）→ 进预览勾选尽调
  const goMultiPreview = () => {
    if (!done) return
    handleImportResult({ data: { claims: done.claims, input_warnings: done.warnings, dedup: done.dedup } }, 'doc')
  }

  // 单条直尽调：直接发起任务（与预览页同一链路）
  const startSingleDD = async () => {
    const claim = done?.claims?.[0]
    if (!claim) return
    setPhase('running')
    try {
      const resp = await taskApi.create([claim.id], [claim.id])
      navigate(`/progress/${resp.data.id}`)
    } catch { /* 拦截器已提示 */ } finally {
      setPhase('done')
    }
  }

  const goSinglePreview = () => {
    if (!done) return
    goPreview(done.claims, done.warnings, done.dedup)
  }

  const single = (!done?.is_multi) ? (done?.claims?.[0] || null) : null
  // 来源文件 + 分级标签（识别后展示：哪份是一级判决/合同、二级机构报告、三级佐证）
  const sourceFiles = (done?.file_names || []).map((n) => {
    const fc = (done?.file_classes || fileClasses).find((c) => c.name === n)
    return { name: n, fc }
  })
  // 区分：已发起过尽调的历史重复（拦截） vs 仅导入过但未尽调（提示但不拦截，可正常尽调）
  const dups = done?.dedup?.existing_dups || []
  const singleStartedDup = dups.some((d) => d.started)
  const singleDupNames = dups.map((d) => d.debtor_name)
  const singleOnlyImported = dups.filter((d) => !d.started).map((d) => d.debtor_name)

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <Title level={3}>尽调输入</Title>
      <Paragraph type="secondary">粘贴债权文字或上传文件，系统自动提取结构化字段并发起尽调（最多支持 5 条同时尽调）。</Paragraph>

      {/* 上半：粘贴文本 */}
      <Card title="粘贴文字" style={{ marginBottom: 20 }}>
        <TextArea
          rows={9}
          placeholder={SAMPLE_PLACEHOLDER}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>支持从公告、拍卖页面、判决书等复制文字粘贴；关键信息缺失也没关系，会提示补齐。</Text>
          <Button type="primary" loading={textLoading} onClick={handleText}>开始</Button>
        </div>
      </Card>

      {/* 下半：上传文件（单框，不区分格式，系统按内容自动分流） */}
      <Card title="上传文件" style={{ marginBottom: 20 }}>
        <Dragger
          accept=".xlsx,.xls,.csv,.docx,.doc,.pdf,.txt,.md,.jpg,.jpeg,.png,.webp,.bmp"
          multiple
          disabled={recognizing}
          beforeUpload={addToQueue}
          showUploadList={false}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽文件到此处（Excel / Word / PDF / 图片均可）</p>
          <p className="ant-upload-hint">
            系统自动识别文件内容：债权清单（表格多笔）→ 勾选尽调；判决书/裁定书/合同等材料（单份）→ 可继续多传，全部收齐后统一分析；<br />
            自动识别债务人、债权人、本金、利息、利息计算方式、是否胜诉、抵押物（含设备租赁）等信息回填报告
          </p>
        </Dragger>

        {/* 已上传文件列表：每行右侧内嵌进度条（识别中显示进度，未识别无进度条，可删除） */}
        {docQueue.length > 0 && !locked && phase !== 'done' && (
          <div style={{ marginTop: 14 }}>
            {recognizing && (
              <div style={{ marginBottom: 8, fontSize: 13 }}>
                <Space size={8}>
                  <Spin size="small" />
                  <Text strong style={{ fontSize: 14 }}>{jobLabel || '正在识别…'}</Text>
                  {uploadPct != null
                    ? <Text type="secondary">正在上传文件… {uploadPct}%（{uploadedText}），文件越大上传越慢，请勿关闭页面</Text>
                    : <Text type="secondary">已处理 {elapsed} 秒；扫描件/大文件会慢一些，请勿关闭页面</Text>}
                </Space>
                {uploadPct != null && (
                  <Progress percent={Math.max(1, uploadPct)} size="small" style={{ marginTop: 6 }} />
                )}
              </div>
            )}
            <List
              size="small"
              style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: 6 }}
              dataSource={docQueue}
              renderItem={(q, idx) => {
                const fs = fileStates[idx] || {}
                return (
                  <List.Item
                    actions={[
                      <Button key="del" type="text" size="small" icon={<DeleteOutlined />} disabled={recognizing} onClick={() => removeFromQueue(q.uid)} />,
                    ]}
                  >
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 12 }}>
                      <Space size={8} style={{ minWidth: 180, flexShrink: 0 }}>
                        <FileTextOutlined style={{ color: 'var(--primary)' }} />
                        <Text style={{ fontSize: 13 }} ellipsis title={q.name}>{q.name}</Text>
                        <Tag style={{ marginInlineEnd: 0 }}>{SIZE_FMT(q.size)}</Tag>
                      </Space>
                      {recognizing && (
                        <div style={{ flex: 1 }}>
                          <Progress
                            percent={fs.percent || 0}
                            size="small"
                            status={fs.status === '无有效内容' ? 'exception' : fs.status === '已完成' ? 'success' : 'active'}
                            format={(p) => (fs.status === '已完成' ? '完成' : fs.status === '无有效内容' ? '无内容' : `${p}%`)}
                          />
                        </div>
                      )}
                    </div>
                  </List.Item>
                )
              }}
            />
          </div>
        )}

        {/* 识别失败：显示原因 + 可重试 */}
        {phase === 'error' && !recognizing && (
          <Alert
            style={{ marginTop: 12 }}
            type="error"
            showIcon
            message="识别失败"
            description={<div>{lastError || '请重试'}<div style={{ marginTop: 8 }}><Button size="small" onClick={recognize}>重试识别</Button></div></div>}
          />
        )}

        {/* 操作栏：识别中按钮灰禁 + 漏斗图标 */}
        {docQueue.length > 0 && !locked && phase !== 'done' && (
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button
              type="primary"
              icon={recognizing ? undefined : <ClockCircleOutlined />}
              disabled={recognizing}
              loading={recognizing}
              onClick={recognize}
            >
              {recognizing ? `识别中…（${elapsed} 秒）` : (phase === 'error' ? '重试识别' : `开始识别（${docQueue.length} 份）`)}
            </Button>
            <Button disabled={recognizing} onClick={clearQueue}>清空</Button>
          </div>
        )}

        {/* 单条结果：识别完成即锁定（补充材料请到尽调报告页） */}
        {single && phase === 'done' && (
          <Card size="small" style={{ marginTop: 14, background: '#F7F9FC' }} title={<Text strong>✅ 已识别 1 条债权</Text>}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>来源文件：</Text>
                <div style={{ marginTop: 4 }}>
                  {sourceFiles.length > 0 ? sourceFiles.map((sf, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
                      <Text style={{ fontSize: 13 }} ellipsis title={sf.name}>{sf.name}</Text>
                      {levelTag(sf.fc)}
                    </div>
                  )) : <Text style={{ fontSize: 13 }}>—</Text>}
                </div>
              </div>
              <div><Text type="secondary" style={{ fontSize: 12 }}>债务人：</Text><Text style={{ fontSize: 13 }}>{single.debtor_name || '—'}</Text></div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>摘要：</Text>
                <Text style={{ fontSize: 13 }}>
                  {[
                    single.principal_cents != null ? `本金 ${(single.principal_cents / 100).toLocaleString()} 元` : '',
                    single.interest_cents != null ? `利息 ${(single.interest_cents / 100).toLocaleString()} 元` : '',
                    single.creditor ? `债权人 ${single.creditor}` : '',
                    single.collateral ? `抵押物：${single.collateral}` : '',
                    single.judgment_result ? `裁判结果：${single.judgment_result}` : '',
                  ].filter(Boolean).join('；') || '已提取到债权信息，可发起尽调'}
                </Text>
              </div>
              <Alert type="info" showIcon style={{ marginTop: 4 }}
                message="本次上传已识别完成；如需补充该债权的判决多页/裁定书/合同等材料，请在发起尽调生成报告后，于报告页的「补充材料」处上传" />
              {singleOnlyImported.length > 0 && (
                <Alert type="warning" showIcon style={{ marginTop: 4 }}
                  message={`债务人「${singleOnlyImported.join('、')}」您之前导入过但未发起尽调，本次可正常发起尽调（历史导入记录不会产生报告）`} />
              )}
              {singleStartedDup && (
                <Alert type="error" showIcon style={{ marginTop: 4 }}
                  message={`债务人「${singleDupNames.join('、')}」已生成过尽调报告，建议先去「我的报告」查看；如需重新尽调请先删除旧报告`} />
              )}
              {single.completeness === 'red' && (
                <Alert type="warning" showIcon style={{ marginTop: 4 }} message="关键信息不全（缺债务人/本金/抵押物），需先补充后再尽调" />
              )}
            </Space>
            <Space style={{ marginTop: 12 }}>
              <Button type="primary" disabled={!single || single.completeness === 'red' || singleStartedDup} loading={recognizing} onClick={startSingleDD}>
                发起尽调
              </Button>
              <Button onClick={goSinglePreview}>去核对/编辑</Button>
              <Button onClick={clearQueue}>重新开始</Button>
            </Space>
          </Card>
        )}

        {/* 多条结果：债权清单锁定，去勾选尽调（选 A：跳现有信息预处理勾选页） */}
        {done?.is_multi && phase === 'done' && (
          <Card size="small" style={{ marginTop: 14, background: '#F7F9FC' }} title={<Text strong>✅ 识别出 {done.claims.length} 条债权（债权清单/多份债权材料）</Text>}>
            <Alert type="info" showIcon style={{ marginBottom: 10 }}
              message="请勾选要对哪条债权进行尽调（可多选）；其他文件识别出的信息会自动补全所选债权的字段"
              description="如需给选中债权补充判决书等材料，请在生成尽调报告后，于报告页的「补充材料」处上传。" />
            <Space>
              <Button type="primary" onClick={goMultiPreview}>去勾选尽调（{done.claims.length} 条）</Button>
              <Button onClick={clearQueue}>放弃这批</Button>
            </Space>
          </Card>
        )}

        {/* 无关文件（ignored）：提示 + 关联性说明输入，用户说明有关则采纳重新分析 */}
        {phase === 'done' && ignoredFiles.length > 0 && (
          <Card size="small" style={{ marginTop: 14 }} title={<Text strong>已忽略与本案无关的文件（可说明关联性）</Text>}>
            <Alert type="warning" showIcon style={{ marginBottom: 10 }}
              message="以下文件被判断为与本案债权无关，未参与识别；如实际有关，请填写说明后采纳，将重新分析并用于报告" />
            {ignoredFiles.map((ig, i) => (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <FileTextOutlined style={{ color: '#faad14' }} />
                  <Text style={{ fontSize: 13 }}>{ig.name}</Text>
                  {ig.reason && <Text type="secondary" style={{ fontSize: 12 }}>（{ig.reason}）</Text>}
                </div>
                <Input
                  size="small"
                  placeholder="该文件与本案的关联说明（如：是本债权抵押物清单/补充协议；不填则直接忽略）"
                  value={relationNotes[ig.name] || ''}
                  onChange={(e) => setRelationNotes((prev) => ({ ...prev, [ig.name]: e.target.value }))}
                />
              </div>
            ))}
            <Space>
              <Button type="primary" loading={adopting} onClick={adoptIgnored}>采纳（带说明重新分析）</Button>
              <Button onClick={() => { setIgnoredFiles([]); setRelationNotes({}) }}>不采纳，直接忽略</Button>
            </Space>
          </Card>
        )}
      </Card>
    </div>
  )
}
