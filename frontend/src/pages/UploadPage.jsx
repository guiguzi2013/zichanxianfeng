import { useState } from 'react'
import { Card, Tabs, Input, Button, Upload, Typography, message, Alert, Modal } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { claimApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'
import { useAuthStore } from '../store/auth'

const { TextArea } = Input
const { Dragger } = Upload
const { Title, Text, Paragraph } = Typography

const SAMPLE_TEXT = `债务人：青岛青海源商贸有限公司(在业)，债权本金539万元，债权利息429万元。
保证人：青岛宝祥真珠宝有限公司(在业)、青岛常天赢集团有限公司（2025-05-21被吊销）、吴迪、王国平、曲红霞等。
抵押物：王国平名下位于青岛市市北区广饶路24号-2、24号-3和28号-2的三处商业网点房产，证号青房地权市字第201034568号等，建筑面积共计687.34㎡。
执行法院：市南法院。`

export default function UploadPage() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const setClaims = useClaimDraftStore((s) => s.setClaims)
  const [tab, setTab] = useState('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingDup, setPendingDup] = useState(null) // { claims, warnings, dedup } 重复文件确认后继续

  // 未登录：可浏览尽调输入页面，发起提取/导入需先登录
  const requireLogin = () => {
    if (token) return true
    Modal.confirm({
      title: '登录后即可尽调',
      content: '智能尽调将生成尽调任务与报告，请先登录。（未登录可浏览输入页面与示例）',
      okText: '去登录',
      cancelText: '取消',
      onOk: () => navigate('/login'),
    })
    return false
  }

  const goPreview = (claims, warnings, dedup) => {
    setClaims(claims, warnings, dedup)
    navigate('/preview')
  }

  // 统一处理导入结果：先检查重复提醒，再决定是否直接进预览
  const handleImportResult = (resp, mode) => {
    const dedup = resp.data.dedup || {}
    const dupMsgs = []
    if (dedup.file_duplicate) dupMsgs.push('该文件此前已上传过，建议去「我的任务」查看已有记录')
    if (dedup.removed > 0) dupMsgs.push(`本次导入剔除 ${dedup.removed} 条重复债务人（同名只保留第一条）`)
    if ((dedup.batch_dups || []).length > 0) dupMsgs.push(`同一批内有 ${dedup.batch_dups.length} 条重复债务人，只能勾选其中一条`)
    if ((dedup.existing_dups || []).length > 0) dupMsgs.push(`其中 ${dedup.existing_dups.length} 条与您历史债权/报告中的债务人重复，建议先去「我的报告」查看`)

    // 文件重复：弹确认，用户选继续才进预览
    if (dedup.file_duplicate && mode === 'excel') {
      setPendingDup({ claims: resp.data.claims, warnings: resp.data.input_warnings, dedup, dupMsgs })
      return
    }
    if (dupMsgs.length) {
      message.warning(dupMsgs.join('；'), 4)
    }
    goPreview(resp.data.claims, resp.data.input_warnings, dedup)
  }

  const handleText = async () => {
    if (text.trim().length < 10) return message.warning('请粘贴更完整的债权信息')
    if (!requireLogin()) return
    setLoading(true)
    try {
      const resp = await claimApi.importText(text)
      handleImportResult(resp, 'text')
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  const handleLink = async () => {
    if (!url.trim()) return message.warning('请输入拍卖链接')
    if (!requireLogin()) return
    setLoading(true)
    try {
      const resp = await claimApi.importLink(url)
      handleImportResult(resp, 'link')
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  const handleExcel = async (file) => {
    if (!requireLogin()) return false // 未登录：阻止上传，提示登录
    setLoading(true)
    try {
      const resp = await claimApi.importExcel(file)
      const mapping = resp.data.column_mapping
      const unmapped = resp.data.unmapped_columns || []
      const mappedCount = mapping ? Object.keys(mapping).length : 0
      const extra = unmapped.length ? `，未识别列：${unmapped.join('、')}（已保留原文）` : ''
      message.success(`已解析 ${resp.data.claims.length} 条债权，自动识别 ${mappedCount} 列${extra}`)
      handleImportResult(resp, 'excel')
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
    return false // 阻止默认上传
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <Title level={3}>尽调输入</Title>
      <Paragraph type="secondary">支持三种方式输入债权信息，系统将自动提取结构化字段（最多支持 5 条同时尽调）。</Paragraph>

      <Card>
        <Tabs activeKey={tab} onChange={setTab} items={[
          {
            key: 'text',
            label: '📋 粘贴文本',
            children: (
              <>
                <TextArea
                  rows={8}
                  placeholder="从公告、拍卖页面等复制债权信息文字粘贴到这里…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between' }}>
                  <Button size="small" onClick={() => setText(SAMPLE_TEXT)}>填入示例</Button>
                  <Button type="primary" loading={loading} onClick={handleText}>提取信息</Button>
                </div>
              </>
            ),
          },
          {
            key: 'link',
            label: '🔗 粘贴链接',
            children: (
              <>
                <Input
                  size="large"
                  placeholder="粘贴淘宝/京东司法拍卖链接…"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                <Alert
                  style={{ marginTop: 12 }}
                  type="info"
                  showIcon
                  message="抓取说明"
                  description="系统将尝试抓取页面内容；若目标站点反爬拦截，请改用「粘贴文本」方式，把页面文字复制进来。"
                />
                <div style={{ marginTop: 12, textAlign: 'right' }}>
                  <Button type="primary" loading={loading} onClick={handleLink}>抓取并提取</Button>
                </div>
              </>
            ),
          },
          {
            key: 'excel',
            label: '📊 上传Excel',
            children: (
              <>
                <Dragger
                  accept=".xlsx,.xls,.csv"
                  beforeUpload={handleExcel}
                  showUploadList={false}
                >
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p className="ant-upload-text">点击或拖拽 Excel 文件到此处</p>
                  <p className="ant-upload-hint">支持 .xlsx / .xls / .csv 债权清单，自动识别列映射（表头如：债权项目/债权本金/保证人/抵押物等）</p>
                </Dragger>
              </>
            ),
          },
        ]} />
      </Card>

      {/* 重复文件确认弹窗 */}
      <Modal
        title="文件已上传过"
        open={pendingDup != null}
        onCancel={() => setPendingDup(null)}
        onOk={() => {
          const p = pendingDup
          setPendingDup(null)
          message.warning((p.dupMsgs || []).join('；'), 4)
          goPreview(p.claims, p.warnings, p.dedup)
        }}
        okText="仍要继续"
        cancelText="取消"
      >
        <Alert type="warning" showIcon message="检测到您之前上传过该文件" description="为避免重复尽调，建议先去「我的任务」查看已有记录。若该文件内容有更新，可继续导入。" />
      </Modal>
    </div>
  )
}
