import { useEffect, useState } from 'react'
import { Card, Table, Tag, Typography, Spin, Button, Space, Modal, Form, Input, InputNumber, Select, message, Upload, Popconfirm, Alert, Row, Col, Collapse } from 'antd'
import { PlusOutlined, UploadOutlined, InboxOutlined, BookOutlined } from '@ant-design/icons'
import client from '../api/client'
import { useAuthStore } from '../store/auth'

const { Title, Text } = Typography
const { TextArea } = Input

const LAND_TYPE_OPTIONS = ['工业', '商业', '住宅', '综合', '仓储', '农业', '公共', '交通'].map((v) => ({ value: v, label: v }))

// 《土地利用现状分类》GB/T 21010-2017 一级类（官方分类指导）
const LAND_CLASSIFICATION = [
  { code: '01', name: '耕地', desc: '水田、水浇地、旱地' },
  { code: '02', name: '园地', desc: '果园、茶园、橡胶园、其他园地' },
  { code: '03', name: '林地', desc: '乔木林地、竹林地、灌木林地、其他林地' },
  { code: '04', name: '草地', desc: '天然牧草地、人工牧草地、其他草地' },
  { code: '05', name: '湿地', desc: '红树林地、森林沼泽、灌丛沼泽、沼泽草地、内陆滩涂、沼泽地、盐田' },
  { code: '06', name: '农业设施建设用地', desc: '乡村道路用地、设施农业用地' },
  { code: '07', name: '居住用地', desc: '城镇住宅用地、农村宅基地' },
  { code: '08', name: '公共管理与公共服务用地', desc: '机关团体、科研、文化、教育、体育、医疗卫生、社会福利、公用设施、公园绿地等' },
  { code: '09', name: '商业服务业用地', desc: '商业用地（零售/批发/餐饮/旅馆）、商务金融用地、娱乐康体用地、其他商业服务业用地' },
  { code: '10', name: '工矿用地', desc: '工业用地、采矿用地' },
  { code: '11', name: '交通运输用地', desc: '铁路、公路、机场、港口码头、管道运输、交通服务等用地' },
  { code: '12', name: '水域及水利设施用地', desc: '河流水面、湖泊水面、水库水面、坑塘水面、沟渠、水工建筑用地等' },
  { code: '13', name: '其他土地', desc: '空闲地、裸土地、裸岩石砾地、田坎、其他' },
]

