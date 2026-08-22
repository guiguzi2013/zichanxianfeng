import { useEffect, useState } from 'react'
import { Card, Statistic, Row, Col, Table, Tag, Typography, Spin, Button, Space, Modal, Form, Input, message, Popconfirm } from 'antd'
import { UserOutlined, FileTextOutlined, CheckCircleOutlined, DatabaseOutlined, InboxOutlined, TagsOutlined, TeamOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore } from '../store/auth'

const { Title } = Typography

export default function AdminDashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'
  const isEditor = user?.role === 'editor'
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [staffModal, setStaffModal] = useState(false)
  const [staffForm] = Form.useForm()

  useEffect(() => {
    const load = async () => {
      try {
        const [s, u] = await Promise.all([
          client.get('/admin/stats'),
          client.get('/admin/users'),
        ])
        setStats(s.data)
        setUsers(u.data?.users || [])
      } catch { /* 拦截器已提示 */ } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const createStaff = async () => {
    const v = await staffForm.validateFields()
    try {
      await client.post('/admin/editor-accounts', v)
      message.success('员工账号已创建')
      setStaffModal(false)
      staffForm.resetFields()
      const u = await client.get('/admin/users')
      setUsers(u.data?.users || [])
    } catch { /* 拦截器已提示 */ }
  }

  const deleteStaff = async (id) => {
    try {
      await client.delete(`/admin/editor-accounts/${id}`)
      message.success('员工账号已删除')
      const u = await client.get('/admin/users')
      setUsers(u.data?.users || [])
    } catch { /* 拦截器已提示 */ }
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>

  const cards = [
    { title: '用户数', value: stats?.users, icon: <UserOutlined />, color: '#1a5fb4' },
    { title: '债权记录', value: stats?.claims, icon: <DatabaseOutlined />, color: '#389e0d' },
    { title: '尽调任务', value: stats?.tasks, icon: <FileTextOutlined />, color: '#d48806' },
    { title: '已完成任务', value: stats?.tasks_done, icon: <CheckCircleOutlined />, color: '#13c2c2' },
    { title: '报告数', value: stats?.reports, icon: <FileTextOutlined />, color: '#722ed1' },
    { title: '栏目内容', value: stats?.feed_items, icon: <TagsOutlined />, color: '#eb2f96' },
    { title: '上传文件', value: stats?.uploads, icon: <InboxOutlined />, color: '#fa8c16' },
  ]

  const staffList = users.filter((u) => u.role === 'editor')

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>
          管理后台{isEditor && <Tag color="blue" style={{ marginLeft: 8 }}>运营编辑</Tag>}
        </Title>
        <Space>
          <Button type="primary" onClick={() => navigate('/admin/feed')}>栏目内容管理</Button>
          {isAdmin && <Button onClick={() => navigate('/admin/data')}>市场数据管理</Button>}
          {isAdmin && <Button onClick={() => navigate('/admin/knowledge')}>知识库</Button>}
        </Space>
      </div>

      {/* 权限提示：编辑只能维护精选/捡漏 */}
      {isEditor && (
        <Card style={{ marginBottom: 16, borderColor: '#b7eb8f' }}>
          <Space>
            <Tag color="green">您的权限</Tag>
            <span style={{ fontSize: 13 }}>可录入 / 删改：精选债权、热门捡漏。其余栏目为自动抓取数据，系统配置与用户管理仅管理员可用。</span>
          </Space>
        </Card>
      )}

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {cards.map((c) => (
          <Col xs={12} md={6} key={c.title}>
            <Card>
              <Statistic title={c.title} value={c.value ?? 0} prefix={<span style={{ color: c.color }}>{c.icon}</span>} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        title="栏目内容管理"
        extra={<Button type="primary" onClick={() => navigate('/admin/feed')}>进入管理</Button>}
        style={{ marginBottom: 16 }}
      >
        <Space>
          {isEditor
            ? <span style={{ fontSize: 13 }}>维护精选债权 / 热门捡漏（您的权限范围）</span>
            : <span style={{ fontSize: 13 }}>维护首页精选债权 / 捡漏 / 存量资产盘活等栏目数据</span>}
        </Space>
      </Card>

      {/* 员工账号管理（仅管理员）*/}
      {isAdmin && (
        <Card
          title={<Space><TeamOutlined />员工账号管理（运营编辑）</Space>}
          extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setStaffModal(true)}>开通员工账号</Button>}
          style={{ marginBottom: 16 }}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              员工账号仅可录入 / 删改「精选债权」「热门捡漏」，不能管理用户与系统配置。
            </span>
            <Table
              rowKey="id"
              size="small"
              dataSource={staffList}
              pagination={false}
              locale={{ emptyText: '暂无员工账号' }}
              columns={[
                { title: 'ID', dataIndex: 'id', width: 60 },
                { title: '用户名', dataIndex: 'username' },
                { title: '昵称', dataIndex: 'nickname' },
                { title: '角色', width: 100, render: () => <Tag color="blue">运营编辑</Tag> },
                { title: '创建时间', dataIndex: 'created_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
                {
                  title: '操作', width: 90,
                  render: (_, r) => (
                    <Popconfirm title="确认删除该员工账号？" onConfirm={() => deleteStaff(r.id)}>
                      <Button size="small" danger>删除</Button>
                    </Popconfirm>
                  ),
                },
              ]}
            />
          </Space>
        </Card>
      )}

      {/* 用户列表（仅管理员）*/}
      {isAdmin && (
        <Card title="用户列表">
          <Table
            rowKey="id"
            size="small"
            dataSource={users}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 60 },
              { title: '用户名', dataIndex: 'username' },
              { title: '昵称', dataIndex: 'nickname' },
              {
                title: '角色', dataIndex: 'role', width: 100,
                render: (v) => <Tag color={v === 'admin' ? 'gold' : v === 'editor' ? 'blue' : 'green'}>{v === 'admin' ? '管理员' : v === 'editor' ? '运营编辑' : '用户'}</Tag>,
              },
              { title: '积分', dataIndex: 'points', width: 80 },
              { title: '注册时间', dataIndex: 'created_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
            ]}
          />
        </Card>
      )}

      {/* 开通员工账号弹窗 */}
      <Modal title="开通员工账号（运营编辑）" open={staffModal} onOk={createStaff} onCancel={() => setStaffModal(false)} okText="创建">
        <Form form={staffForm} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input placeholder="如 editor01" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 6, message: '至少6位' }]}>
            <Input.Password placeholder="初始密码" />
          </Form.Item>
          <Form.Item name="nickname" label="昵称">
            <Input placeholder="如 小李（录入员）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
