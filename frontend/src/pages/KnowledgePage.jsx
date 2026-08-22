import { useState, useEffect } from 'react'
import { Card, Tabs, Table, Button, Modal, Form, Input, Select, Upload, Tag, Space, message, Popconfirm, Alert, Typography } from 'antd'
import { UploadOutlined, PlusOutlined, FileTextOutlined, BookOutlined } from '@ant-design/icons'
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

  const loadDocs = async () => {
    setDocsLoading(true)
    try {
      const resp = await knowledgeApi.listLegalDocs()
      setDocs(resp.data?.docs || [])
    } catch (e) {
      message.error(e.message || '加载规范性文件失败')
    } finally {
      setDocsLoading(false)
    }
  }
  const loadCases = async () => {
    setCasesLoading(true)
    try {
      const resp = await knowledgeApi.listCases()
      setCases(resp.data?.cases || [])
    } catch (e) {
      message.error(e.message || '加载案例失败')
    } finally {
      setCasesLoading(false)
    }
  }
  useEffect(() => { loadDocs(); loadCases() }, [])

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
      loadDocs()
    } catch (e) {
      message.error(e.message || '保存失败')
    }
  }
  const delDoc = async (id) => {
    try { await knowledgeApi.deleteLegalDoc(id); message.success('已删除'); loadDocs() }
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
      loadCases()
    } catch (e) {
      message.error(e.message || '保存失败')
    }
  }
  const delCase = async (id) => {
    try { await knowledgeApi.deleteCase(id); message.success('已删除'); loadCases() }
    catch (e) { message.error(e.message || '删除失败') }
  }

  // ---- 文件上传 ----
  const uploadProps = (kind) => ({
    accept: '.doc,.docx,.pdf,.txt,.md,.jpg,.jpeg,.png,.webp,.bmp',
    showUploadList: false,
    beforeUpload: async (file) => {
      if (kind === 'doc') {
        try { await knowledgeApi.uploadLegalDoc(file); message.success('法规文件已上传，请核对补全元信息'); loadDocs() }
        catch (e) { message.error(e.message || '上传失败') }
      } else {
        try { await knowledgeApi.uploadCase(file); message.success('案例文档已上传，请补全场景标签与关键词'); loadCases() }
        catch (e) { message.error(e.message || '上传失败') }
      }
      return false
    },
  })

  const docColumns = [
    { title: '文件名称', dataIndex: 'title', width: 260, render: (v, r) => (
      <Space>
        <FileTextOutlined style={{ color: 'var(--primary)' }} />
        <span>{v}</span>
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
        <Button size="small" onClick={() => openDocModal(r)}>编辑</Button>
        <Popconfirm title="确认删除？" onConfirm={() => delDoc(r.id)}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  const caseColumns = [
    { title: '案例标题', dataIndex: 'title', width: 240 },
    { title: '场景', dataIndex: 'scenario', width: 110, render: (v) => v ? <Tag color="blue">{v}</Tag> : '—' },
    { title: '关键词', dataIndex: 'keywords', width: 200, ellipsis: true },
    { title: '摘要', dataIndex: 'summary', ellipsis: true },
    { title: '操作', width: 120, render: (_, r) => (
      <Space>
        <Button size="small" onClick={() => openCaseModal(r)}>编辑</Button>
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

      <Tabs
        items={[
          {
            key: 'docs',
            label: <span><FileTextOutlined /> 规范性文件（{docs.length}）</span>,
            children: (
              <>
                <Space style={{ marginBottom: 12 }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => openDocModal(null)}>新增规范性文件</Button>
                  <Upload {...uploadProps('doc')}>
                    <Button icon={<UploadOutlined />}>上传法规原文（Word/PDF/TXT/图片）</Button>
                  </Upload>
                </Space>
                <Alert type="info" showIcon style={{ marginBottom: 12 }}
                  message="效力状态为『需复核』或『已废止』的文件会在报告引用时排除/提示；请在法规修订时人工更新版本信息。" />
                <Table rowKey="id" size="small" loading={docsLoading} columns={docColumns} dataSource={docs}
                  pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
              </>
            ),
          },
          {
            key: 'cases',
            label: <span><BookOutlined /> 典型案例（{cases.length}）</span>,
            children: (
              <>
                <Space style={{ marginBottom: 12 }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => openCaseModal(null)}>新增案例</Button>
                  <Upload {...uploadProps('case')}>
                    <Button icon={<UploadOutlined />}>上传案例文档（Word/PDF/TXT/图片）</Button>
                  </Upload>
                </Space>
                <Alert type="info" showIcon style={{ marginBottom: 12 }}
                  message="场景标签（如 抵押物占用 / 债务人生病 / 终本 / 拒执 / 一人公司）与关键词用于尽调报告自动匹配提醒，请务必填写。" />
                <Table rowKey="id" size="small" loading={casesLoading} columns={caseColumns} dataSource={cases}
                  pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
              </>
            ),
          },
        ]}
      />

      {/* 规范性文件编辑弹窗 */}
      <Modal title={docModal?.id ? '编辑规范性文件' : '新增规范性文件'} open={docModal != null}
        onCancel={() => setDocModal(null)} onOk={saveDoc} width={640}>
        <Form form={docForm} layout="vertical">
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
