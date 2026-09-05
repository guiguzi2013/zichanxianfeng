import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Typography, Spin, message, Tabs, Descriptions, Space, Modal, Form, Input } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { taskApi, authApi, activityApi } from '../api'
import client from '../api/client'
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
  const [valuations, setValuations] = useState([])
  const [clues, setClues] = useState([])
  const [myReports, setMyReports] = useState([])   // 报告级列表（每份一行）
  const [loading, setLoading] = useState(true)
  const [reportKeyword, setReportKeyword] = useState('')  // 2026-09-02 报告搜索

  // 2026-09-02：报告按 债务人/标题 过滤
  const rkw = reportKeyword.trim().toLowerCase()
  const filteredReports = rkw
    ? myReports.filter((r) => `${r.debtor_name || ''} ${r.title || ''}`.toLowerCase().includes(rkw))
    : myReports

  // 任务原始表格弹窗
  useEffect(() => {
    const load = async () => {
      try {
        const [t, v, c, r] = await Promise.all([
          taskApi.list(),
          activityApi.list('valuation'),
          activityApi.list('clue'),
          client.get('/reports/my/reports'),
        ])
        setTasks(t.data.tasks || [])
        setValuations(v.data.records || [])
        setClues(c.data.records || [])
        setMyReports(r.data?.reports || [])
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
    { title: '任务ID', dataIndex: 'id', width: 70 },
    {
      title: '任务名称',
      dataIndex: 'name',
      ellipsis: true,
      render: (v, r) => <Button type="link" style={{ padding: 0, height: 'auto', textAlign: 'left' }} onClick={() => navigate(`/task/${r.id}/edit`)}>{v || `任务#${r.id}`}</Button>,
    },
    { title: '债权数', dataIndex: 'claim_ids', width: 80, render: (v) => (Array.isArray(v) ? v.length : 0) },
    { title: '来源', dataIndex: 'id', width: 90, render: () => <Tag color="blue">智能尽调</Tag> },
    { title: '状态', dataIndex: 'status', width: 100, render: (v) => { const m = STATUS_META[v] || STATUS_META.pending; return <Tag color={m.color}>{m.label}</Tag> } },
    { title: '进度', dataIndex: 'progress', width: 80, render: (v) => `${v}%` },
    { title: '创建时间', dataIndex: 'created_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    {
      title: '操作', width: 100,
      render: (_, record) => (
        record.status === 'pending'
          ? <Button type="link" onClick={() => startDD(record.id)}>开始尽调</Button>
          : null
      ),
    },
  ]

  const activityColumns = [
    { title: '时间', dataIndex: 'created_at', width: 140, render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    { title: '标题', dataIndex: 'title', width: 240, render: (v) => <Text strong>{v}</Text> },
    { title: '摘要', dataIndex: 'summary', render: (v) => v || '—' },
  ]

  const doneTasks = tasks.filter((t) => t.status === 'done' || t.status === 'partial')
  // 报告级列表：每份报告一行（含债务人画像/企业速览 2026-09-04），点哪行看哪份
  const reportColumns = [
    { title: '报告ID', dataIndex: 'report_id', width: 80, render: (v, r) => (r.type === 'profile' ? '—' : v) },
    { title: '类型', dataIndex: 'type', width: 100, render: (v) => v === 'profile' ? <Tag color="blue">企业速览</Tag> : <Tag color="green">债权尽调</Tag> },
    {
      title: '债务人/企业', dataIndex: 'debtor_name', ellipsis: true,
      render: (v) => <Text strong>{v ? String(v).split('；')[0] : '—'}</Text>,
    },
    { title: '版本', dataIndex: 'version', width: 70, render: (v) => `v${v || 1}` },
    {
      title: '状态', dataIndex: 'task_status', width: 100,
      render: (v) => { const m = STATUS_META[v] || STATUS_META.pending; return <Tag color={m.color}>{m.label}</Tag> },
    },
    { title: '生成时间', dataIndex: 'created_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    {
      title: '操作', width: 110,
      render: (_, record) => (
        record.type === 'profile'
          ? <Button type="link" onClick={() => navigate(`/debtor-report/${record.profile_id}`)}>查看报告</Button>
          : <Button type="link" onClick={() => navigate(`/report/${record.task_id}/${record.report_id}`)}>查看报告</Button>
      ),
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
      navigate('/login', { state: { from: window.location.pathname } })
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
          {
            key: 'tasks',
            label: `我的任务（${tasks.length + valuations.length + clues.length}）`,
            children: loading ? <Spin /> : (
              <>
                {/* 区块一：智能尽调任务 */}
                <Card title={<span><Tag color="blue">智能尽调</Tag> 债权尽调任务（{tasks.length}）</span>} style={{ marginBottom: 16 }}>
                  <Table rowKey="id" columns={taskColumns} dataSource={tasks} pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
                </Card>
                {/* 区块二：土地厂房估价 */}
                <Card title={<span><Tag color="orange">土地厂房估价</Tag> 估价记录（{valuations.length}）</span>} style={{ marginBottom: 16 }}>
                  {valuations.length ? <Table rowKey="id" columns={activityColumns} dataSource={valuations} pagination={{ pageSize: 10 }} /> : <Text type="secondary">暂无估价记录，去「土地厂房估价」试试</Text>}
                </Card>
                {/* 区块三：财产线索 */}
                <Card title={<span><Tag color="green">财产线索</Tag> 查询记录（{clues.length}）</span>}>
                  {clues.length ? <Table rowKey="id" columns={activityColumns} dataSource={clues} pagination={{ pageSize: 10 }} /> : <Text type="secondary">暂无财产线索查询记录，去「财产线索」试试</Text>}
                </Card>
              </>
            ),
          },
          {
            key: 'reports',
            label: `我的报告（${myReports.length}）`,
            children: loading ? <Spin /> : (
              <>
                {/* 2026-09-02：报告搜索（债务人/标题过滤） */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                  <Input.Search allowClear placeholder="搜索债务人/标题" style={{ width: 240 }} onSearch={(v) => setReportKeyword(v)} />
                </div>
                {/* 区块一：智能尽调报告（每份一行，按债务人）*/}
                <Card title={<span><Tag color="blue">智能尽调</Tag> 尽调报告（{filteredReports.length}）</span>} style={{ marginBottom: 16 }}>
                  <Table rowKey="report_id" columns={reportColumns} dataSource={filteredReports} pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
                </Card>
                {/* 区块二：估价报告（后期） */}
                <Card title={<span><Tag color="orange">土地厂房估价</Tag> 估价报告（{valuations.length}）</span>}>
                  {valuations.length
                    ? <Table rowKey="id" columns={activityColumns} dataSource={valuations} pagination={{ pageSize: 10 }} />
                    : <Text type="secondary">暂无估价记录（土地厂房估价可单独使用）</Text>}
                </Card>
              </>
            ),
          },
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
