import { useState } from 'react'
import { Card, Checkbox, Button, Tag, Table, InputNumber, Input, Select, Modal, Typography, message, Space, Form } from 'antd'
import { useNavigate } from 'react-router-dom'
import { claimApi, taskApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'

const { Title, Text } = Typography

const COMPLETENESS_META = {
  green: { color: 'green', label: '🟢 完整' },
  yellow: { color: 'orange', label: '🟡 少量缺失' },
  red: { color: 'red', label: '🔴 缺少关键字段' },
}

const GUARANTY_OPTIONS = ['抵押', '保证', '质押', '信用'].map((v) => ({ value: v, label: v }))

export default function PreviewPage() {
  const navigate = useNavigate()
  const { claims, warnings, updateClaim } = useClaimDraftStore()
  const [selected, setSelected] = useState([])
  const [saving, setSaving] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [editTarget, setEditTarget] = useState(null) // 当前编辑的 claim
  const [editForm] = Form.useForm()

  if (claims.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Title level={4}>没有待确认的债权信息</Title>
        <Button type="primary" onClick={() => navigate('/upload')}>去输入</Button>
      </div>
    )
  }

  const toggle = (id, disabled) => {
    if (disabled) return
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const saveOnly = async () => {
    setSaving(true)
    try {
      await taskApi.saveOnly(selected)
      message.success('已保存到我的任务')
      navigate('/tasks')
    } catch { /* 拦截器已提示 */ } finally {
      setSaving(false)
    }
  }

  const startDD = async () => {
    setSaving(true)
    try {
      const resp = await taskApi.create(selected)
      navigate(`/progress/${resp.data.id}`)
    } catch { /* 拦截器已提示 */ } finally {
      setSaving(false)
    }
  }

  const columns = [
    {
      title: '选择',
      width: 70,
      render: (_, record) => {
        const disabled = record.completeness === 'red'
        return (
          <Checkbox
            checked={selected.includes(record.id)}
            disabled={disabled}
            onChange={() => toggle(record.id, disabled)}
          />
        )
      },
    },
    {
      title: '债务人',
      dataIndex: 'debtor_name',
      render: (v) => v || <Text type="danger">缺失</Text>,
    },
    {
      title: '本金（元）',
      dataIndex: 'principal_cents',
      render: (v) => (v != null ? (v / 100).toLocaleString() : <Text type="danger">缺失</Text>),
    },
    {
      title: '抵押物',
      dataIndex: 'collateral',
      ellipsis: true,
      render: (v) => v || <Text type="danger">缺失</Text>,
    },
    {
      title: '利息（元）',
      dataIndex: 'interest_cents',
      render: (v) => (v != null ? (v / 100).toLocaleString() : '未知'),
    },
    {
      title: '担保类型',
      dataIndex: 'guaranty_type',
      render: (v) => v || '未知',
    },
    {
      title: '完整度',
      dataIndex: 'completeness',
      width: 120,
      render: (v) => {
        const meta = COMPLETENESS_META[v] || COMPLETENESS_META.red
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '缺失字段',
      dataIndex: 'missing_fields',
      render: (v) => (Array.isArray(v) && v.length ? v.join('、') : '—'),
    },
    {
      title: '操作',
      width: 120,
      render: (_, record) => (
        <Button size="small" onClick={() => onEdit(record)}>编辑</Button>
      ),
    },
  ]

  const onEdit = (record) => {
    setEditTarget(record)
    editForm.setFieldsValue({
      debtor_name: record.debtor_name,
      principal: record.principal_cents != null ? record.principal_cents / 100 : undefined,
      interest: record.interest_cents != null ? record.interest_cents / 100 : undefined,
      guaranty_type: record.guaranty_type,
      collateral: record.collateral,
    })
  }

  const saveEdit = async () => {
    const values = await editForm.validateFields()
    const patch = {
      debtor_name: values.debtor_name,
      principal_cents: values.principal != null ? Math.round(values.principal * 100) : null,
      interest_cents: values.interest != null ? Math.round(values.interest * 100) : null,
      guaranty_type: values.guaranty_type || null,
      collateral: values.collateral || null,
    }
    // 本地更新 + 同步后端（失败不阻塞）；后端返回重算后的完整度
    updateClaim(editTarget.id, patch)
    try {
      const resp = await claimApi.update(editTarget.id, patch)
      updateClaim(editTarget.id, {
        completeness: resp.data?.completeness,
        missing_fields: resp.data?.missing_fields,
      })
      message.success('已更新')
    } catch {
      message.warning('已本地更新，但同步服务器失败，可稍后重试')
    }
    setEditTarget(null)
  }

  const selectedCount = selected.length
  const estPoints = selectedCount * 100

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px', paddingBottom: 120 }}>
      <Title level={3}>信息预处理确认</Title>
      <Text type="secondary">AI 已从输入中提取以下债权信息，请核对并勾选需要尽调的记录（最多 5 条）。关键字段（债务人/本金/抵押物）齐全才可尽调，缺失的标红且不可勾选，可点「编辑」补全。</Text>

      {/* 输入质量提醒 */}
      {warnings && warnings.length > 0 && (
        <Alert
          style={{ marginTop: 16 }}
          type={warnings.some((w) => w.level === 'error') ? 'error' : warnings.some((w) => w.level === 'warning') ? 'warning' : 'info'}
          showIcon
          message="输入质量提醒（请先核对，避免在错误信息上浪费尽调资源）"
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {warnings.map((w, i) => (
                <li key={i} style={{ marginBottom: 4 }}>{w.text}</li>
              ))}
            </ul>
          }
        />
      )}

      <Card style={{ marginTop: 16 }}>
        <Table rowKey="id" columns={columns} dataSource={claims} pagination={false} size="middle" />
      </Card>

      {/* 底部固定操作栏 */}
      <div
        style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          background: '#fff', boxShadow: '0 -2px 8px rgba(0,0,0,.08)',
          padding: '12px 24px', display: 'flex', justifyContent: 'center', gap: 16, zIndex: 10,
        }}
      >
        <Space size="large" align="center">
          <Text strong>已选 {selectedCount}/5 条</Text>
          <Text type="secondary">预估 {estPoints} 积分</Text>
          <Button onClick={saveOnly} loading={saving} disabled={selectedCount === 0}>
            仅保存到我的任务
          </Button>
          <Button
            type="primary"
            disabled={selectedCount === 0}
            loading={saving}
            onClick={() => setConfirmOpen(true)}
          >
            开始尽调
          </Button>
        </Space>
      </div>

      <Modal
        title="确认开始尽调"
        open={confirmOpen}
        onOk={startDD}
        onCancel={() => setConfirmOpen(false)}
        okText="确认并开始"
        confirmLoading={saving}
      >
        <p>将消耗预估 <Text strong>{estPoints}</Text> 积分（一期仅展示，不真实扣费）。</p>
        <p>尽调将依次执行：信息提取 → 工商/司法查询 → 法律检索 → 抵押物估值 → 本息计算 → 综合分析。</p>
      </Modal>

      {/* 编辑弹窗 */}
      <Modal
        title={editTarget ? `编辑：${editTarget.debtor_name || '未命名'}` : '编辑'}
        open={editTarget != null}
        onOk={saveEdit}
        onCancel={() => setEditTarget(null)}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="debtor_name" label="债务人名称" rules={[{ required: true, message: '请输入债务人名称' }]}>
            <Input placeholder="企业全称或自然人姓名" />
          </Form.Item>
          <Form.Item name="principal" label="债权本金（元）">
            <InputNumber style={{ width: '100%' }} min={0} placeholder="如 5390000" />
          </Form.Item>
          <Form.Item name="interest" label="利息/罚息（元）">
            <InputNumber style={{ width: '100%' }} min={0} placeholder="可选" />
          </Form.Item>
          <Form.Item name="guaranty_type" label="担保类型">
            <Select allowClear placeholder="选择担保类型" options={GUARANTY_OPTIONS} />
          </Form.Item>
          <Form.Item name="collateral" label="抵押物" rules={[{ required: true, message: '请输入抵押物（尽调关键字段）' }]}>
            <Input.TextArea rows={3} placeholder="抵押物位置/面积/产权证号等" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
