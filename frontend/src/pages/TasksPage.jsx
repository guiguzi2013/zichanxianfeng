import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Typography, Spin, message, Tabs, Space, Modal, Popconfirm, Input } from 'antd'
import { DeleteOutlined, RestOutlined, UndoOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { taskApi, activityApi, trashApi } from '../api'
import client from '../api/client'

const { Title, Text } = Typography

const STATUS_META = {
  pending: { color: 'default', label: '待尽调' },
  running: { color: 'processing', label: '尽调中' },
  done: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
  partial: { color: 'warning', label: '部分完成' },
}
const KIND_META = {
  task: { tag: 'blue', label: '尽调任务' },
  report: { tag: 'green', label: '尽调报告' },
  profile: { tag: 'geekblue', label: '企业速览' },
  clue: { tag: 'orange', label: '财产线索' },
}

export default function TasksPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const rawTab = params.get('tab')
  const tab = ['tasks', 'reports', 'trash'].includes(rawTab) ? rawTab : 'tasks'
  const [tasks, setTasks] = useState([])
  const [valuations, setValuations] = useState([])
  const [clues, setClues] = useState([])
  const [myReports, setMyReports] = useState([])
  const [trashItems, setTrashItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [reportKeyword, setReportKeyword] = useState('')

  const rkw = reportKeyword.trim().toLowerCase()
  const filteredReports = rkw
    ? myReports.filter((r) => `${r.debtor_name || ''} ${r.title || ''}`.toLowerCase().includes(rkw))
    : myReports

  const loadAll = async () => {
    try {
      const [t, v, c, r, tr] = await Promise.all([
        taskApi.list(),
        activityApi.list('valuation'),
        activityApi.list('clue'),
        client.get('/reports/my/reports'),
        trashApi.list(),
      ])
      setTasks(t.data.tasks || [])
      setValuations(v.data.records || [])
      setClues(c.data.records || [])
      setMyReports(r.data?.reports || [])
      setTrashItems(tr.data?.items || [])
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadAll() }, [])

  const startDD = async (id) => {
    try {
      const resp = await taskApi.start(id)
      message.success('尽调已启动')
      navigate(`/progress/${resp.data.id}`)
    } catch { /* 拦截器已提示 */ }
  }

  // ---------- 删除(移入回收站) ----------
  const delItem = async (kind, id, extra) => {
    try {
      await trashApi.del(kind, id)
      message.success('已移入回收站（可恢复或清空）')
      loadAll()
    } catch (e) { message.error(e?.response?.data?.error || '删除失败') }
  }

  const openTrashUrl = (it) => {
    if (it.kind === 'task') navigate('/tasks')  // 任务在任务页; 回收站内点名称回列表
    if (it.kind === 'report') navigate(`/report/${it.task_id || ''}/${it.id}`)
    if (it.kind === 'profile') navigate(`/debtor-report/${it.id}`)
    if (it.kind === 'clue') navigate(`/clue-report/${it.id}`)
  }

  // ---------- 回收站操作 ----------
  const doRestore = async (it) => {
    try {
      await trashApi.restore(it.kind, it.id)
      message.success('已恢复')
      loadAll()
    } catch (e) { message.error(e?.response?.data?.error || '恢复失败') }
  }
  const doRegenerate = async (it) => {
    const isQuery = it.kind === 'profile' || it.kind === 'clue'
    Modal.confirm({
      title: isQuery ? '重新生成将消耗查询积分' : '确认重新尽调？',
      content: isQuery
        ? '将重新查询企查查并生成最新报告，单次消耗数十积分（依企业数据量而定）。确认继续？'
        : '将按原债权数据重新执行尽调并生成新版报告（已查过的数据走缓存）。确认继续？',
      okText: '确认并重新生成',
      okButtonProps: { danger: false },
      onOk: async () => {
        try {
          message.info('正在重新生成，约需 1-3 分钟，请勿关闭页面…', 6)
          await trashApi.regenerate(it.kind, it.id)
          message.success('重新生成完成，已恢复到列表中')
          loadAll()
        } catch (e) { message.error(e?.response?.data?.error || '重新生成失败') }
      },
    })
  }
  const doClear = async (it) => {
    Modal.confirm({
      title: '彻底删除？',
      content: `将从回收站彻底删除「${it.name}」（含已下载的 PDF），无法恢复。确认？`,
      okText: '彻底删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await trashApi.clear(it.kind, it.id)
          message.success('已彻底删除')
          loadAll()
        } catch (e) { message.error(e?.response?.data?.error || '删除失败') }
      },
    })
  }
  const doClearAll = () => {
    if (!trashItems.length) return
    Modal.confirm({
      title: '清空回收站？',
      content: `将彻底删除回收站中全部 ${trashItems.length} 条记录（含 PDF），无法恢复。确认？`,
      okText: '清空全部',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await trashApi.clearAll()
          message.success('回收站已清空')
          loadAll()
        } catch (e) { message.error(e?.response?.data?.error || '清空失败') }
      },
    })
  }

  // ---------- 表格列 ----------
  const taskColumns = [
    { title: '任务ID', dataIndex: 'id', width: 70 },
    {
      title: '任务名称', dataIndex: 'name', ellipsis: true,
      render: (v, r) => <Button type="link" style={{ padding: 0, height: 'auto', textAlign: 'left' }} onClick={() => navigate(`/task/${r.id}/edit`)}>{v || `任务#${r.id}`}</Button>,
    },
    { title: '债权数', dataIndex: 'claim_ids', width: 80, render: (v) => (Array.isArray(v) ? v.length : 0) },
    { title: '来源', dataIndex: 'id', width: 90, render: () => <Tag color="blue">智能尽调</Tag> },
    { title: '状态', dataIndex: 'status', width: 100, render: (v) => { const m = STATUS_META[v] || STATUS_META.pending; return <Tag color={m.color}>{m.label}</Tag> } },
    { title: '进度', dataIndex: 'progress', width: 80, render: (v) => `${v}%` },
    { title: '创建时间', dataIndex: 'created_at', render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    {
      title: '操作', width: 150,
      render: (_, record) => (
        <Space size={0}>
          {record.status === 'pending'
            ? <Button type="link" onClick={() => startDD(record.id)}>开始尽调</Button>
            : <Button type="link" onClick={() => navigate(`/progress/${record.id}`)}>进度</Button>}
          <Popconfirm title="移入回收站？将连带删除该任务的全部报告（可在回收站恢复）" onConfirm={() => delItem('task', record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const activityColumns = [
    { title: '时间', dataIndex: 'created_at', width: 140, render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    { title: '标题', dataIndex: 'title', width: 240, render: (v) => <Text strong>{v}</Text> },
    { title: '摘要', dataIndex: 'summary', render: (v) => v || '—' },
  ]

  const reportColumns = [
    { title: '报告ID', dataIndex: 'report_id', width: 80, render: (v, r) => (r.type === 'profile' || r.type === 'clue' ? '—' : v) },
    { title: '类型', dataIndex: 'type', width: 100, render: (v) => v === 'profile' ? <Tag color="geekblue">企业速览</Tag> : v === 'clue' ? <Tag color="orange">财产线索</Tag> : <Tag color="green">债权尽调</Tag> },
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
      title: '操作', width: 200,
      render: (_, record) => {
        const kind = record.type === 'profile' ? 'profile' : record.type === 'clue' ? 'clue' : 'report'
        const viewUrl = record.type === 'profile'
          ? `/debtor-report/${record.profile_id}`
          : record.type === 'clue'
            ? `/clue-report/${record.clue_id}`
            : `/report/${record.task_id}/${record.report_id}`
        return (
          <Space size={0}>
            <Button type="link" onClick={() => navigate(viewUrl)}>查看报告</Button>
            <Popconfirm
              title={record.type === 'clue' || record.type === 'profile' ? '移入回收站？（可在回收站恢复或清空）' : '移入回收站？（可在回收站恢复或清空）'}
              onConfirm={() => delItem(kind, record.type === 'clue' ? record.clue_id : record.type === 'profile' ? record.profile_id : record.report_id)}>
              <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  const trashColumns = [
    { title: '类型', dataIndex: 'kind', width: 110, render: (v) => { const m = KIND_META[v] || { tag: 'default', label: v }; return <Tag color={m.tag}>{m.label}</Tag> } },
    { title: '名称', dataIndex: 'name', ellipsis: true, render: (v) => <Text strong>{v}</Text> },
    { title: '删除时间', dataIndex: 'deleted_at', width: 150, render: (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '—') },
    {
      title: '操作', width: 280,
      render: (_, it) => (
        <Space size={0} wrap>
          <Button type="link" icon={<UndoOutlined />} onClick={() => doRestore(it)}>恢复</Button>
          <Button type="link" icon={<ReloadOutlined />} onClick={() => doRegenerate(it)}>重新尽调/生成</Button>
          <Button type="link" danger icon={<DeleteOutlined />} onClick={() => doClear(it)}>清空</Button>
        </Space>
      ),
    },
  ]

  const setTab = (key) => setParams(key === 'tasks' ? {} : { tab: key }, { replace: true })

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}>
        <Title level={3} style={{ margin: 0 }}>用户中心</Title>
        <Button icon={<UserOutlined />} onClick={() => navigate('/account')}>账户信息</Button>
      </Space>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'tasks',
            label: `我的任务（${tasks.length + valuations.length + clues.length}）`,
            children: loading ? <Spin /> : (
              <>
                <Card title={<span><Tag color="blue">智能尽调</Tag> 债权尽调任务（{tasks.length}）</span>} style={{ marginBottom: 16 }}>
                  <Table rowKey="id" columns={taskColumns} dataSource={tasks} pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
                </Card>
                <Card title={<span><Tag color="orange">土地厂房估价</Tag> 估价记录（{valuations.length}）</span>} style={{ marginBottom: 16 }}>
                  {valuations.length ? <Table rowKey="id" columns={activityColumns} dataSource={valuations} pagination={{ pageSize: 10 }} /> : <Text type="secondary">暂无估价记录，去「土地厂房估价」试试</Text>}
                </Card>
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
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                  <Input.Search allowClear placeholder="搜索债务人/企业" style={{ width: 240 }} onSearch={(v) => setReportKeyword(v)} />
                </div>
                {/* 2026-09-08: 估价已移出"我的报告"(估价=任务记录, 见"我的任务") */}
                <Card title={<span><Tag color="blue">尽调/速览/线索</Tag> 全部报告（{filteredReports.length}）</span>}>
                  {filteredReports.length
                    ? <Table rowKey="report_id" columns={reportColumns} dataSource={filteredReports} pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
                    : <Text type="secondary">暂无报告</Text>}
                </Card>
              </>
            ),
          },
          {
            key: 'trash',
            label: `回收站（${trashItems.length}）`,
            children: loading ? <Spin /> : (
              <>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                  <Button danger icon={<RestOutlined />} disabled={!trashItems.length} onClick={doClearAll}>清空回收站</Button>
                </div>
                <Card>
                  {trashItems.length
                    ? <Table rowKey={(r) => `${r.kind}-${r.id}`} columns={trashColumns} dataSource={trashItems} pagination={{ pageSize: 10 }} scroll={{ x: 'max-content' }} />
                    : <Text type="secondary">回收站为空。删除的任务/报告会先进入这里，可恢复、重新生成或彻底清空。</Text>}
                </Card>
              </>
            ),
          },
        ]}
      />
    </div>
  )
}
