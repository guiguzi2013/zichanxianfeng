import { useEffect, useState } from 'react'
import { Card, Statistic, Row, Col, Table, Tag, Typography, Spin, Button, Space, Modal, Form, Input, Switch, message, Popconfirm, Tabs, Descriptions, Alert, Popover } from 'antd'
import { UserOutlined, FileTextOutlined, CheckCircleOutlined, DatabaseOutlined, InboxOutlined, TagsOutlined, TeamOutlined, PlusOutlined, EditOutlined, ReloadOutlined, EyeOutlined, SearchOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { adminClueApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Title } = Typography

// 格式化秒数为"X小时X分/X分钟"（今日在线时长）
function formatSeconds(sec) {
  if (sec == null || sec < 0) return '—'
  if (sec < 60) return '不足1分钟'
  const mins = Math.floor(sec / 60)
  if (mins < 60) return `${mins}分钟`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h}小时${m}分` : `${h}小时`
}

export default function AdminDashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'
  const isEditor = user?.role === 'editor'
  const hasLandPerm = isAdmin || (isEditor && user?.land_price_perm)
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [staffModal, setStaffModal] = useState(false)
  const [staffForm] = Form.useForm()
  const [editStaff, setEditStaff] = useState(null) // 当前编辑的员工
  // 用户登录时段（2026-09-01：管理员点开看该用户全部登录会话，分页展示所有历史记录）
  const [sessionModal, setSessionModal] = useState(null) // { user_id, username }
  const [sessions, setSessions] = useState([])
  const [sessionTotal, setSessionTotal] = useState(0)
  const [sessionPage, setSessionPage] = useState(1)
  const [sessionLoading, setSessionLoading] = useState(false)
  const loadSessions = async (u, page = 1) => {
    setSessionLoading(true)
    setSessionModal((prev) => ({ user_id: u.id, username: u.username }))
    setSessionPage(page)
    try {
      const resp = await client.get(`/admin/users/${u.id}/sessions`, { params: { offset: (page - 1) * 50, limit: 50 } })
      setSessions(resp.data?.sessions || [])
      setSessionTotal(resp.data?.total || 0)
    } catch { /* 拦截器已提示 */ } finally {
      setSessionLoading(false)
    }
  }

  useEffect(() => {
    const load = async () => {
      try {
        // 分开请求，各自容错（避免单接口失败导致整页报错）
        const s = await client.get('/admin/stats').catch(() => null)
        if (s) setStats(s.data)
      } catch { /* 拦截器已提示 */ }
      try {
        const u = await client.get('/admin/users').catch(() => null)
        if (u) setUsers(u.data?.users || [])
      } catch { /* 拦截器已提示 */ } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // 报告管理弹窗（员工可查看用户生成的报告，处理用户问题/投诉；不能下载）
  const [reportModal, setReportModal] = useState(false)
  const [reports, setReports] = useState([])
  const [reportLoading, setReportLoading] = useState(false)
  const [reportSearch, setReportSearch] = useState('')
  const loadReports = async (username) => {
    setReportLoading(true)
    try {
      const resp = await client.get('/admin/reports', { params: { username: username || undefined, limit: 50 } })
      setReports(resp.data?.reports || [])
    } catch { /* 拦截器已提示 */ } finally {
      setReportLoading(false)
    }
  }
  const openReports = async () => {
    setReportModal(true)
    setReportSearch('')
    loadReports('')
    loadClueReports('')
  }
  const searchReports = () => loadReports(reportSearch)

  // 财产线索/深挖报告（2026-09-01 落库留存，管理后台可查看；员工可看、清缓存仅管理员）
  const [clueReports, setClueReports] = useState([])
  const [clueLoading, setClueLoading] = useState(false)
  const [clueSearch, setClueSearch] = useState('')
  const [clueDetail, setClueDetail] = useState(null) // 查看报告全文弹窗
  const [clueDetailLoading, setClueDetailLoading] = useState(false)
  const loadClueReports = async (username) => {
    setClueLoading(true)
    try {
      const resp = await adminClueApi.list({ username: username || undefined, limit: 50 })
      setClueReports(resp.data?.reports || [])
    } catch { /* 拦截器已提示 */ } finally {
      setClueLoading(false)
    }
  }
  const searchClueReports = () => loadClueReports(clueSearch)
  const viewClueReport = async (id) => {
    setClueDetailLoading(true)
    try {
      const resp = await adminClueApi.get(id)
      setClueDetail(resp.data)
    } catch { /* 拦截器已提示 */ } finally {
      setClueDetailLoading(false)
    }
  }
  const clearClueCache = async (r) => {
    try {
      const resp = await adminClueApi.clearCache(r.id)
      message.success(resp.message || '缓存已清除')
    } catch { /* 拦截器已提示 */ }
  }
  const clearReportCache = async (r) => {
    try {
      const resp = await adminClueApi.clearReportCache(r.report_id)
      message.success(resp.message || '缓存已清除')
    } catch { /* 拦截器已提示 */ }
  }

  const createStaff = async () => {
    const v = await staffForm.validateFields()
    try {
      await client.post('/admin/editor-accounts', { ...v, land_price_perm: v.land_price_perm || false })
      message.success('员工账号已创建')
      setStaffModal(false)
      staffForm.resetFields()
      const u = await client.get('/admin/users')
      setUsers(u.data?.users || [])
    } catch { /* 拦截器已提示 */ }
  }

  const openEditStaff = (r) => {
    setEditStaff(r)
    staffForm.setFieldsValue({ nickname: r.nickname, land_price_perm: r.land_price_perm })
  }

  const saveEditStaff = async () => {
    const v = await staffForm.validateFields()
    try {
      await client.put(`/admin/editor-accounts/${editStaff.id}`, { nickname: v.nickname, land_price_perm: v.land_price_perm || false })
      message.success('员工账号已更新')
      setEditStaff(null)
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
    { title: '报告数', value: (stats?.reports || 0) + (stats?.clue_reports || 0), icon: <FileTextOutlined />, color: '#722ed1', onClick: openReports },
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
          {hasLandPerm && <Button onClick={() => navigate('/admin/land-prices')}>土地价格库</Button>}
          {isAdmin && <Button onClick={() => navigate('/admin/data')}>市场数据管理</Button>}
          {isAdmin && <Button onClick={() => navigate('/admin/knowledge')}>知识库</Button>}
        </Space>
      </div>

      {/* 权限提示：编辑只能维护精选/捡漏 */}
      {isEditor && (
        <Card style={{ marginBottom: 16, borderColor: '#b7eb8f' }}>
          <Space>
            <Tag color="green">您的权限</Tag>
            <span style={{ fontSize: 13 }}>
              可录入 / 删改：精选债权、热门捡漏{hasLandPerm ? '、土地价格库' : ''}。其余栏目为自动抓取数据，系统配置与用户管理仅管理员可用。
            </span>
          </Space>
        </Card>
      )}

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {cards.map((c) => (
          <Col xs={12} md={6} key={c.title}>
            <Card hoverable={!!c.onClick} onClick={c.onClick} style={c.onClick ? { cursor: 'pointer' } : undefined}>
              <Statistic title={c.title} value={c.value ?? 0} prefix={<span style={{ color: c.color }}>{c.icon}</span>} />
              {c.onClick && <div style={{ fontSize: 11, color: 'var(--text-weak)', marginTop: 4 }}>点击查看</div>}
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
              员工账号可录入 / 删改「精选债权」「热门捡漏」；勾选「土地价格库权限」后还可录入土地参考价（删除土地记录仅管理员）。不能管理用户与系统配置。
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
                {
                  title: '土地价格库权限', dataIndex: 'land_price_perm', width: 140,
                  render: (v) => (v ? <Tag color="green">已开通</Tag> : <Tag>未开通</Tag>),
                },
                { title: '创建时间', dataIndex: 'created_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
                {
                  title: '操作', width: 140,
                  render: (_, r) => (
                    <Space>
                      <Button size="small" icon={<EditOutlined />} onClick={() => openEditStaff(r)}>修改</Button>
                      <Popconfirm title="确认删除该员工账号？" onConfirm={() => deleteStaff(r.id)}>
                        <Button size="small" danger>删除</Button>
                      </Popconfirm>
                    </Space>
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
              {
                title: '最后上线时间', dataIndex: 'last_login_at', width: 150,
                render: (v, r) => {
                  if (!v) return <span style={{ color: 'var(--text-weak)' }}>从未登录</span>
                  const login = new Date(v)
                  const logout = r.last_logout_at ? new Date(r.last_logout_at) : null
                  const online = !logout || login.getTime() > logout.getTime()
                  return (
                    <Space direction="vertical" size={0}>
                      <span>{String(v).replace('T', ' ').slice(0, 16)}</span>
                      {online && <Tag color="green" style={{ marginTop: 2 }}>在线</Tag>}
                    </Space>
                  )
                },
              },
              {
                title: '今日在线时间', dataIndex: 'today_online_seconds', width: 130,
                render: (v, r) => {
                  const login = r.last_login_at ? new Date(r.last_login_at) : null
                  const logout = r.last_logout_at ? new Date(r.last_logout_at) : null
                  const online = login && (!logout || login.getTime() > logout.getTime())
                  return online
                    ? <Tag color="green">{formatSeconds(v)}（进行中）</Tag>
                    : <span>{formatSeconds(v)}</span>
                },
              },
              {
                title: '操作', width: 100,
                render: (_, r) => (
                  <Button size="small" icon={<SearchOutlined />} onClick={() => loadSessions(r)}>登录记录</Button>
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* 登录时段弹窗（2026-09-01：管理员查看该用户全部登录会话，分页） */}
      <Modal
        title={`登录记录：${sessionModal?.username || ''}（共 ${sessionTotal} 条，全部历史，不限当天）`}
        open={sessionModal != null}
        onCancel={() => setSessionModal(null)}
        footer={<Button type="primary" onClick={() => setSessionModal(null)}>关闭</Button>}
        width={820}
      >
        <Table
          rowKey="id"
          size="small"
          loading={sessionLoading}
          dataSource={sessions}
          pagination={{
            current: sessionPage,
            pageSize: 50,
            total: sessionTotal,
            showTotal: (t) => `共 ${t} 条登录记录`,
            onChange: (p) => loadSessions(sessionModal, p),
          }}
          locale={{ emptyText: '暂无登录记录' }}
          columns={[
            { title: '登录时间', dataIndex: 'login_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 19) : '—') },
            {
              title: '登出时间', dataIndex: 'logout_at',
              render: (v, r) => r.online ? <Tag color="green">在线中</Tag> : (v ? String(v).replace('T', ' ').slice(0, 19) : '—'),
            },
            {
              title: '在线时长', dataIndex: 'duration_seconds', width: 130,
              render: (v, r) => r.online
                ? <Tag color="green">{formatSeconds(v)}（进行中）</Tag>
                : <span>{formatSeconds(v)}</span>,
            },
          ]}
        />
      </Modal>

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
          <Form.Item name="land_price_perm" label="土地价格库录入权限" valuePropName="checked" initialValue={false}>
            <Switch checkedChildren="开通" unCheckedChildren="不开通" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 修改员工账号弹窗 */}
      <Modal title={`修改员工账号（${editStaff?.username || ''}）`} open={editStaff != null} onOk={saveEditStaff} onCancel={() => setEditStaff(null)} okText="保存">
        <Form form={staffForm} layout="vertical">
          <Form.Item name="nickname" label="昵称">
            <Input placeholder="如 小李（录入员）" />
          </Form.Item>
          <Form.Item name="land_price_perm" label="土地价格库录入权限" valuePropName="checked">
            <Switch checkedChildren="开通" unCheckedChildren="不开通" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 报告管理弹窗：尽调报告 + 财产线索报告 + 深挖（占位）；员工可查看处理投诉，清缓存仅管理员 */}
      <Modal
        title="平台报告（查看用户生成的报告，处理用户问题/投诉）"
        open={reportModal}
        onCancel={() => setReportModal(false)}
        footer={null}
        width={1100}
      >
        <Tabs
          items={[
            {
              key: 'dd',
              label: `尽调报告（${stats?.reports || 0}）`,
              children: (
                <>
                  <Space style={{ marginBottom: 12 }}>
                    <Input
                      placeholder="按用户名 / 昵称搜索"
                      value={reportSearch}
                      onChange={(e) => setReportSearch(e.target.value)}
                      onPressEnter={searchReports}
                      style={{ width: 240 }}
                    />
                    <Button type="primary" onClick={searchReports} loading={reportLoading}>搜索</Button>
                    <Button onClick={() => { setReportSearch(''); loadReports('') }}>全部</Button>
                  </Space>
                  <Table
                    rowKey="report_id"
                    size="small"
                    loading={reportLoading}
                    dataSource={reports}
                    pagination={{ pageSize: 10 }}
                    scroll={{ x: 'max-content' }}
                    columns={[
                      { title: '报告ID', dataIndex: 'report_id', width: 80 },
                      { title: '用户', dataIndex: 'username', width: 110, render: (v, r) => <span>{v}<span style={{ color: 'var(--text-weak)', fontSize: 12 }}>（{r.nickname || ''}）</span></span> },
                      { title: '债务人', dataIndex: 'debtor_name', ellipsis: true, render: (v) => v || '—' },
                      { title: '版本', dataIndex: 'version', width: 60 },
                      { title: '任务状态', dataIndex: 'task_status', width: 100, render: (v) => <Tag color={v === 'done' ? 'success' : 'default'}>{v === 'done' ? '已完成' : v}</Tag> },
                      { title: '生成时间', dataIndex: 'created_at', width: 140, render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
                      {
                        title: '操作', width: isAdmin ? 190 : 100,
                        render: (_, r) => (
                          <Space size={4}>
                            <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => navigate(`/report/${r.task_id}/${r.report_id}`)}>查看报告</Button>
                            {isAdmin && (
                              <Popconfirm title={`确认清除「${r.debtor_name || r.report_id}」的企查查缓存？下次尽调将重新实查（消耗积分）`} onConfirm={() => clearReportCache(r)}>
                                <Button size="small" type="link" danger icon={<ReloadOutlined />}>清缓存</Button>
                              </Popconfirm>
                            )}
                          </Space>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'clue',
              label: `财产线索报告（${stats?.clue_reports || 0}）`,
              children: (
                <>
                  <Space style={{ marginBottom: 12 }}>
                    <Input
                      placeholder="按用户名 / 昵称搜索"
                      value={clueSearch}
                      onChange={(e) => setClueSearch(e.target.value)}
                      onPressEnter={searchClueReports}
                      style={{ width: 240 }}
                    />
                    <Button type="primary" onClick={searchClueReports} loading={clueLoading}>搜索</Button>
                    <Button onClick={() => { setClueSearch(''); loadClueReports('') }}>全部</Button>
                  </Space>
                  <Table
                    rowKey="id"
                    size="small"
                    loading={clueLoading}
                    dataSource={clueReports}
                    pagination={{ pageSize: 10 }}
                    scroll={{ x: 'max-content' }}
                    columns={[
                      { title: 'ID', dataIndex: 'id', width: 70 },
                      { title: '用户', dataIndex: 'username', width: 110, render: (v, r) => <span>{v}<span style={{ color: 'var(--text-weak)', fontSize: 12 }}>（{r.nickname || ''}）</span></span> },
                      { title: '类型', dataIndex: 'report_type', width: 80, render: (v) => <Tag color={v === 'deep' ? 'purple' : 'blue'}>{v === 'deep' ? '深挖' : '综合分析'}</Tag> },
                      { title: '标题', dataIndex: 'title', ellipsis: true },
                      { title: '主体', dataIndex: 'subject_names', ellipsis: true, render: (v) => (Array.isArray(v) && v.length ? v.join('、') : '—') },
                      { title: '生成时间', dataIndex: 'created_at', width: 140, render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
                      {
                        title: '操作', width: isAdmin ? 190 : 100,
                        render: (_, r) => (
                          <Space size={4}>
                            <Button size="small" type="link" icon={<EyeOutlined />} loading={clueDetailLoading} onClick={() => viewClueReport(r.id)}>查看报告</Button>
                            {isAdmin && (
                              <Popconfirm title={`确认清除该报告涉及主体（${(r.subject_names || []).join('、') || '无'}）的企查查缓存？下次查询将重新实查（消耗积分）`} onConfirm={() => clearClueCache(r)}>
                                <Button size="small" type="link" danger icon={<ReloadOutlined />}>清缓存</Button>
                              </Popconfirm>
                            )}
                          </Space>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'deep',
              label: '深挖（功能完善中）',
              children: (
                <Alert type="info" showIcon message="「深挖」功能待完善：将在用户使用财产线索功能后出现，用于用户补充资料后对财产线索深度挖掘。当前暂无数据列表。" style={{ marginTop: 8 }} />
              ),
            },
          ]}
        />
      </Modal>

      {/* 财产线索/深挖报告全文查看弹窗 */}
      <Modal
        title={clueDetail ? clueDetail.title : '报告详情'}
        open={clueDetail != null}
        onCancel={() => setClueDetail(null)}
        footer={<Button type="primary" onClick={() => setClueDetail(null)}>关闭</Button>}
        width={900}
      >
        {clueDetail && (
          <>
            <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="用户">{clueDetail.username}（{clueDetail.nickname || ''}）</Descriptions.Item>
              <Descriptions.Item label="类型">{clueDetail.report_type === 'deep' ? '深挖' : '综合分析'}</Descriptions.Item>
              <Descriptions.Item label="涉及主体">{(clueDetail.subject_names || []).join('、') || '—'}</Descriptions.Item>
              <Descriptions.Item label="生成时间">{clueDetail.created_at ? String(clueDetail.created_at).replace('T', ' ').slice(0, 16) : '—'}</Descriptions.Item>
            </Descriptions>
            <pre style={{ maxHeight: '55vh', overflow: 'auto', background: '#f6f8fa', borderRadius: 8, padding: 12, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {JSON.stringify(clueDetail.content || {}, null, 2)}
            </pre>
          </>
        )}
      </Modal>
    </div>
  )
}
