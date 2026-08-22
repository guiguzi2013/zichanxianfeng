import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Typography, Spin, message, Tabs, Descriptions, Space, Modal, Form, Input } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { taskApi, authApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Title, Text } = Typography

const STATUS_META = {
  pending: { color: 'default', label: '待尽调' },
  running: { color: 'processing', label: '尽调中' },
  done: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
  partial: { color: 'warning', label: '部分完成' },
}

export default function TasksPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'tasks'
  const { user } = useAuthStore()
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const resp = await taskApi.list()
        setTasks(resp.data.tasks || [])
      } catch { /* 拦截器已提示 */ } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const startDD = async (id) => {
    try {
      const resp = await taskApi.start(id)
      message.success('尽调已启动')
      navigate(`/progress/${resp.data.id}`)
    } catch { /* 拦截器已提示 */ }
  }

  const taskColumns = [
    { title: '任务ID', dataIndex: 'id', width: 80 },
    { title: '债权数', dataIndex: 'claim_ids', width: 90, render: (v) => (Array.isArray(v) ? v.length : 0) },
    { title: '状态', dataIndex: 'status', width: 100, render: (v) => { const m = STATUS_META[v] || STATUS_META.pending; return <Tag color={m.color}>{m.label}</Tag> } },
    { title: '进度', dataIndex: 'progress', width: 100, render: (v) => `${v}%` },
    { title: '创建时间', dataIndex: 'created_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    {
      title: '操作', width: 200,
      render: (_, record) => (
        <>
          {record.status === 'pending' && <Button type="link" onClick={() => startDD(record.id)}>开始尽调</Button>}
          <Button type="link" disabled={record.status !== 'done' && record.status !== 'partial'} onClick={() => navigate(`/report/${record.id}`)}>查看报告</Button>
        </>
      ),
    },
  ]

  const doneTasks = tasks.filter((t) => t.status === 'done' || t.status === 'partial')
  const reportColumns = [
    { title: '报告ID', dataIndex: 'id', width: 80 },
    { title: '债权数', dataIndex: 'claim_ids', width: 90, render: (v) => (Array.isArray(v) ? v.length : 0) },
    { title: '状态', dataIndex: 'status', width: 100, render: (v) => { const m = STATUS_META[v] || STATUS_META.pending; return <Tag color={m.color}>{m.label}</Tag> } },
    { title: '完成时间', dataIndex: 'updated_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    {
      title: '操作', width: 120,
      render: (_, record) => <Button type="link" onClick={() => navigate(`/report/${record.id}`)}>查看报告 / 下载PDF</Button>,
    },
  ]

  const setTab = (key) => setParams(key === 'tasks' ? {} : { tab: key }, { replace: true })

  // 修改密码
  const [pwdModal, setPwdModal] = useState(false)
  const [pwdForm] = Form.useForm()
  const changePassword = async () => {
    const v = await pwdForm.validateFields()
    try {
      await authApi.changePassword({ old_password: v.old_password, new_password: v.new_password })
      message.success('密码已修改，请重新登录')
      setPwdModal(false)
      useAuthStore.getState().logout()
      navigate('/login')
    } catch { /* 拦截器已提示 */ }
  }

  const profileTab = (
    <Card>
      <Descriptions column={1} bordered size="small" style={{ maxWidth: 560 }}>
        <Descriptions.Item label="用户名">{user?.username}</Descriptions.Item>
        <Descriptions.Item label="昵称">{user?.nickname || '—'}</Descriptions.Item>
        <Descriptions.Item label="角色">
          <Tag color={user?.role === 'admin' ? 'gold' : user?.role === 'editor' ? 'blue' : 'green'}>
            {user?.role === 'admin' ? '管理员' : user?.role === 'editor' ? '运营编辑' : '注册用户'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="积分余额">{user?.points ?? 0}</Descriptions.Item>
        <Descriptions.Item label="注册时间">{user?.created_at ? String(user.created_at).replace('T', ' ').slice(0, 16) : '—'}</Descriptions.Item>
      </Descriptions>
      <Space style={{ marginTop: 16 }}>
        <Button type="primary" onClick={() => setPwdModal(true)}>修改密码</Button>
      </Space>
    </Card>
  )

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <Title level={3}>用户中心</Title>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'tasks', label: `我的任务（${tasks.length}）`, children: <Card>{loading ? <Spin /> : <Table rowKey="id" columns={taskColumns} dataSource={tasks} pagination={{ pageSize: 10 }} />}</Card> },
          { key: 'reports', label: `我的报告（${doneTasks.length}）`, children: <Card>{loading ? <Spin /> : <Table rowKey="id" columns={reportColumns} dataSource={doneTasks} pagination={{ pageSize: 10 }} />}</Card> },
          { key: 'profile', label: '账户信息', children: profileTab },
        ]}
      />

      {/* 修改密码弹窗 */}
      <Modal title="修改密码" open={pwdModal} onOk={changePassword} onCancel={() => setPwdModal(false)} okText="确认修改" destroyOnClose>
        <Form form={pwdForm} layout="vertical">
          <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 6, message: '至少6位' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, v) => (!v || getFieldValue('new_password') === v ? Promise.resolve() : Promise.reject(new Error('两次密码不一致'))),
              }),
            ]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
