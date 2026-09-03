import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Typography, Spin, Modal, Form, Input, Select, Space, Popconfirm, message, Alert, Checkbox } from 'antd'
import { PlusOutlined, SyncOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore } from '../store/auth'

const { Title } = Typography

const SECTIONS = [
  { value: 'featured', label: '精选债权' },
  { value: 'bargain', label: '捡漏' },
  { value: 'asset_revive', label: '存量资产盘活' },
  { value: 'amc', label: 'AMC专区' },
  { value: 'auction', label: '拍卖平台' },
  { value: 'notice', label: '债权公告' },  // 债权公告 = 业务版块以公告形式展示
]
// 员工（editor）可维护：精选债权 / 捡漏 / 债权公告
const EDITOR_SECTIONS = SECTIONS.filter((s) => ['featured', 'bargain', 'notice'].includes(s.value))

export default function AdminFeedPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isEditor = user?.role === 'editor'
  const hasLandPerm = !isEditor || user?.land_price_perm
  const sectionOptions = isEditor ? EDITOR_SECTIONS : SECTIONS
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  // 当前栏目（点击栏目入口切换；默认第一个可管理栏目）
  const [activeSection, setActiveSection] = useState(null)
  // 平台公告（notices 表，独立于债权公告）
  const [platformNotices, setPlatformNotices] = useState([])
  const [noticeOpen, setNoticeOpen] = useState(false)
  const [noticeEditing, setNoticeEditing] = useState(null)
  const [noticeForm] = Form.useForm()
  const [syncing, setSyncing] = useState(false)
  const [syncingAmc, setSyncingAmc] = useState(false)

  const syncAll = async () => {
    setSyncing(true)
    try {
      const resp = await client.post('/admin/feed/sync-all')
      message.success(resp.data?.message || '同步完成')
      load()
    } catch { /* 拦截器已提示 */ } finally {
      setSyncing(false)
    }
  }

  const syncAmc = async () => {
    setSyncingAmc(true)
    try {
      const resp = await client.post('/admin/feed/sync-amc')
      message.success(resp.data?.message || 'AMC 公告同步完成')
      load()
    } catch { /* 拦截器已提示 */ } finally {
      setSyncingAmc(false)
    }
  }

  const load = async () => {
    try {
      // 管理专用列表：按角色过滤栏目 + 包含已下架记录
      const resp = await client.get('/admin/feed-items')
      setItems(resp.data?.items || [])
      // 默认选中第一个可管理栏目
      setActiveSection((prev) => prev || (isEditor ? EDITOR_SECTIONS : SECTIONS)[0]?.value || null)
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  const loadNotices = async () => {
    try {
      const resp = await client.get('/admin/notices')
      setPlatformNotices(resp.data?.notices || [])
    } catch { /* 拦截器已提示 */ }
  }

  useEffect(() => { load(); loadNotices() }, [])

  const openNoticeCreate = () => {
    setNoticeEditing(null)
    noticeForm.resetFields()
    noticeForm.setFieldsValue({ enabled: true })
    setNoticeOpen(true)
  }
  const openNoticeEdit = (n) => {
    setNoticeEditing(n)
    noticeForm.setFieldsValue({ title: n.title, content: n.content, is_pinned: n.is_pinned, enabled: n.enabled })
    setNoticeOpen(true)
  }
  const saveNotice = async () => {
    const v = await noticeForm.validateFields()
    try {
      if (noticeEditing?.id) {
        await client.put(`/admin/notices/${noticeEditing.id}`, v)
        message.success('平台公告已更新')
      } else {
        await client.post('/admin/notices', v)
        message.success('平台公告已发布')
      }
      setNoticeOpen(false)
      loadNotices()
    } catch (e) { message.error(e.message || '保存失败') }
  }
  const delNotice = async (id) => {
    try { await client.delete(`/admin/notices/${id}`); message.success('已删除'); loadNotices() }
    catch (e) { message.error(e.message || '删除失败') }
  }

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ section: activeSection }) // 默认归入当前栏目
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

  // 下架/上架切换
  const toggleItem = async (record) => {
    try {
      const resp = await client.post(`/admin/feed/${record.id}/toggle`)
      message.success(resp.data?.message || (record.is_active === 1 ? '已下架' : '已上架'))
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
      title: '状态', dataIndex: 'is_active', width: 90,
      render: (v) => (v === 1 ? <Tag color="success">已上架</Tag> : <Tag color="default">已下架</Tag>),
    },
    {
      title: '操作', width: 140,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title={record.is_active === 1 ? '确认下架该内容？（后台仍保留，可重新上架）' : '确认重新上架？'} onConfirm={() => toggleItem(record)}>
            <Button size="small" danger={record.is_active === 1}>{record.is_active === 1 ? '下架' : '上架'}</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>栏目内容管理</Title>
      </div>
      {isEditor && (
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="您的权限范围：可维护「精选债权」「热门捡漏」「债权公告」栏目与「平台公告」；下架内容在后台仍保留，可重新上架。" />
      )}

      {/* 栏目入口平铺：一眼看到所有可管理栏目，点击进入该栏目列表 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          {(isEditor ? EDITOR_SECTIONS : SECTIONS).map((s) => {
            const count = items.filter((i) => i.section === s.value).length
            const active = activeSection === s.value
            return (
              <Button
                key={s.value}
                size="large"
                type={active ? 'primary' : 'default'}
                onClick={() => setActiveSection(s.value)}
                style={{ height: 'auto', padding: '10px 18px' }}
              >
                {s.label} <Tag style={{ marginLeft: 6 }} color={active ? 'green' : 'blue'}>{count}</Tag>
              </Button>
            )
          })}
          <Button size="large" loading={syncing} onClick={syncAll} icon={<SyncOutlined />}>
            同步债权信息（精选+破产捡漏）
          </Button>
          <Button size="large" loading={syncingAmc} onClick={syncAmc} icon={<SyncOutlined />}>
            同步 AMC 公告（长城/中信金融/信达/东方）
          </Button>
        </Space>
      </Card>

      {/* 当前栏目列表（点击栏目进入）*/}
      {activeSection ? (
        <Card
          title={<span><Tag color="blue">{(isEditor ? EDITOR_SECTIONS : SECTIONS).find((s) => s.value === activeSection)?.label || activeSection}</Tag>{items.filter((i) => i.section === activeSection).length} 条</span>}
          style={{ marginBottom: 16 }}
          extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增内容</Button>}
        >
          <Table rowKey="id" columns={columns} dataSource={items.filter((i) => i.section === activeSection)} pagination={{ pageSize: 10 }} />
        </Card>
      ) : (
        <Card><span style={{ color: 'var(--text-weak)' }}>请选择上方栏目</span></Card>
      )}

      {/* 平台公告（区别于债权公告：平台通知/说明）*/}
      <Card
        title={<span><Tag color="purple">平台公告</Tag> 平台通知与说明（{platformNotices.length} 条）</span>}
        style={{ marginBottom: 16 }}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openNoticeCreate}>发布公告</Button>}
      >
        <Table
          rowKey="id"
          size="small"
          dataSource={platformNotices}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: '标题', dataIndex: 'title', render: (v, r) => <span>{r.is_pinned && <Tag color="red">置顶</Tag>}{v}</span> },
            { title: '内容', dataIndex: 'content', ellipsis: true },
            { title: '状态', dataIndex: 'enabled', width: 80, render: (v) => v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag> },
            { title: '发布日期', dataIndex: 'published_at', width: 120, render: (v) => (v || '').slice(0, 10) },
            { title: '操作', width: 140, render: (_, r) => (
              <Space>
                <Button size="small" onClick={() => openNoticeEdit(r)}>编辑</Button>
                <Popconfirm title="确认删除该平台公告？" onConfirm={() => delNotice(r.id)}>
                  <Button size="small" danger>删除</Button>
                </Popconfirm>
              </Space>
            ) },
          ]}
        />
      </Card>

      {/* 平台公告编辑弹窗 */}
      <Modal title={noticeEditing?.id ? '编辑平台公告' : '发布平台公告'} open={noticeOpen}
        onOk={saveNotice} onCancel={() => setNoticeOpen(false)} width={560} destroyOnClose>
        <Form form={noticeForm} layout="vertical">
          <Form.Item name="title" label="公告标题" rules={[{ required: true, message: '请输入标题' }]}><Input /></Form.Item>
          <Form.Item name="content" label="公告内容"><Input.TextArea rows={5} /></Form.Item>
          <Space size="large">
            <Form.Item name="is_pinned" valuePropName="checked" label="置顶"><Checkbox /></Form.Item>
            <Form.Item name="enabled" valuePropName="checked" label="启用"><Checkbox /></Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 土地价格库区块（有权限的员工可见）*/}
      {hasLandPerm && (
        <Card
          title={<span><Tag color="orange">土地价格库</Tag> 土地参考价录入</span>}
          style={{ marginBottom: 16 }}
          extra={<Button type="primary" onClick={() => navigate('/admin/land-prices')}>进入土地价格库</Button>}
        >
          <span style={{ fontSize: 13 }}>维护各地土地出让基准价/成交价（元/㎡），抵押物估值时自动参考。土地性质分类参照 GB/T 21010-2017。</span>
        </Card>
      )}

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
