import { useState, useEffect } from 'react'
import { Card, Tabs, Table, Button, Modal, Form, Input, Select, Upload, Tag, Space, message, Popconfirm, Alert, Typography } from 'antd'
import { UploadOutlined, PlusOutlined, FileTextOutlined, DiffOutlined } from '@ant-design/icons'
import { knowledgeApi } from '../api'

const { Text } = Typography

const STATUS_COLORS = { '现行有效': 'green', '已修改': 'orange', '已废止': 'red', '需复核': 'volcano' }

export default function KnowledgePage() {
  const [docs, setDocs] = useState([])
  const [cases, setCases] = useState([])
  const [docsLoading, setDocsLoading] = useState(false)
  const [casesLoading, setCasesLoading] = useState(false)
  const [docModal, setDocModal] = useState(null) // { record? }
  const [caseModal, setCaseModal] = useState(null)
  const [docForm] = Form.useForm()
  const [caseForm] = Form.useForm()
  // 分类（平铺展示，点击切换；含条目数与类型）
  const [allCategories, setAllCategories] = useState([]) // [{name, count, kind: 'legal'|'case'}]
  const [activeCat, setActiveCat] = useState(null) // 当前选中分类 {name, kind}
  // 统一粘贴录入框
  const [pasteText, setPasteText] = useState('')
  const [pasteCat, setPasteCat] = useState('') // 自动识别出的分类（可手动改）
  const [pasting, setPasting] = useState(false)

  const loadDocs = async (cat) => {
    setDocsLoading(true)
    try {
      const resp = await knowledgeApi.listLegalDocs(cat || undefined)
      setDocs(resp.data?.docs || [])
    } catch (e) {
      message.error(e.message || '加载规范性文件失败')
    } finally {
      setDocsLoading(false)
    }
  }
  const loadCases = async (cat) => {
    setCasesLoading(true)
    try {
      const resp = await knowledgeApi.listCases(cat || undefined)
      setCases(resp.data?.cases || [])
    } catch (e) {
      message.error(e.message || '加载案例失败')
    } finally {
      setCasesLoading(false)
    }
  }
  const loadCategories = async () => {
    try {
      const resp = await knowledgeApi.categories()
      const legal = (resp.data?.legal_categories || []).map((c) => (typeof c === 'string' ? { name: c, count: 0, kind: 'legal' } : { name: c.name, count: c.count || 0, kind: 'legal' }))
      const cases = (resp.data?.case_categories || []).map((c) => (typeof c === 'string' ? { name: c, count: 0, kind: 'case' } : { name: c.name, count: c.count || 0, kind: 'case' }))
      setAllCategories([...legal, ...cases])
      // 默认选中第一个分类
      setActiveCat((prev) => prev || (legal.length ? legal[0] : cases[0] || null))
    } catch { /* 忽略 */ }
  }
  // 切换分类：加载该分类条目
  useEffect(() => {
    if (!activeCat) return
    if (activeCat.kind === 'case') loadCases(activeCat.name)
    else loadDocs(activeCat.name)
    loadCategories() // 刷新各分类计数
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCat?.name, activeCat?.kind])
  useEffect(() => { loadCategories() }, [])

  // 删除分类（仅空分类）
  const delCat = async (name) => {
    try {
      const resp = await knowledgeApi.deleteCategory(name)
      message.success(resp.message || '已删除')
      setActiveCat(null)
      loadCategories()
    } catch (e) {
      message.error(e.message || e.response?.data?.detail || '删除失败（分类下可能还有条目）')
    }
  }

  // ---- 统一粘贴录入（自动分类）----
  const onPasteClassify = async () => {
    if (!pasteText.trim()) return
    const isCase = activeCat?.kind === 'case'
    try {
      const resp = await knowledgeApi.classify(pasteText, isCase)
      setPasteCat(resp.data?.category || '其他')
      message.success(`已自动识别分类：${resp.data?.category || '其他'}（可手动修改）`)
    } catch (e) {
      message.error(e.message || '识别失败')
    }
  }
  const onPasteSubmit = async () => {
    const isCase = activeCat?.kind === 'case'
    const targetCat = pasteCat || activeCat?.name
    if (!pasteText.trim() || !targetCat) {
      return message.warning('请先粘贴内容并确认分类')
    }
    setPasting(true)
    try {
      if (isCase) {
        await knowledgeApi.createCase({
          category: targetCat, title: (pasteText.split('\n')[0] || '新知识').slice(0, 80),
          scenario: '', keywords: '', summary: pasteText.slice(0, 6000), source: '粘贴录入',
        })
        message.success(`已录入到「${targetCat}」`)
      } else {
        await knowledgeApi.createLegalDoc({
          category: targetCat, title: (pasteText.split('\n')[0] || '新知识').slice(0, 80),
          status: '需复核', keywords: '', summary: pasteText.slice(0, 4000), note: '由粘贴内容录入，请核对完善元信息',
        })
        message.success(`已录入到「${targetCat}」`)
      }
      setPasteText(''); setPasteCat('')
      if (isCase) loadCases(targetCat); else loadDocs(targetCat)
      loadCategories()
    } catch (e) {
      message.error(e.message || '录入失败')
    } finally {
      setPasting(false)
    }
  }

  // ---- 规范性文件 CRUD ----
  const openDocModal = (record) => {
    setDocModal(record || {})
    docForm.setFieldsValue(record || { status: '现行有效' })
  }
  const saveDoc = async () => {
    const v = await docForm.validateFields()
    try {
      if (docModal?.id) {
        await knowledgeApi.updateLegalDoc(docModal.id, v)
        message.success('已更新')
      } else {
        await knowledgeApi.createLegalDoc(v)
        message.success('已添加')
      }
      setDocModal(null)
      if (activeCat?.kind === 'case') loadCases(activeCat.name); else loadDocs(activeCat?.name)
      loadCategories()
    } catch (e) {
      message.error(e.message || '保存失败')
    }
  }
  const delDoc = async (id) => {
    try { await knowledgeApi.deleteLegalDoc(id); message.success('已删除'); if (activeCat?.kind === 'case') loadCases(activeCat.name); else loadDocs(activeCat?.name); loadCategories() }
    catch (e) { message.error(e.message || '删除失败') }
  }

  // ---- 案例 CRUD ----
  const openCaseModal = (record) => {
    setCaseModal(record || {})
    caseForm.setFieldsValue(record || {})
  }
  const saveCase = async () => {
    const v = await caseForm.validateFields()
    try {
      if (caseModal?.id) {
        await knowledgeApi.updateCase(caseModal.id, v)
        message.success('已更新')
      } else {
        await knowledgeApi.createCase(v)
        message.success('已添加')
      }
      setCaseModal(null)
      if (activeCat?.kind === 'case') loadCases(activeCat.name); else loadDocs(activeCat?.name)
      loadCategories()
    } catch (e) {
      message.error(e.message || '保存失败')
    }
  }
  const delCase = async (id) => {
    try { await knowledgeApi.deleteCase(id); message.success('已删除'); if (activeCat?.kind === 'case') loadCases(activeCat.name); else loadDocs(activeCat?.name); loadCategories() }
    catch (e) { message.error(e.message || '删除失败') }
  }

  // ---- 文件上传 ----
  const uploadProps = (kind) => ({
    accept: '.doc,.docx,.pdf,.txt,.md,.jpg,.jpeg,.png,.webp,.bmp',
    showUploadList: false,
    beforeUpload: async (file) => {
      const reloadActive = () => {
        if (activeCat?.kind === 'case') loadCases(activeCat.name); else loadDocs(activeCat?.name)
        loadCategories()
      }
      if (kind === 'doc' || activeCat?.kind !== 'case') {
        try { await knowledgeApi.uploadLegalDoc(file); message.success('法规文件已上传，请核对补全元信息'); reloadActive() }
        catch (e) { message.error(e.message || '上传失败') }
      } else {
        try { await knowledgeApi.uploadCase(file); message.success('案例文档已上传，请补全场景标签与关键词'); reloadActive() }
        catch (e) { message.error(e.message || '上传失败') }
      }
      return false
    },
  })

  const docColumns = [
    { title: '分类', dataIndex: 'category', width: 100, render: (v) => v ? <Tag color="geekblue">{v}</Tag> : '—' },
    { title: '文件名称', dataIndex: 'title', width: 260, render: (v, r) => (
      <Space>
        <FileTextOutlined style={{ color: 'var(--primary)' }} />
        <span>{v}</span>
        {r.source_type === 'upload' && <Tag color="orange">文档</Tag>}
        {r.status === '已废止' && <Tag color="red">已废止</Tag>}
        {r.status === '需复核' && <Tag color="volcano">需复核</Tag>}
      </Space>
    ) },
    { title: '文号', dataIndex: 'doc_no', width: 130 },
    { title: '发布机关', dataIndex: 'issuer', width: 160 },
    { title: '施行日期', dataIndex: 'effect_date', width: 130 },
    { title: '效力状态', dataIndex: 'status', width: 90, render: (v) => <Tag color={STATUS_COLORS[v] || 'default'}>{v}</Tag> },
    { title: '标签/关键词', dataIndex: 'keywords', ellipsis: true },
    { title: '操作', width: 120, render: (_, r) => (
      <Space>
        <Button size="small" disabled={r.source_type === 'upload'} onClick={() => openDocModal(r)}>编辑</Button>
        <Popconfirm title="确认删除？" onConfirm={() => delDoc(r.id)}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  const caseColumns = [
    { title: '分类', dataIndex: 'category', width: 100, render: (v) => v ? <Tag color="geekblue">{v}</Tag> : '—' },
    { title: '案例标题', dataIndex: 'title', width: 240, render: (v, r) => (
      <Space>
        <span>{v}</span>
        {r.source_type === 'upload' && <Tag color="orange">文档</Tag>}
      </Space>
    ) },
    { title: '场景', dataIndex: 'scenario', width: 110, render: (v) => v ? <Tag color="blue">{v}</Tag> : '—' },
    { title: '关键词', dataIndex: 'keywords', width: 200, ellipsis: true },
    { title: '摘要', dataIndex: 'summary', ellipsis: true },
    { title: '操作', width: 120, render: (_, r) => (
      <Space>
        <Button size="small" disabled={r.source_type === 'upload'} onClick={() => openCaseModal(r)}>编辑</Button>
        <Popconfirm title="确认删除？" onConfirm={() => delCase(r.id)}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: 24 }}>
      <h2 style={{ marginBottom: 4 }}>知识库</h2>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        规范性文件用于规范报告用词与法条引用（效力状态人工维护，已废止/需复核文件请及时更新）；
        案例按场景关键词与尽调数据自动匹配，报告生成时附风险提醒。
      </Text>

      {/* 统一粘贴录入框：自动识别分类（作用于当前分类） */}
      <Card size="small" style={{ marginBottom: 16, borderColor: '#b7eb8f' }}>
        <Space style={{ marginBottom: 8 }} wrap>
          <Text strong><DiffOutlined /> 粘贴录入知识</Text>
          <Button size="small" onClick={onPasteClassify}>自动识别分类</Button>
        </Space>
        <Input.TextArea rows={3} placeholder="粘贴法规/行业知识/案例内容，系统自动识别放入对应分类…"
          value={pasteText} onChange={(e) => setPasteText(e.target.value)} />
        <Space style={{ marginTop: 8 }} wrap>
          <Select style={{ width: 200 }} placeholder="确认分类（自动识别后可改，默认当前分类）"
            value={pasteCat || activeCat?.name} onChange={setPasteCat}
            options={allCategories.map((c) => ({ value: c.name, label: `${c.name}（${c.kind === 'case' ? '案例' : '法规/常识'}）` }))} />
          <Button type="primary" loading={pasting} onClick={onPasteSubmit}>录入知识</Button>
          <Text type="secondary" style={{ fontSize: 12 }}>文字录入的条目可编辑；文档上传的条目只读（仅可删除）</Text>
        </Space>
      </Card>

      {/* 分类平铺：点击切换，点哪个分类对哪个分类操作 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          {allCategories.map((c) => (
            <Button
              key={`${c.kind}-${c.name}`}
              size="middle"
              type={activeCat?.name === c.name && activeCat?.kind === c.kind ? 'primary' : 'default'}
              onClick={() => setActiveCat({ name: c.name, kind: c.kind })}
              style={{ height: 'auto', padding: '6px 12px' }}
            >
              {c.name} <Tag style={{ marginLeft: 4 }} color={c.kind === 'case' ? 'purple' : 'blue'}>{c.count}</Tag>
            </Button>
          ))}
          {allCategories.length === 0 && <Text type="secondary">暂无分类</Text>}
        </Space>
      </Card>

      {/* 当前分类内容区 */}
      {activeCat ? (
        <Card
          size="small"
          title={<Space><Text strong>{activeCat.name}</Text>
            <Tag color={activeCat.kind === 'case' ? 'purple' : 'blue'}>{activeCat.kind === 'case' ? '典型案例' : '法规/常识'}</Tag></Space>}
          extra={<Popconfirm title={`确认删除空分类「${activeCat.name}」？`} onConfirm={() => delCat(activeCat.name)}>
            <Button size="small" danger disabled={(activeCat.kind === 'case' ? cases.length : docs.length) > 0}>删除该分类</Button>
          </Popconfirm>}
        >
          <Space style={{ marginBottom: 12 }} wrap>
            <Button type="primary" icon={<PlusOutlined />}
              onClick={() => activeCat.kind === 'case' ? openCaseModal(null) : openDocModal(null)}>
              {activeCat.kind === 'case' ? '新增案例' : '新增条目'}
            </Button>
            <Upload {...uploadProps(activeCat.kind === 'case' ? 'case' : 'doc')}>
              <Button icon={<UploadOutlined />}>
                {activeCat.kind === 'case' ? '上传案例文档' : '上传文档（Word/PDF/TXT/图片）'}
              </Button>
            </Upload>
          </Space>
          {activeCat.kind === 'case' ? (
            <>
              <Alert type="info" showIcon style={{ marginBottom: 12 }}
                message="场景标签与关键词用于尽调报告自动匹配提醒，请务必填写。" />
              <Table rowKey="id" size="small" loading={casesLoading} columns={caseColumns} dataSource={cases}
                pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
            </>
          ) : (
            <>
              <Alert type="info" showIcon style={{ marginBottom: 12 }}
                message="效力状态为『需复核』或『已废止』的文件会在报告引用时排除/提示。" />
              <Table rowKey="id" size="small" loading={docsLoading} columns={docColumns} dataSource={docs}
                pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
            </>
          )}
        </Card>
      ) : (
        <Card><Text type="secondary">请选择上方分类进行管理</Text></Card>
      )}

      {/* 规范性文件编辑弹窗 */}
      <Modal title={docModal?.id ? '编辑规范性文件' : '新增规范性文件'} open={docModal != null}
        onCancel={() => setDocModal(null)} onOk={saveDoc} width={640}>
        <Form form={docForm} layout="vertical">
          <Form.Item name="category" label="知识分类" rules={[{ required: true, message: '请选择分类' }]}>
            <Select
              placeholder="选择分类"
              options={allCategories.filter((c) => c.kind === 'legal').map((c) => ({ value: c.name, label: c.name }))}
            />
          </Form.Item>
          <Form.Item name="title" label="文件名称" rules={[{ required: true, message: '请输入文件名称' }]}><Input /></Form.Item>
          <Space.Compact block>
            <Form.Item name="doc_no" label="文号" style={{ width: '48%' }}><Input placeholder="如 法释〔2017〕8号" /></Form.Item>
            <Form.Item name="issuer" label="发布机关" style={{ width: '48%' }}><Input /></Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="effect_date" label="施行日期" style={{ width: '48%' }}><Input placeholder="如 2024-07-01 施行" /></Form.Item>
            <Form.Item name="status" label="效力状态" style={{ width: '48%' }}>
              <Select options={['现行有效', '已修改', '已废止', '需复核'].map((s) => ({ value: s, label: s }))} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="latest_version" label="最新版本/修订说明"><Input placeholder="如 2023-12-29 修订，2024-07-01 施行" /></Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）"><Input placeholder="如 公司法,一人公司,出资加速到期" /></Form.Item>
          <Form.Item name="keywords" label="关键词（逗号分隔，用于报告匹配）"><Input placeholder="如 一人公司,股东,未实缴,人格混同" /></Form.Item>
          <Form.Item name="summary" label="核心条款摘要（报告可直接引用）"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="note" label="备注/复核提示"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 案例编辑弹窗 */}
      <Modal title={caseModal?.id ? '编辑案例' : '新增案例'} open={caseModal != null}
        onCancel={() => setCaseModal(null)} onOk={saveCase} width={640}>
        <Form form={caseForm} layout="vertical">
          <Form.Item name="category" label="知识分类" rules={[{ required: true, message: '请选择分类' }]}>
            <Select
              placeholder="选择分类"
              options={allCategories.filter((c) => c.kind === 'case').map((c) => ({ value: c.name, label: c.name }))}
            />
          </Form.Item>
          <Form.Item name="title" label="案例标题" rules={[{ required: true, message: '请输入案例标题' }]}><Input /></Form.Item>
          <Space.Compact block>
            <Form.Item name="scenario" label="场景标签" style={{ width: '48%' }}>
              <Select mode="tags" placeholder="如 抵押物占用 / 债务人生病 / 终本 / 拒执 / 一人公司 / 应收债权"
                tokenSeparators={[',']} />
            </Form.Item>
            <Form.Item name="keywords" label="关键词（逗号分隔）" style={{ width: '48%' }}><Input /></Form.Item>
          </Space.Compact>
          <Form.Item name="summary" label="案情摘要"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="approach" label="处理思路/法律路径"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="result" label="处理结果"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="source" label="来源"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