export default function AdminLandPricePage() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'
  const canWrite = isAdmin || user?.land_price_perm // 增改权限（删除仅 admin）
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState(null) // null / {mode:'create'} / {mode:'edit', record}
  const [form] = Form.useForm()
  const [importModal, setImportModal] = useState(false)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)

  const load = async () => {
    try {
      const resp = await client.get('/admin/land-prices')
      setRecords(resp.data?.records || [])
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setModal({ mode: 'create' })
    form.resetFields()
  }
  const openEdit = (r) => {
    setModal({ mode: 'edit', record: r })
    form.setFieldsValue(r)
  }

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (modal.mode === 'create') {
        await client.post('/admin/land-prices', v)
        message.success('已新增')
      } else {
        await client.put(`/admin/land-prices/${modal.record.id}`, v)
        message.success('已更新')
      }
      setModal(null)
      load()
    } catch { /* 拦截器已提示 */ }
  }

  const remove = async (id) => {
    try {
      await client.delete(`/admin/land-prices/${id}`)
      message.success('已删除')
      load()
    } catch { /* 拦截器已提示 */ }
  }

  // 批量导入：粘贴文本
  const doImportText = async () => {
    if (!importText.trim()) return message.warning('请粘贴土地价格信息')
    setImporting(true)
    try {
      const resp = await client.post('/admin/land-prices/import', null, { params: { text: importText } })
      setImportResult(resp.data)
      message.success(`导入完成：成功 ${resp.data?.saved || 0} 条`)
      load()
    } catch { /* 拦截器已提示 */ } finally {
      setImporting(false)
    }
  }

  // 批量导入：上传文件（Word/Excel/图片）
  const uploadProps = {
    multiple: true,
    showUploadList: false,
    beforeUpload: () => false,
    onChange: async ({ fileList }) => {
      const files = fileList.filter((f) => f.originFileObj).map((f) => f.originFileObj)
      if (!files.length) return
      setImporting(true)
      try {
        const formData = new FormData()
        files.forEach((f) => formData.append('files', f))
        const resp = await client.post('/admin/land-prices/import', formData, { timeout: 180000 })
        setImportResult(resp.data)
        message.success(`导入完成：成功 ${resp.data?.saved || 0} 条`)
        load()
      } catch { /* 拦截器已提示 */ } finally {
        setImporting(false)
      }
    },
  }

  const columns = [
    { title: '省', dataIndex: 'province', width: 80, render: (v) => v || '—' },
    { title: '市', dataIndex: 'city', width: 100, render: (v) => v || '—' },
    { title: '区县', dataIndex: 'district', width: 110, render: (v) => v || '—' },
    { title: '土地性质', dataIndex: 'land_type', width: 90, render: (v) => <Tag color="blue">{v}</Tag> },
    { title: '单价下限(元/㎡)', dataIndex: 'price_lo', width: 120, align: 'right' },
    { title: '单价上限(元/㎡)', dataIndex: 'price_hi', width: 120, align: 'right' },
    { title: '来源', dataIndex: 'source', ellipsis: true },
    { title: '生效日期', dataIndex: 'effective_date', width: 100, render: (v) => v || '—' },
    {
      title: '操作', width: 140,
      render: (_, r) => (
        <Space>
          {canWrite && <Button size="small" onClick={() => openEdit(r)}>编辑</Button>}
          {isAdmin && (
            <Popconfirm title="确认删除？" onConfirm={() => remove(r.id)}>
              <Button size="small" danger>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Title level={3} style={{ margin: 0 }}>土地价格库</Title>
        <Space>
          <Button icon={<InboxOutlined />} onClick={() => setImportModal(true)}>批量导入</Button>
          {canWrite && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增</Button>}
        </Space>
      </div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        各地土地出让基准价 / 成交价参考（元/㎡）。抵押物估值时按「地区 + 土地性质」自动匹配；库内无匹配则回退默认档位。土地性质分类参照《土地利用现状分类》GB/T 21010-2017。
      </Text>
      {!canWrite && <Alert type="warning" showIcon message="您只有查看权限（增改需管理员开通土地价格库权限）" style={{ marginBottom: 12 }} />}

      {/* 土地性质分类官方指导（GB/T 21010-2017）*/}
      <Collapse
        ghost
        style={{ marginBottom: 12 }}
        items={[{
          key: 'classify',
          label: <Space><BookOutlined style={{ color: 'var(--primary)' }} /><Text strong>《土地利用现状分类》GB/T 21010-2017 分类指导（官方标准，录入土地性质时参考）</Text></Space>,
          children: (
            <Table
              size="small"
              rowKey="code"
              pagination={false}
              dataSource={LAND_CLASSIFICATION}
              columns={[
                { title: '编码', dataIndex: 'code', width: 60 },
                { title: '一级类', dataIndex: 'name', width: 180 },
                { title: '说明（含主要二级类）', dataIndex: 'desc' },
              ]}
            />
          ),
        }]}
      />

      <Card>
        <Table rowKey="id" columns={columns} dataSource={records} pagination={{ pageSize: 15 }} size="middle" scroll={{ x: 'max-content' }} />
      </Card>

      {/* 新增/编辑弹窗 */}
      <Modal title={modal?.mode === 'create' ? '新增土地参考价' : '编辑土地参考价'} open={modal != null} onOk={save} onCancel={() => setModal(null)} okText="保存" destroyOnClose>
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={8}><Form.Item name="province" label="省"><Input placeholder="如 山东" /></Form.Item></Col>
            <Col span={8}><Form.Item name="city" label="市"><Input placeholder="如 青岛" /></Form.Item></Col>
            <Col span={8}><Form.Item name="district" label="区县（可选）"><Input placeholder="如 城阳" /></Form.Item></Col>
          </Row>
          <Form.Item name="land_type" label="土地性质" rules={[{ required: true, message: '请选择土地性质' }]}>
            <Select options={LAND_TYPE_OPTIONS} placeholder="选择土地性质" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="price_lo" label="单价下限（元/㎡）" rules={[{ required: true, message: '必填' }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="price_hi" label="单价上限（元/㎡）" rules={[{ required: true, message: '必填' }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Form.Item name="source" label="来源"><Input placeholder="如 基准地价公示 / 成交公告 / 人工录入" /></Form.Item>
          <Form.Item name="effective_date" label="生效日期"><Input placeholder="如 2024" /></Form.Item>
          <Form.Item name="note" label="备注"><TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 批量导入弹窗 */}
      <Modal title="批量导入土地价格" open={importModal} onCancel={() => setImportModal(false)} footer={null} width={720}>
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message="支持：粘贴文字 / 上传 Word、Excel、图片（自动识别地区、土地性质、单价并归类；图片需清晰）" />
        <TextArea
          rows={6}
          placeholder={'粘贴格式示例（每行一条）：\n山东-青岛 工业用地 600~1200元/㎡ 基准地价公示\n临沂市兰山区 工业 2000~6000元/㎡ 成交公告\n山东 潍坊 工业 30万/亩~50万/亩'}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" loading={importing} onClick={doImportText}>解析粘贴文本</Button>
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />} loading={importing}>上传文件（Word/Excel/图片）</Button>
          </Upload>
        </Space>
        {importResult && (
          <div style={{ marginTop: 12 }}>
            <Alert
              type="success" showIcon
              message={`成功 ${importResult.saved} 条 / 解析 ${importResult.parsed} 条${importResult.skipped ? ` / 跳过 ${importResult.skipped}` : ''}`}
            />
            {importResult.parse_errors?.length > 0 && (
              <div style={{ marginTop: 8 }}>
                {importResult.parse_errors.map((e, i) => <div key={i} style={{ fontSize: 12, color: '#cf1322' }}>⚠️ {e}</div>)}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
