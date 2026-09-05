import { useEffect, useState } from 'react'
import { Card, Descriptions, Tag, Button, Typography, Spin, Alert, message, Row, Col, Space, Table, Input } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, FundOutlined, WarningOutlined, SolutionOutlined, FireOutlined, FileTextOutlined, DownloadOutlined } from '@ant-design/icons'
import client from '../api/client'
import { claimApi, feedAttachmentApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'
import { useAuthStore } from '../store/auth'
import LoginModal from '../components/LoginModal'
import { canDueDiligence } from '../utils/claimEligibility'

const { Title, Text, Paragraph } = Typography

export default function AssetDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const setClaims = useClaimDraftStore((s) => s.setClaims)
  const token = useAuthStore((s) => s.token)
  const [item, setItem] = useState(null)
  const [related, setRelated] = useState([]) // 相关推荐（捡漏/精选）
  const [loading, setLoading] = useState(true)
  const [extracting, setExtracting] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [pendingAtt, setPendingAtt] = useState(null) // 登录后待下载的附件索引

  useEffect(() => {
    client.get(`/feed/${id}`)
      .then((resp) => setItem(resp.data))
      .catch(() => { /* 拦截器已提示 */ })
      .finally(() => setLoading(false))
  }, [id])

  // 加载相关推荐（同栏目其他债权，排除当前）
  useEffect(() => {
    if (!item) return
    const sec = item.section === 'bargain' ? 'bargain' : 'featured'
    client.get(`/feed?section=${sec}&page_size=100`).then((resp) => {
      const list = (resp.data?.items || []).filter((it) => it.id !== item.id).slice(0, 4)
      setRelated(list)
    }).catch(() => {})
  }, [item])

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  if (!item) return <div style={{ textAlign: 'center', padding: 80 }}><Title level={4}>内容不存在</Title></div>

  const detail = item.detail || {}
  const isBargain = item.section === 'bargain'
  // 2026-09-02：债权公告（智收云索引·报纸公告）——详情页仿智收云格式，不套用精选/捡漏表格
  const isNotice = item.section === 'notice'

  // 资产包判定（2026-09-02 用户确认）：announce_table 存在且含债务人列、数据行 ≥2（不含合计行）
  const isPackage = (() => {
    const at = detail.announce_table
    if (!at || !at.headers || !at.rows) return false
    const headers = (at.headers || []).map((h) => String(h || ''))
    if (!headers.some((h) => /债务人|借款企业|借款人|单位名称|企业名称/.test(h))) return false
    const dataRows = (at.rows || []).filter((r) => {
      const first2 = (r || []).slice(0, 2).map((c) => String(c || '').replace(/[\s\u3000]/g, ''))
      return !first2.some((c) => /合计|总计|小计/.test(c))
    })
    return dataRows.length >= 2
  })()

  // 资产包每户 → 供 canDD/startDD 使用
  const packageRows = isPackage ? (detail.announce_table.rows || []).filter((r) => {
    const first2 = (r || []).slice(0, 2).map((c) => String(c || '').replace(/[\s\u3000]/g, ''))
    return !first2.some((c) => /合计|总计|小计/.test(c))
  }).map((r) => {
    const headers = detail.announce_table.headers || []
    const get = (re) => {
      const i = headers.findIndex((h) => re.test(String(h || '')))
      return i >= 0 ? String(r[i] || '').trim() : ''
    }
    return {
      debtor_name: get(/债务人|借款企业|借款人|单位名称|企业名称/),
      claim_total: get(/本金余额|贷款本金|本金|债权本金/),
      collateral_desc: get(/担保情况|担保措施|抵押情况|抵质押|保证情况|担保|抵押/),
      collateral_type: '',
      interest: get(/结欠利息|利息余额|利息|重组收益/),
    }
  }) : []

  const startDD = async () => {
    setExtracting(true)
    try {
      // 资产包：按表格按户拆分（2026-09-02 用户确认：包中任意一条满足即可发起，用户到预处理页勾选）
      if (isPackage && detail.announce_table) {
        const resp = await claimApi.importPackage(
          detail.announce_table.headers,
          detail.announce_table.rows,
          item.title,
          item.source_url || ''
        )
        setClaims(resp.data.claims)
        message.success(`已按表格拆分为 ${resp.data.split_count || resp.data.claims.length} 条债权，请勾选要尽调的记录`)
        navigate('/preview')
        return
      }
      const atts = (detail.attachments || []).map((a, i) => `${a.name}（可下载：/api/feed/${item.id}/attachments/${i}）`).join('；')
      const vr = detail.valuation_report || {}
      const vrText = vr.year && vr.value_text ? `评估报告：${vr.year}年评估价值${vr.value_text}（2年内可直接采用，超2年仅参考）` : ''
      const sourceText = `${item.title}\n${item.summary || ''}\n${JSON.stringify(detail || {})}${atts ? `\n重要文件下载：${atts}` : ''}${vrText ? `\n${vrText}` : ''}`
      const resp = await claimApi.importText(sourceText)
      setClaims(resp.data.claims)
      message.success('已提取字段，请确认后尽调')
      navigate('/preview')
    } catch { /* 拦截器已提示 */ } finally {
      setExtracting(false)
    }
  }

  // 附件下载（2026-09-01：未登录先弹登录框，登录后留在原页自动继续下载）
  const doDownload = async (attIndex) => {
    try {
      const resp = await client.get(`/feed/${item.id}/attachments/${attIndex}`, { responseType: 'blob' })
      const blob = resp // 拦截器 (resp) => resp.data 已解包，resp 就是 Blob
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const att = (detail.attachments || [])[attIndex] || {}
      a.href = url
      a.download = att.name || `附件${attIndex + 1}`
      document.body.appendChild(a)
      a.click()
      URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (e) {
      // 401：token 过期或未登录 → 弹登录框
      if (e?.response?.status === 401) {
        setPendingAtt(attIndex)
        setLoginOpen(true)
      } else {
        message.error(e?.response?.data?.detail || e.message || '下载失败')
      }
    }
  }

  const downloadAttachment = (attIndex) => {
    if (!token) {
      // 未登录：记住待下载项，弹登录框（留在原页）
      setPendingAtt(attIndex)
      setLoginOpen(true)
      return
    }
    doDownload(attIndex)
  }

  const onLoginSuccess = () => {
    // 登录成功：留在原页，自动继续下载之前想下载的附件
    if (pendingAtt != null) {
      const idx = pendingAtt
      setPendingAtt(null)
      doDownload(idx)
    }
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
      {/* 顶部搜索条（2026-09-02：去掉重复返回，搜索条放右侧；返回保留在下方标签行） */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Input.Search
          allowClear
          placeholder="搜索债权 / 债务人 / 抵押物 / 地区"
          style={{ width: 320 }}
          onSearch={(v) => { if (v && v.trim()) navigate(`/search?q=${encodeURIComponent(v.trim())}`) }}
        />
      </div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ paddingLeft: 0 }}>返回</Button>
        {isBargain ? <Tag color="orange" icon={<FundOutlined />}>捡漏标的</Tag> : <Tag color="green">债权信息</Tag>}
        {detail.discount && <Tag color="red">{detail.discount}</Tag>}
      </Space>
      <Title level={3} style={{ marginTop: 0 }}>{item.title}</Title>
      <Text type="secondary">来源：{item.source || '—'}</Text>

      <Row gutter={[16, 16]} style={{ marginTop: 20 }}>
        {/* 左栏：基本信息 + 招商原文 */}
        <Col xs={24} lg={15}>
          <Card title="基本信息" style={{ marginBottom: 16 }}>
            {/* 阿里资产登录提示已删除（2026-09-05 用户两次圈1：登录后仍是列表字段，此提示像替抓不到找借口，无信息价值） */}
            {isNotice ? (
              /* 债权公告（智收云索引·报纸公告）——仿智收云公告详情页格式（2026-09-02）
                 指标卡(债权金额/本金/户数) + 来源(报纸/日期/类型) + 债权方 + 债务人 + 正文 + 链接跳转 */
              <div>
                <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                  <Col span={8}><div style={{ textAlign: 'center', padding: '12px 6px', background: 'var(--bg-soft, #F7F9FC)', borderRadius: 8 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-weak)' }}>债权金额</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--danger)', marginTop: 4 }}>{detail.claim_total || '—'}</div>
                  </div></Col>
                  <Col span={8}><div style={{ textAlign: 'center', padding: '12px 6px', background: 'var(--bg-soft, #F7F9FC)', borderRadius: 8 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-weak)' }}>本金</div>
                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{detail.principal || '—'}</div>
                  </div></Col>
                  <Col span={8}><div style={{ textAlign: 'center', padding: '12px 6px', background: 'var(--bg-soft, #F7F9FC)', borderRadius: 8 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-weak)' }}>债务人户数</div>
                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>{detail.households || '—'}</div>
                  </div></Col>
                </Row>
                <div style={{ marginBottom: 12 }}>
                  {detail.notice_type && <Tag color="blue" style={{ marginRight: 8 }}>{detail.notice_type}</Tag>}
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    来源：{detail.paper || item.source || '—'}
                    {(detail.notice_date || detail.publish_date) && <span> ｜ 公告日期：{detail.notice_date || detail.publish_date}</span>}
                  </Text>
                </div>
                <Descriptions column={1} size="small" bordered labelStyle={{ width: 110 }}>
                  <Descriptions.Item label="债权方">{detail.transferor || '未披露'}</Descriptions.Item>
                  <Descriptions.Item label="债务人">{detail.debtor_names || '未披露'}</Descriptions.Item>
                  {(detail.asset_pkg_no || detail.deadline || detail.interest) && (
                    <>
                      {detail.asset_pkg_no && <Descriptions.Item label="公告编号">{detail.asset_pkg_no}</Descriptions.Item>}
                      {detail.interest && <Descriptions.Item label="利息">{detail.interest}</Descriptions.Item>}
                      {detail.other_fees && <Descriptions.Item label="其他费用">{detail.other_fees}</Descriptions.Item>}
                      {detail.deadline && <Descriptions.Item label="金额截止日">{detail.deadline}</Descriptions.Item>}
                    </>
                  )}
                </Descriptions>
                {/* 2026-09-03：正文排版后逐段展示（禁止文字堆砌；表格文字已在抓取时从正文剔除，
                    原文表格由下方自建表格展示——用户修改1） */}
                {detail.body_paragraphs && detail.body_paragraphs.length > 0 ? (
                  <div style={{ marginTop: 14 }}>
                    {detail.body_paragraphs.map((p, i) => (
                      <Paragraph key={i} style={{
                        fontSize: 13, lineHeight: 2, color: 'var(--text-main)', marginBottom: 10,
                        textIndent: p.length > 40 ? '2em' : 0, whiteSpace: 'pre-wrap',
                      }}>{p}</Paragraph>
                    ))}
                  </div>
                ) : (detail.paper_body || detail.body_text) ? (
                  <div style={{ marginTop: 12, fontSize: 13, lineHeight: 2, color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>
                    {detail.paper_body || detail.body_text}
                  </div>
                ) : null}
                {/* 2026-09-03：AMC 公告原文表格（有表抓表规则：按原文表格回填展示） */}
                {(detail.tables || []).length > 0 && detail.tables.map((tb, ti) => {
                  const headers = tb.headers || []
                  const rows = tb.rows || []
                  if (!headers.length) return null
                  return (
                    <div key={ti} style={{ marginTop: 16 }}>
                      <Text strong style={{ fontSize: 13 }}>{detail.tables.length > 1 ? `原文表格 ${ti + 1}` : '原文明细表'}</Text>
                      <Table
                        size="small"
                        bordered
                        pagination={false}
                        rowKey={(_, i) => i}
                        scroll={{ x: 'max-content' }}
                        style={{ marginTop: 8 }}
                        columns={headers.map((h, i) => ({
                          title: h || `列${i + 1}`,
                          dataIndex: `c${i}`,
                          key: `c${i}`,
                          width: /金额|余额|本金|利息|费用|违约金|面积/.test(h) ? 130 : 160,
                          render: (v) => <span style={{ fontSize: 12 }}>{v || ''}</span>,
                        }))}
                        dataSource={rows.map((r) => {
                          const obj = {}
                          headers.forEach((_, i) => { obj[`c${i}`] = r[i] || '' })
                          return obj
                        })}
                      />
                    </div>
                  )
                })}
              </div>
            ) : isBargain ? (
              /* 捡漏基本信息（2026-09-02 用户要求按捡漏特点改，区别于精选债权表格）：
                 捡漏=破产处置资产（应收债权/股权/实物/车位/房产），无债权式利息/担保/保证概念 */
              <Descriptions column={2} size="small" bordered labelStyle={{ width: 110 }}>
                <Descriptions.Item label="标的类型">
                  {(() => {
                    const t = `${item.title || ''} ${detail.collateral_desc || ''} ${detail.short_title || ''}`
                    if (detail.collateral_type) return detail.collateral_type
                    if (/应收/.test(t)) return '应收债权'
                    if (/股权|出资/.test(t)) return '股权/出资款'
                    if (/车位|车库/.test(t)) return '车位'
                    if (/房产|房屋|楼|住宅|大厦/.test(t)) return '房产'
                    if (/设备|机器/.test(t)) return '设备'
                    if (/存货|物资|板房/.test(t)) return '存货/物资'
                    return '破产处置'
                  })()}
                </Descriptions.Item>
                <Descriptions.Item label="金额">{detail.claim_total || '未披露'}</Descriptions.Item>
                <Descriptions.Item label="挂牌价">{detail.listing_price || '未披露'}</Descriptions.Item>
                <Descriptions.Item label="状态">{detail.auction_status || '未披露'}</Descriptions.Item>
                <Descriptions.Item label="地区">{detail.region || '未披露'}</Descriptions.Item>
                <Descriptions.Item label="处置方">{detail.transferor || '未披露'}</Descriptions.Item>
                <Descriptions.Item label="拍卖时间">{detail.auction_time || '未披露'}</Descriptions.Item>
                <Descriptions.Item label="折扣">{detail.discount || detail.discount_rate || '未披露'}</Descriptions.Item>
                <Descriptions.Item label="标的描述" span={2}>
                  {detail.collateral_desc || detail.short_title || '未披露'}
                </Descriptions.Item>
              </Descriptions>
            ) : (
            <Descriptions column={2} size="small" bordered labelStyle={{ width: 110 }}>
              <Descriptions.Item label="案号">{detail.case_no || '待补充'}</Descriptions.Item>
              <Descriptions.Item label="债权本金">{detail.claim_total || '未披露'}</Descriptions.Item>
              <Descriptions.Item label="利息">{detail.interest || '未披露'}</Descriptions.Item>
              <Descriptions.Item label="罚息">{detail.penalty || '未披露'}</Descriptions.Item>
              <Descriptions.Item label="其他费用">{detail.other_fees || '未披露'}</Descriptions.Item>
              <Descriptions.Item label="本息合计">{detail.total_claims || '未披露'}</Descriptions.Item>
              <Descriptions.Item label="判决结果">{detail.judgment || '待补充'}</Descriptions.Item>
              {/* 2026-09-02：执行状态 → 司法状态（涵盖诉讼+执行，如"执行终本/已诉/执行中"） */}
              <Descriptions.Item label="司法状态">
                <Tag color={detail.judicial_status === '执行中' ? 'orange' : detail.judicial_status === '已判决' ? 'blue' : 'default'}>
                  {detail.judicial_status || detail.execution || '未披露'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="债务人" span={2}>
                {detail.debtor_count > 1
                  ? <span>见详情（共 {detail.debtor_count} 人）<Text type="secondary" style={{ fontSize: 11 }}>（见下方招商原文）</Text></span>
                  : (detail.debtor_name || '未披露')}
              </Descriptions.Item>
              <Descriptions.Item label="担保方式" span={2}>{detail.guaranty_type || '未披露'}</Descriptions.Item>
              <Descriptions.Item label="抵押物" span={2}>
                {detail.collateral_type ? <span>{detail.collateral_type}</span> : '未披露'}
                {detail.collateral_desc && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>{detail.collateral_desc}</div>}
              </Descriptions.Item>
              <Descriptions.Item label="保证人" span={2}>{detail.guarantor_names || '未披露'}</Descriptions.Item>
              <Descriptions.Item label="地区" span={2}>{detail.region || '未披露'}</Descriptions.Item>
            </Descriptions>
            )}
          </Card>

          {/* 重要文件（2026-09-01：京东公告信息类附件，已保存到服务器，用户可下载） */}
          {(detail.attachments && detail.attachments.length > 0) && (
            <Card title={<Space><FileTextOutlined />重要文件</Space>} style={{ marginBottom: 16 }}>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                以下文件来自原公告（资产清单/评估报告/抵押物清单/判决书等，word/excel/pdf 格式），已保存到平台，登录后可下载。
              </Text>
              <Space direction="vertical" style={{ width: '100%' }} size={6}>
                {detail.attachments.map((att, i) => {
                  const name = att.name || `附件${i + 1}`
                  const isInfo = att.type === 'info'
                  const isVal = att.type === 'valuation'
                  const isExternal = !!(att.url && !att.local_path)  // AMC 官网附件：外链打开
                  const vr = att.valuation || (detail.valuation_report && isVal ? detail.valuation_report : null)
                  const valAge = vr && vr.year ? new Date().getFullYear() - vr.year : null
                  return (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, padding: '6px 10px', background: isVal ? '#E6F4FF' : isInfo ? '#EFFAF5' : '#f6f8fa', borderRadius: 6, border: isVal ? '1px solid #91caff' : isInfo ? '1px solid #B7EBD6' : '1px solid #f0f0f0' }}>
                      <Space size={6} style={{ minWidth: 0 }}>
                        <FileTextOutlined style={{ color: isVal ? 'var(--primary)' : isInfo ? 'var(--success)' : 'var(--text-secondary)' }} />
                        <Text style={{ fontSize: 13 }} ellipsis={{ tooltip: name }}>{name}</Text>
                        {isVal && <Tag color="blue" style={{ marginInlineEnd: 0 }}>评估报告</Tag>}
                        {isVal && vr && vr.year && (
                          <Tag color={valAge !== null && valAge <= 2 ? 'green' : 'orange'} style={{ marginInlineEnd: 0 }}>
                            {vr.year}年{valAge !== null && valAge <= 2 ? '（2年内，可直接参考）' : '（超2年，仅供参考）'}
                          </Tag>
                        )}
                        {isInfo && <Tag color="green" style={{ marginInlineEnd: 0 }}>信息文件</Tag>}
                        {isExternal && <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>官网原文</Tag>}
                      </Space>
                      {isExternal ? (
                        <Button size="small" type="primary" icon={<DownloadOutlined />} onClick={() => window.open(att.url, '_blank')}>
                          打开原文
                        </Button>
                      ) : (
                        <Button size="small" type={(isInfo || isVal) ? 'primary' : 'default'} icon={<DownloadOutlined />}
                          onClick={() => downloadAttachment(i)}>
                          下载
                        </Button>
                      )}
                    </div>
                  )
                })}
              </Space>
            </Card>
          )}

          {/* 公告原文摘要/招商信息原文：报纸公告显示摘要；AMC 公告全文已在上方段落化展示（不重复，卡整体隐藏） */}
          {(!isNotice || detail.summary_text || detail.paper_body || detail.raw_text) && (
          <Card title={isNotice ? '公告原文摘要' : '招商信息原文'} style={{ marginBottom: 16 }}>
            {isNotice && (detail.summary_text || detail.paper_body) && (
              <Paragraph style={{ fontSize: 13, lineHeight: 2, color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>
                {detail.summary_text || detail.paper_body}
              </Paragraph>
            )}
            {detail.raw_text && (
              <div style={{ fontSize: 13, lineHeight: 2, color: 'var(--text-main)' }}>
                {detail.raw_text.split(/\n{2,}/).map((para, i) => (
                  <Paragraph key={i} style={{ marginBottom: 12, whiteSpace: 'pre-wrap', textIndent: 0 }}>
                    {para.split('\n').map((ln, j) => (
                      <span key={j} style={{ display: ln.trim() ? 'block' : 'none' }}>{ln || '\u00A0'}</span>
                    ))}
                  </Paragraph>
                ))}
              </div>
            )}
            {/* 自建表格：从原文表格解析，可读且与原文一致（2026-09-02 修复：竖排键值表
                此前被当横表渲染只显示键、值全丢；现按形态区分——键值表用键值对展示，
                横表保持 AntD Table） */}
            {detail.announce_table && detail.announce_table.headers && (
              <div style={{ marginTop: 8, marginBottom: 8 }}>
                {(() => {
                  const at = detail.announce_table
                  const headers = at.headers || []
                  const rows = at.rows || []
                  // 键值表判定：表头非空列 ≤1 且存在"键→值"行（首列是键、次列是值）
                  const nonEmptyHeaders = headers.filter((h) => h && String(h).trim())
                  const isKv = nonEmptyHeaders.length <= 1 && rows.some((r) => {
                    const k = String(r[0] || '').trim()
                    const v = String(r[1] || '').trim()
                    return k && v && !/^[\d,\.]+(元|万|万元|亿|亿元)?$/.test(k)
                  })
                  if (!isKv) {
                    return (
                      <Table
                        size="small"
                        bordered
                        pagination={false}
                        rowKey={(_, i) => i}
                        scroll={{ x: 'max-content' }}
                        columns={headers.map((h, i) => ({
                          title: h || `列${i + 1}`,
                          dataIndex: `c${i}`,
                          key: `c${i}`,
                          width: /金额|本金|利息|罚息|费用|小计|余额/.test(h) ? 120 : 160,
                          render: (v) => <span style={{ fontSize: 12 }}>{v || ''}</span>,
                        }))}
                        dataSource={rows.map((r) => {
                          const obj = {}
                          headers.forEach((_, i) => { obj[`c${i}`] = r[i] || '' })
                          return obj
                        })}
                      />
                    )
                  }
                  // 键值表渲染：2列行[键,值] / 3列行[组名,键,值] / 长文本段落
                  return (
                    <div style={{ border: '1px solid #f0f0f0', borderRadius: 6 }}>
                      {rows.map((r, i) => {
                        const cells = (r || []).map((c) => String(c || '').trim())
                        if (cells.length === 1 && cells[0].length > 40) {
                          return <div key={i} style={{ padding: '8px 12px', fontSize: 12, lineHeight: 1.7, borderBottom: '1px solid #f5f5f5', color: '#595959' }}>{cells[0]}</div>
                        }
                        if (cells.length >= 3 && cells[0] && cells[1] && cells[2]) {
                          // 组名 + 键 + 值（如 债权基本情况 / 贷款发放金额 / 10000000.00 元）
                          return (
                            <div key={i} style={{ padding: '8px 12px', borderBottom: '1px solid #f5f5f5' }}>
                              <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 4 }}>{cells[0]}</div>
                              <div style={{ fontSize: 12 }}>
                                <span style={{ color: '#262626', fontWeight: 500, marginRight: 8 }}>{cells[1]}</span>
                                <span style={{ color: '#595959', wordBreak: 'break-all' }}>{cells[2]}</span>
                              </div>
                            </div>
                          )
                        }
                        if (cells.length >= 2 && cells[0]) {
                          return (
                            <div key={i} style={{ padding: '8px 12px', borderBottom: '1px solid #f5f5f5', fontSize: 12, display: 'flex', gap: 8 }}>
                              <span style={{ color: '#262626', fontWeight: 500, flexShrink: 0, minWidth: 110 }}>{cells[0]}</span>
                              <span style={{ color: '#595959', wordBreak: 'break-all', flex: 1 }}>{cells[1] || '—'}</span>
                            </div>
                          )
                        }
                        return <div key={i} style={{ padding: '8px 12px', fontSize: 12, color: '#595959', borderBottom: '1px solid #f5f5f5' }}>{cells[0] || ''}</div>
                      })}
                    </div>
                  )
                })()}
              </div>
            )}
            {!detail.raw_text && <Paragraph>{item.summary || '暂无简介'}</Paragraph>}
            {detail.sections && Object.entries(detail.sections).map(([k, v]) => (
              <div key={k} style={{ marginBottom: 12 }}>
                <Text strong>{k}</Text>
                <Paragraph style={{ marginBottom: 0 }}>{typeof v === 'string' ? v : JSON.stringify(v)}</Paragraph>
              </div>
            ))}
            {/* 2026-09-02：公告(notice)不显示此按钮——source_url 是智收云(竞对)，公告跳转用溯源原文链接 */}
            {!isNotice && item.source_url && (
              <Button type="link" onClick={() => window.open(item.source_url, '_blank')}>查看原始公告 →</Button>
            )}
          </Card>
          )}

          {/* 2026-09-02：公告原文链接+提示放详情页最底部（不跳智收云，只跳溯源原文） */}
          {isNotice && (
            <Card style={{ marginBottom: 16 }}>
              <Alert type="info" showIcon style={{ marginBottom: 12 }} message="完整公告（含债务人明细表格）详见原公告，可点击下方链接查看。" />
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {(detail.paper_url || item.source_url) && <Button type="primary" href={detail.paper_url || item.source_url} target="_blank">查看原公告（报纸官网/AMC官网）→</Button>}
              </div>
            </Card>
          )}
        </Col>

        {/* 右栏：按类型区分（精选=可尽调；捡漏=仅信息+推荐）*/}
        <Col xs={24} lg={9}>
          {/* 快速信息 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>快速信息</div>
            <Descriptions column={1} size="small">
              <Descriptions.Item label={isBargain ? '来源' : '债权转让方'}>
                {isBargain ? (item.source || '—') : (detail.transferor || item.source || '—')}
              </Descriptions.Item>
              {!isBargain && detail.auction_status && (
                <Descriptions.Item label="状态">
                  <Tag color={detail.auction_status === '进行中' ? 'orange' : 'blue'}>{detail.auction_status}</Tag>
                </Descriptions.Item>
              )}
              {!isBargain && (detail.debtor_name || detail.claim_total || detail.listing_price) && (
                <Descriptions.Item label="起拍价">
                  <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--danger)' }}>
                    {detail.listing_price || '—'}
                  </span>
                  {detail.listing_price && <span style={{ fontSize: 11, color: 'var(--text-weak)', marginLeft: 6 }}>起拍</span>}
                </Descriptions.Item>
              )}
              <Descriptions.Item label="折扣率">{detail.discount || detail.discount_rate || '—'}</Descriptions.Item>
              {isBargain && detail.claim_total && <Descriptions.Item label="本金">{detail.claim_total}</Descriptions.Item>}
            </Descriptions>
          </Card>

          {isBargain ? (
            <>
              {/* 捡漏风险提示（不提供尽调）*/}
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message="捡漏标的提示"
                description="捡漏类债权/资产价格极低，但通常存在诉讼时效、债权有效性、抵押物占用等重大风险，且信息有限，平台不提供尽调评估。请自行核实或咨询专业机构后谨慎决策。"
              />

              {/* 注意事项 */}
              {detail.cautions && (
                <Card size="small" style={{ marginBottom: 16, borderColor: '#faad14' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}><WarningOutlined style={{ color: '#faad14', marginRight: 6 }} />注意事项</div>
                  <Text style={{ fontSize: 12 }}>{detail.cautions}</Text>
                </Card>
              )}

              {/* 处置建议 */}
              {detail.disposal_advice && (
                <Card size="small" style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}><SolutionOutlined style={{ color: 'var(--success)', marginRight: 6 }} />处置建议</div>
                  <Text style={{ fontSize: 12 }}>{detail.disposal_advice}</Text>
                </Card>
              )}

              {/* 相关捡漏推荐 */}
              {related.length > 0 && (
                <Card size="small" title={<Space><FireOutlined style={{ color: '#fa541c' }} />更多捡漏标的</Space>}>
                  {related.map((r) => {
                    const rd = r.detail || {}
                    return (
                      <div key={r.id} style={{ padding: '8px 0', borderBottom: '1px dashed var(--border-light)', cursor: 'pointer' }}
                        onClick={() => navigate(`/asset/${r.id}`)}>
                        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{r.title}</div>
                        <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                          {rd.claim_total && <span>本金 {rd.claim_total}</span>}
                          {rd.listing_price && <span style={{ marginLeft: 8 }}>挂牌 <Text strong style={{ color: 'var(--danger)' }}>{rd.listing_price}</Text></span>}
                        </div>
                      </div>
                    )
                  })}
                </Card>
              )}
            </>
          ) : isNotice ? (
            <>
              {/* 债权公告（智收云索引）：不提供一键尽调（公告为多户汇总，尽调需逐户录入） */}
              <Card size="small" style={{ marginBottom: 16 }} title={<Space><FileTextOutlined style={{ color: 'var(--primary)' }} />公告说明</Space>}>
                <Text style={{ fontSize: 12, lineHeight: 1.8 }}>
                  本页为报纸债权公告索引信息。如需对其中某户债权尽调，可将债务人信息录入「智能尽调」，或用「财产线索」查询债务人财产；完整公告（含债务人明细）请查看原公告链接。
                </Text>
              </Card>
              {detail.paper && (
                <Card size="small" title="来源信息">
                  <div style={{ fontSize: 13, lineHeight: 2 }}>
                    <div>报纸：<Text strong>{detail.paper}</Text></div>
                    <div>公告日期：{detail.notice_date || '—'}</div>
                    <div>公告类型：{detail.notice_type || '—'}</div>
                  </div>
                </Card>
              )}
            </>
          ) : (
            <>
              {/* 精选债权：尽调评估 + 一键尽调 */}
              <Card size="small" style={{ marginBottom: 16 }} title={<Space><FundOutlined style={{ color: 'var(--primary)' }} />尽调评估摘要</Space>}>
                <Row gutter={[8, 8]}>
                  <Col span={8}><div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: 'var(--text-weak)' }}>保守</div><div style={{ fontSize: 15, fontWeight: 600 }}>{detail.valuation?.conservative || '—'}</div></div></Col>
                  <Col span={8}><div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: 'var(--text-weak)' }}>中性</div><div style={{ fontSize: 15, fontWeight: 600, color: 'var(--primary)' }}>{detail.valuation?.neutral || '—'}</div></div></Col>
                  <Col span={8}><div style={{ textAlign: 'center' }}><div style={{ fontSize: 11, color: 'var(--text-weak)' }}>乐观</div><div style={{ fontSize: 15, fontWeight: 600, color: 'var(--success)' }}>{detail.valuation?.optimistic || '—'}</div></div></Col>
                </Row>
                {detail.recovery_cycle && (
                  <div style={{ marginTop: 10, fontSize: 13 }}>回收周期估算：<Text strong>{detail.recovery_cycle}</Text></div>
                )}
              </Card>

              {detail.cautions && (
                <Card size="small" style={{ marginBottom: 16, borderColor: '#faad14' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}><WarningOutlined style={{ color: '#faad14', marginRight: 6 }} />注意事项</div>
                  <Text style={{ fontSize: 12 }}>{detail.cautions}</Text>
                </Card>
              )}

              {detail.disposal_advice && (
                <Card size="small" style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}><SolutionOutlined style={{ color: 'var(--success)', marginRight: 6 }} />处置建议</div>
                  <Text style={{ fontSize: 12 }}>{detail.disposal_advice}</Text>
                </Card>
              )}

              {/* 可尽调判定（用户规则 2026-08-31 + 2026-09-02 细化）：债务人+债权金额+抵押物合格(房产类+描述具体) 三者齐备才可尽调；
                  资产包（2026-09-02 用户确认）：包内任意一条满足条件即可发起，预处理页让用户勾选具体户 */}
              {(() => {
                const canDD = isPackage
                  ? packageRows.some((r) => canDueDiligence(r))
                  : canDueDiligence(detail)
                return (
                  <>
                    <Button type="primary" size="large" block icon={<FundOutlined />} loading={extracting}
                      disabled={!canDD} onClick={startDD} style={{ marginBottom: 8 }}>
                      一键尽调分析
                    </Button>
                    {!canDD && (
                      <Alert type="warning" showIcon message="该债权信息不全，暂无法尽调" style={{ fontSize: 12, marginBottom: 8 }}
                        description="缺少债务人名称 / 债权金额 / 抵押物等基本信息，请先补充完整后再发起尽调。" />
                    )}
                    {canDD && isPackage && (
                      <Alert type="info" showIcon message="资产包债权：将按表格拆分为多条记录，可在下一步勾选要尽调的户" style={{ fontSize: 12, marginBottom: 8 }} />
                    )}
                  </>
                )
              })()}
              <Alert type="info" showIcon message="尽调流程" style={{ fontSize: 12 }}
                description="系统将提取债权要素 → 查询债务人工商/司法/抵押数据 → 生成九版块尽调报告（含估值与处置建议）。" />
            </>
          )}
        </Col>
      </Row>

      {/* 登录弹窗：未登录下载附件时弹出，登录后留在原页自动继续下载 */}
      <LoginModal open={loginOpen} onClose={() => { setLoginOpen(false); setPendingAtt(null) }} onSuccess={onLoginSuccess} />
    </div>
  )
}
