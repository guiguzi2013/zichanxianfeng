import { useState } from 'react'
import { Card, Tabs, Input, Button, Upload, Typography, message, Alert } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { claimApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'

const { TextArea } = Input
const { Dragger } = Upload
const { Title, Text, Paragraph } = Typography

const SAMPLE_TEXT = `债务人：青岛青海源商贸有限公司(在业)，债权本金539万元，债权利息429万元。
保证人：青岛宝祥真珠宝有限公司(在业)、青岛常天赢集团有限公司（2025-05-21被吊销）、吴迪、王国平、曲红霞等。
抵押物：王国平名下位于青岛市市北区广饶路24号-2、24号-3和28号-2的三处商业网点房产，证号青房地权市字第201034568号等，建筑面积共计687.34㎡。
执行法院：市南法院。`

export default function UploadPage() {
  const navigate = useNavigate()
  const setClaims = useClaimDraftStore((s) => s.setClaims)
  const [tab, setTab] = useState('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)

  const goPreview = (claims, warnings) => {
    setClaims(claims, warnings)
    navigate('/preview')
  }

  const handleText = async () => {
    if (text.trim().length < 10) return message.warning('请粘贴更完整的债权信息')
    setLoading(true)
    try {
      const resp = await claimApi.importText(text)
      goPreview(resp.data.claims, resp.data.input_warnings)
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  const handleLink = async () => {
    if (!url.trim()) return message.warning('请输入拍卖链接')
    setLoading(true)
    try {
      const resp = await claimApi.importLink(url)
      goPreview(resp.data.claims, resp.data.input_warnings)
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  const handleExcel = async (file) => {
    setLoading(true)
    try {
      const resp = await claimApi.importExcel(file)
      const mapping = resp.data.column_mapping
      const unmapped = resp.data.unmapped_columns || []
      const mappedCount = mapping ? Object.keys(mapping).length : 0
      const extra = unmapped.length ? `，未识别列：${unmapped.join('、')}（已保留原文）` : ''
      message.success(`已解析 ${resp.data.claims.length} 条债权，自动识别 ${mappedCount} 列${extra}`)
      goPreview(resp.data.claims, resp.data.input_warnings)
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
    return false // 阻止默认上传
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '32px 16px' }}>
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
    </div>
  )
}
