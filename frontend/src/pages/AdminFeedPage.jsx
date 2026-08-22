import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Typography, Spin, Modal, Form, Input, Select, Space, Popconfirm, message, Alert } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import client from '../api/client'
import { useAuthStore } from '../store/auth'

const { Title } = Typography

const SECTIONS = [
  { value: 'featured', label: '精选债权' },
  { value: 'bargain', label: '捡漏' },
  { value: 'asset_revive', label: '存量资产盘活' },
  { value: 'amc', label: 'AMC专区' },
  { value: 'auction', label: '拍卖平台' },
  { value: 'notice', label: '公告' },
]
const EDITOR_SECTIONS = SECTIONS.filter((s) => ['featured', 'bargain'].includes(s.value))

export default function AdminFeedPage() {
  const user = useAuthStore((s) => s.user)
  const isEditor = user?.role === 'editor'
  const sectionOptions = isEditor ? EDITOR_SECTIONS : SECTIONS
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()

  const load = async () => {
    try {
      const resp = await client.get('/feed?page_size=100')
      setItems(resp.data?.items || [])
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setEditOpen(true)
  }

  const openEdit = (record) => {
    setEditing(record)
    form.setFieldsValue({
      section: record.section,
      title: record.title,
      summary: record.summary,
      tags: record.tags || [],
      source: record.source,
      source_url: record.source_url,
      detail_json: record.detail ? JSON.stringify(record.detail, null, 2) : '',
    })
    setEditOpen(true)
  }

  const save = async () => {
    const values = await form.validateFields()
    let detailJson = null
    if (values.detail_json && values.detail_json.trim()) {
      try {
        detailJson = JSON.parse(values.detail_json)
      } catch {
        message.error('详情字段 JSON 格式错误，请检查')
        return
      }
    }
    const payload = { ...values, detail_json: detailJson }
    try {
      if (editing) {
        await client.put(`/admin/feed/${editing.id}`, payload)
        message.success('已更新')
      } else {
        await client.post('/admin/feed', payload)
        message.success('已发布')
      }
      setEditOpen(false)
      load()
    } catch { /* 拦截器已提示 */ }
  }

  const remove = async (id) => {
    try {
      await client.delete(`/admin/feed/${id}`)
      message.success('已下架')
      load()
    } catch { /* 拦截器已提示 */ }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '栏目', dataIndex: 'section', width: 130,
      render: (v) => <Tag color="blue">{SECTIONS.find((s) => s.value === v)?.label || v}</Tag>,
    },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '标签', dataIndex: 'tags', width: 200,
      render: (tags) => (Array.isArray(tags) ? tags.map((t, i) => <Tag key={i}>{t}</Tag>) : '—'),
    },
    { title: '来源', dataIndex: 'source', width: 120 },
    {
      title: '操作', width: 140,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确认下架该内容？" onConfirm={() => remove(record.id)}>
            <Button size="small" danger>下架</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>栏目内容管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增内容</Button>
      </div>
      {isEditor && (
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="您的权限范围：仅可维护「精选债权」「热门捡漏」栏目；其余栏目为自动抓取数据不可编辑。" />
      )}
      <Card>
        {loading ? <Spin /> : (
          <Table rowKey="id" columns={columns} dataSource={items} pagination={{ pageSize: 10 }} />
        )}
      </Card>

      <Modal
        title={editing ? '编辑内容' : '新增内容'}
        open={editOpen}
        onOk={save}
        onCancel={() => setEditOpen(false)}
        okText="保存"
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="section" label="栏目" rules={[{ required: true, message: '请选择栏目' }]}>
            <Select options={sectionOptions} disabled={isEditor && editing?.section && !['featured', 'bargain'].includes(editing.section)} />
          </Form.Item>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="summary" label="简介（2行）">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="tags" label="标签（债权总额/担保方式等）">
            <Select mode="tags" placeholder="输入后回车添加" />
          </Form.Item>
          <Form.Item name="source" label="来源（北交所/淘宝/手工录入）">
            <Input />
          </Form.Item>
          <Form.Item name="source_url" label="原文链接">
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item
            name="detail_json"
            label="详情字段（JSON，可填案号/本息/估值/处置建议等，用于债权详情页）"
            tooltip='示例：{"case_no":"（2023）沪0115民初5678号","claim_total":"3200万","valuation":{"conservative":"960万","neutral":"1760万","optimistic":"2560万"},"cautions":"注意事项","disposal_advice":"处置建议"}'
          >
            <Input.TextArea rows={8} style={{ fontFamily: 'monospace', fontSize: 12 }} placeholder='{"case_no": "", "claim_total": "", "valuation": {}, "cautions": "", "disposal_advice": ""}' />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
