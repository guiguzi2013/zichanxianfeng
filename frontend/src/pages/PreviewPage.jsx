import { useState } from 'react'
import { Card, Checkbox, Button, Tag, Table, InputNumber, Input, Select, Modal, Typography, message, Space, Form, Row, Col, Alert } from 'antd'
import { useNavigate } from 'react-router-dom'
import { claimApi, taskApi } from '../api'
import { useClaimDraftStore } from '../store/claimDraft'

const { Title, Text } = Typography

const COMPLETENESS_META = {
  green: { color: 'green', label: '🟢 完整' },
  yellow: { color: 'orange', label: '🟡 基本可用' },
  red: { color: 'orange', label: '🟠 待补充' },
}

const GUARANTY_OPTIONS = ['抵押', '保证', '质押', '信用'].map((v) => ({ value: v, label: v }))

export default function PreviewPage() {
  const navigate = useNavigate()
  const { claims, warnings, dedup, updateClaim } = useClaimDraftStore()
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

  // 重复债务人判定：dedup 信息来自导入接口
  const batchDupIds = new Set((dedup?.batch_dups || []).map((d) => d.id))          // 同批重复（后出现的，只能勾第一条）
  // 与历史重复：仅当历史同名债权已发起过尽调(有任务/报告)才拦；仅导入过未尽调 → 提示但可正常勾选（2026-09-05）
  const existingDupIds = new Set((dedup?.existing_dups || []).filter((d) => d.started).map((d) => d.id))
  const dupInfoMap = {}
  ;(dedup?.batch_dups || []).forEach((d) => { dupInfoMap[d.id] = `与同批「${d.dup_with}」重复` })
  ;(dedup?.existing_dups || []).forEach((d) => { dupInfoMap[d.id] = `与您历史记录（${d.first_source}）重复，建议先去「我的报告」查看` })

  // 同批同名：只能勾选第一条（首个不在此集合），其余置灰
  const isBatchDup = (id) => batchDupIds.has(id)
  const isExistingDup = (id) => existingDupIds.has(id)
  const isDup = (id) => isBatchDup(id) || isExistingDup(id)

  const toggle = (id, disabled) => {
    if (disabled || isDup(id)) return
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const saveOnly = async () => {
    setSaving(true)
    try {
      // source_claim_ids = 当次导入的全量债权（含未勾选），供"查看录入"显示完整清单
      await taskApi.saveOnly(selected, claims.map((c) => c.id))
      message.success('已保存到我的任务')
      navigate('/tasks')
    } catch { /* 拦截器已提示 */ } finally {
      setSaving(false)
    }
  }

  // 下一步：打开确认弹窗（勾选含重复时弹窗内展示重复提醒）
  const startDD = () => {
    setConfirmOpen(true)
  }

  const doStartDD = async () => {
    setSaving(true)
    try {
      const resp = await taskApi.create(selected, claims.map((c) => c.id))
      navigate(`/progress/${resp.data.id}`)
    } catch { /* 拦截器已提示 */ } finally {
      setSaving(false)
    }
  }

  // 勾选中的重复项（供确认弹窗提示）
  const dupSelectedNames = selected
    .filter((id) => isDup(id))
    .map((id) => {
      const c = claims.find((x) => x.id === id)
      return c ? `${c.debtor_name}（${dupInfoMap[id] || '重复'}）` : ''
    })
    .filter(Boolean)

  const columns = [
    {
      title: '选择',
      width: 80,
      render: (_, record) => {
        const disabled = record.completeness === 'red' || isDup(record.id)
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
      render: (v, record) => (
        <Space direction="vertical" size={2}>
          <span>{v || <Tag color="orange">待补充</Tag>}</span>
          {isBatchDup(record.id) && <Tag color="orange" style={{ marginInlineEnd: 0 }}>同批重复</Tag>}
          {isExistingDup(record.id) && <Tag color="red" style={{ marginInlineEnd: 0 }}>与历史重复</Tag>}
        </Space>
      ),
    },
    {
      title: '本金（元）',
      dataIndex: 'principal_cents',
      render: (v) => (v != null ? (v / 100).toLocaleString() : <Tag color="orange">待补充</Tag>),
    },
    {
      title: '抵押物',
      dataIndex: 'collateral',
      ellipsis: true,
      render: (v) => v || <Tag color="orange">待补充</Tag>,
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
    const extra = record.extra_fields || {}
    editForm.setFieldsValue({
      debtor_name: record.debtor_name,
      principal: record.principal_cents != null ? record.principal_cents / 100 : undefined,
      interest: record.interest_cents != null ? record.interest_cents / 100 : undefined,
      guaranty_type: record.guaranty_type,
      collateral: record.collateral,
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
    // 本地更新 + 同步后端（失败不阻塞）；后端返回重算后的完整度
    updateClaim(editTarget.id, patch)
    try {
      const resp = await claimApi.update(editTarget.id, patch)
      updateClaim(editTarget.id, {
        completeness: resp.data?.completeness,
        missing_fields: resp.data?.missing_fields,
        extra_fields: resp.data?.extra_fields,
      })
      message.success('已更新')
    } catch {
      message.warning('已本地更新，但同步服务器失败，可稍后重试')
    }
    setEditTarget(null)
  }

  const selectedCount = selected.length

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <Title level={3}>信息预处理确认</Title>
      <Text type="secondary">系统已从输入中提取以下债权信息，请核对并勾选需要尽调的记录（最多 5 条）。关键字段（债务人/本金/抵押物）齐全才可尽调，缺失的标红且不可勾选，可点「编辑」补全。</Text>

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

      {/* 重复债权提醒 */}
      {(dedup?.removed > 0 || dedup?.file_duplicate || (dedup?.batch_dups || []).length > 0 || (dedup?.existing_dups || []).length > 0) && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message="重复检测提醒"
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {dedup?.file_duplicate && <li>该文件此前已上传过，建议先去「我的任务」查看已有记录</li>}
              {dedup?.removed > 0 && <li>已剔除 {dedup.removed} 条重复债务人（同名只保留第一条）</li>}
              {(dedup?.batch_dups || []).length > 0 && <li>同一批内有 {(dedup.batch_dups).length} 条重复债务人（标记「同批重复」），只能勾选其中一条</li>}
              {(dedup?.existing_dups || []).length > 0 && <li>{(dedup.existing_dups).length} 条与您历史债权/报告中的债务人重复（标记「与历史重复」），建议先去「我的报告」查看</li>}
            </ul>
          }
        />
      )}

      <Card style={{ marginTop: 16 }}>
        {/* 操作栏：位于表格上方（用户指定位置，替代原底部固定栏） */}
        <div
          style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginBottom: 12, flexWrap: 'wrap', gap: 8,
          }}
        >
          <Space size="large" align="center">
            <Text strong>已选 {selectedCount}/5 条</Text>
          </Space>
          <Space>
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
        <Table rowKey="id" columns={columns} dataSource={claims} pagination={false} size="middle" />
      </Card>

      <Modal
        title="确认开始尽调"
        open={confirmOpen}
        onOk={doStartDD}
        onCancel={() => setConfirmOpen(false)}
        okText="确认并开始"
        confirmLoading={saving}
      >
        {dupSelectedNames.length > 0 && (
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message="以下债权与您先前的债务人重复，建议先去「我的任务」或「我的报告」查看后再决定："
            description={<ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{dupSelectedNames.map((n, i) => <li key={i}>{n}</li>)}</ul>}
          />
        )}
        <p>尽调将依次执行：信息提取 → 工商/司法查询 → 法律检索 → 抵押物分析 → 本息计算 → 综合分析。</p>
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
