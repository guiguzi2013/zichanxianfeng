import { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Typography, Spin, message, Modal, Form, Input, InputNumber, Select, Checkbox, Alert, Row, Col, Space, Popconfirm } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons'
import { taskApi, claimApi, reportApi } from '../api'

const { Title, Text } = Typography

const GUARANTY_OPTIONS = ['抵押', '保证', '质押', '信用'].map((v) => ({ value: v, label: v }))

/** 任务原始录入界面：字段可点击编辑补齐；未尽调可勾选发起新尽调；已尽调且修改过的可单选重新尽调 */
export default function TaskClaimsPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [claims, setClaims] = useState([])
  const [task, setTask] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedNew, setSelectedNew] = useState([])
  const [saving, setSaving] = useState(false)
  const [rediligencing, setRediligencing] = useState(null)

  // 编辑弹窗（所有债权均可编辑补齐字段）
  const [editTarget, setEditTarget] = useState(null)
  const [editForm] = Form.useForm()

  useEffect(() => {
    const load = async () => {
      try {
        const [t, c] = await Promise.all([taskApi.get(taskId), taskApi.claims(taskId)])
        setTask(t.data)
        setClaims(c.data.claims || [])
      } catch { /* 拦截器已提示 */ } finally {
        setLoading(false)
      }
    }
    load()
  }, [taskId])

  const startNewDD = async () => {
    if (!selectedNew.length) return message.warning('请勾选需要尽调的债权')
    setSaving(true)
    try {
      const allIds = claims.map((c) => c.id)
      const resp = await taskApi.create(selectedNew, allIds)
      message.success(`已发起新尽调（${selectedNew.length} 条债权）`)
      navigate(`/progress/${resp.data.id}`)
    } catch { /* 拦截器已提示 */ } finally {
      setSaving(false)
    }
  }

  // 查看已尽调债权的报告
  const viewReport = (claim) => {
    if (claim.report_task_id) {
      navigate(`/report/${claim.report_task_id}/${claim.report_id}`)
    } else {
      message.info('该债权报告暂未找到')
    }
  }

  // 重新尽调（已尽调且用户修改过 → 单选）
  const rediligence = async (claim) => {
    if (!claim.report_id) return message.warning('该债权报告暂未找到，无法重新尽调')
    setRediligencing(claim.id)
    try {
      const resp = await reportApi.rediligence(claim.report_id)
      message.success(resp.data?.message || '重新尽调已启动，完成后可查看新版本报告')
    } catch { /* 拦截器已提示 */ } finally {
      setRediligencing(null)
    }
  }

  const openEdit = (record) => {
    setEditTarget(record)
    const extra = record.extra_fields || {}
    editForm.setFieldsValue({
      debtor_name: record.debtor_name,
      principal: record.principal_cents != null ? record.principal_cents / 100 : undefined,
      interest: record.interest_cents != null ? record.interest_cents / 100 : undefined,
      guaranty_type: record.guaranty_type,
      collateral: record.collateral,
      judicial_status: record.judicial_status,
      region: extra.region,
      collateral_type: extra.collateral_type,
      interest_base_date: extra.interest_base_date,
      land_area_sqm: extra.land_area_sqm,
      building_area_sqm: extra.building_area_sqm,
      build_year: extra.build_year,
      structure_type: extra.structure_type,
      property_cert_no: extra.property_cert_no,
      property_owner: extra.property_owner,
      property_use: extra.property_use,
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
      judicial_status: values.judicial_status || null,
      extra_fields: {
        region: values.region,
        collateral_type: values.collateral_type,
        interest_base_date: values.interest_base_date,
        land_area_sqm: values.land_area_sqm,
        building_area_sqm: values.building_area_sqm,
        build_year: values.build_year,
        structure_type: values.structure_type,
        property_cert_no: values.property_cert_no,
        property_owner: values.property_owner,
        property_use: values.property_use,
      },
    }
    try {
      const resp = await claimApi.update(editTarget.id, patch)
      setClaims((prev) => prev.map((c) => (c.id === editTarget.id ? {
        ...c, ...patch,
        user_edited: true,
        completeness: resp.data?.completeness,
        missing_fields: resp.data?.missing_fields,
        extra_fields: resp.data?.extra_fields,
      } : c)))
      // 已尽调且修改过 → 提示可重新尽调
      if (editTarget.diligence_done) {
        message.success('已更新。该债权已尽调过，如需生效请点击「重新尽调」重新生成报告')
      } else {
        message.success('已更新')
      }
    } catch { /* 拦截器已提示 */ }
    setEditTarget(null)
  }

  const columns = [
    {
      title: '状态',
      width: 90,
      render: (_, r) => r.diligence_done
        ? <Tag color={r.user_edited ? 'purple' : 'success'}>{r.user_edited ? '已尽调·已修改' : '已尽调'}</Tag>
        : <Tag color="default">未尽调</Tag>,
    },
    {
      title: '选择',
      width: 60,
      render: (_, r) => (
        <Checkbox
          checked={r.diligence_done || selectedNew.includes(r.id)}
          disabled={r.diligence_done}
          onChange={(e) => {
            if (r.diligence_done) return
            setSelectedNew((prev) => (e.target.checked ? [...prev, r.id] : prev.filter((x) => x !== r.id)))
          }}
        />
      ),
    },
    {
      title: '债务人（点击可修改）',
      dataIndex: 'debtor_name',
      render: (v, r) => (
        <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => openEdit(r)}>
          {v || <Tag color="orange">待补充（点击填写）</Tag>}
        </Button>
      ),
    },
    { title: '本金（元）', dataIndex: 'principal_cents', width: 110, render: (v, r) => (
      <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => openEdit(r)}>
        {v != null ? (v / 100).toLocaleString() : <Text type="secondary">—（点击填）</Text>}
      </Button>
    ) },
    { title: '抵押物', dataIndex: 'collateral', ellipsis: true, render: (v, r) => (
      <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => openEdit(r)}>
        {v || <Text type="secondary">—（点击填）</Text>}
      </Button>
    ) },
    { title: '担保方式', dataIndex: 'guaranty_type', width: 90, render: (v, r) => (
      <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => openEdit(r)}>
        {v || <Text type="secondary">—</Text>}
      </Button>
    ) },
    {
      title: '操作',
      width: 130,
      render: (_, r) => r.diligence_done
        ? (r.user_edited
          ? <Space size={4}>
              <Button size="small" onClick={() => viewReport(r)}>查看</Button>
              <Popconfirm title="用最新修改的字段重新生成报告？" onConfirm={() => rediligence(r)}>
                <Button size="small" type="primary" icon={<ReloadOutlined />} loading={rediligencing === r.id}>重新尽调</Button>
              </Popconfirm>
            </Space>
          : <Button size="small" onClick={() => viewReport(r)}>查看</Button>)
        : <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>,
    },
  ]

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 80px' }}>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/tasks')}>返回我的任务</Button>
      </Space>
      <Title level={3} style={{ marginBottom: 4 }}>任务 #{taskId}：{task?.name || '债权录入'}</Title>

      {/* 醒目提示：可编辑字段 / 重新尽调 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="💡 点击表格中的字段可直接修改补齐（债务人 / 本金 / 抵押物 / 担保方式等）"
        description={
          <span>
            未尽调的债权可勾选发起尽调；已尽调的债权修改字段后，可点击「重新尽调」用最新信息重新生成报告
            （历史版本保留，可在报告中查看）。已尽调且未修改的债权不可重复尽调。
          </span>
        }
      />

      <Card style={{ marginTop: 16 }}>
        <Table rowKey="id" columns={columns} dataSource={claims} pagination={false} size="middle" />
        <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
          <Button type="primary" disabled={!selectedNew.length} loading={saving} onClick={startNewDD}>
            发起新尽调（已选 {selectedNew.length} 条）
          </Button>
        </div>
      </Card>

      {/* 编辑弹窗（所有债权均可补全信息） */}
      <Modal title={`编辑债权信息${editTarget?.diligence_done ? '（已尽调，修改后可重新尽调）' : ''}`}
        open={editTarget != null} onOk={saveEdit} onCancel={() => setEditTarget(null)} okText="保存" destroyOnClose>
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
          <Form.Item name="judicial_status" label="司法状态">
            <Select allowClear placeholder="如 未诉 / 已诉 / 执行中 / 终本" options={['未诉', '已诉', '已判决', '执行中', '执行终结', '终本'].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item name="region" label="地区">
            <Input placeholder="如 山东-青岛（可选）" />
          </Form.Item>
          <Form.Item name="collateral_type" label="抵押物类型">
            <Select allowClear placeholder="如 住宅/商铺/工业厂房/土地" options={['住宅', '商铺', '商业', '写字楼', '厂房', '工业', '土地', '别墅', '设备'].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Row gutter={12}>
            <Col xs={12} md={8}>
              <Form.Item name="land_area_sqm" label="土地面积（㎡）" tooltip="工业抵押物估值用：土地出让价×面积">
                <InputNumber style={{ width: '100%' }} min={0} placeholder="可选" />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="building_area_sqm" label="建筑面积（㎡）" tooltip="工业抵押物估值用：建安造价×面积×折旧">
                <InputNumber style={{ width: '100%' }} min={0} placeholder="可选" />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="build_year" label="建成年份" tooltip="用于建筑折旧（20年直线折旧），如 2010">
                <InputNumber style={{ width: '100%' }} min={1950} max={2100} placeholder="可选" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="structure_type" label="建筑结构" tooltip="影响建安造价；轻钢600~1000、重钢1000~1500、砖混800~1200元/㎡">
            <Select allowClear placeholder="如 轻钢/重钢/砖混（可选）" options={['light_steel', 'heavy_steel', 'brick'].map((v) => ({ value: v, label: { light_steel: '轻钢结构', heavy_steel: '重钢结构', brick: '砖混/框架' }[v] }))} />
          </Form.Item>
          <Row gutter={12}>
            <Col xs={12} md={8}>
              <Form.Item name="property_cert_no" label="产权证号" tooltip="房产证/不动产权证号，如 京房权证朝字第123456号">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="property_owner" label="权利人" tooltip="证载权利人（可能是债务人或抵押人）">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
            <Col xs={12} md={8}>
              <Form.Item name="property_use" label="房屋用途" tooltip="住宅/商业/办公/工业/厂房/仓储等">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="interest_base_date" label="计息起始日" tooltip="无判决书时按此日起算利息（LPR估算）；缺失则无法计算利息">
            <Input placeholder="如 2022-03-15（可选，但影响利息计算）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
