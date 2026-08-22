import { useEffect, useState } from 'react'
import { Tabs, Table, Button, Modal, Form, Input, InputNumber, Select, Switch, Space, message, Popconfirm } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { adminDataApi } from '../api'

/** 管理后台：市场数据管理（宏观KPI / 拍卖平台 / AMC） */
export default function AdminDataPage() {
  const [activeTab, setActiveTab] = useState('macro')
  const [data, setData] = useState({ macro: [], auction: [], amc: [] })
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const [m, a, c] = await Promise.all([
        adminDataApi.listMacroKpis(),
        adminDataApi.listAuctionStats(),
        adminDataApi.listAmcStats(),
      ])
      setData({ macro: m.data?.items || [], auction: a.data?.items || [], amc: c.data?.items || [] })
    } catch { /* 错误已由拦截器提示 */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (record) => {
    setEditing(record)
    form.setFieldsValue({ ...record, trend_up: record.trend_up === 1 })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    // Switch 返回 boolean，后端需要 0/1
    if (activeTab === 'macro' && typeof values.trend_up === 'boolean') {
      values.trend_up = values.trend_up ? 1 : 0
    }
    try {
      if (activeTab === 'macro') {
        if (editing) await adminDataApi.updateMacroKpi(editing.id, values)
        else await adminDataApi.createMacroKpi(values)
      } else if (activeTab === 'auction') {
        if (editing) await adminDataApi.updateAuctionStat(editing.id, values)
        else await adminDataApi.createAuctionStat(values)
      } else {
        if (editing) await adminDataApi.updateAmcStat(editing.id, values)
        else await adminDataApi.createAmcStat(values)
      }
      message.success('已保存')
      setModalOpen(false)
      load()
    } catch { /* 拦截器已提示 */ }
  }

  const handleDelete = async (id) => {
    try {
      if (activeTab === 'macro') await adminDataApi.deleteMacroKpi(id)
      else if (activeTab === 'auction') await adminDataApi.deleteAuctionStat(id)
      else await adminDataApi.deleteAmcStat(id)
      message.success('已删除')
      load()
    } catch { /* 拦截器已提示 */ }
  }

  const commonTableProps = {
    size: 'small',
    loading,
    pagination: { pageSize: 10, showTotal: (t) => `共 ${t} 条` },
    scroll: { x: 800 },
  }

  const actionCol = {
    title: '操作',
    key: 'action',
    width: 140,
    render: (_, record) => (
      <Space>
        <Button type="link" size="small" onClick={() => openEdit(record)}>编辑</Button>
        <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
          <Button type="link" size="small" danger>删除</Button>
        </Popconfirm>
      </Space>
    ),
  }

  const macroColumns = [
    { title: '类型', dataIndex: 'category', width: 80, render: (v) => (v === 'macro' ? '宏观' : 'KPI') },
    { title: '名称', dataIndex: 'label' },
    { title: '数值', dataIndex: 'value', width: 100 },
    { title: '单位', dataIndex: 'unit', width: 70 },
    { title: '趋势', dataIndex: 'trend', width: 140 },
    { title: '排序', dataIndex: 'sort', width: 70 },
    { title: '来源', dataIndex: 'source', ellipsis: true },
    actionCol,
  ]

  const auctionColumns = [
    { title: '平台', dataIndex: 'platform' },
    { title: '周期', dataIndex: 'period', width: 100 },
    { title: '上拍数', dataIndex: 'on_auction', width: 100, align: 'right' },
    { title: '成交数', dataIndex: 'sold', width: 100, align: 'right' },
    { title: '成交率%', dataIndex: 'sold_rate', width: 100, align: 'right' },
    { title: '成交额(万)', dataIndex: 'amount', width: 120, align: 'right' },
    actionCol,
  ]

  const amcColumns = [
    { title: '机构', dataIndex: 'org_name', ellipsis: true },
    { title: '范围', dataIndex: 'scope', width: 80, render: (v) => (v === 'national' ? '全国' : '地方') },
    { title: '周期', dataIndex: 'period', width: 100 },
    { title: '挂牌笔数', dataIndex: 'listed_count', width: 100, align: 'right' },
    { title: '份额%', dataIndex: 'market_share', width: 100, align: 'right' },
    { title: '趋势', dataIndex: 'trend', width: 90, render: (v) => ({ up: '↑ 上升', down: '↓ 下降', flat: '→ 平稳' }[v] || v) },
    actionCol,
  ]

  return (
    <div className="page-container">
      <div className="section-card">
        <div className="section-title">市场数据管理</div>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            { key: 'macro', label: '宏观指标 / KPI', children: <></> },
            { key: 'auction', label: '拍卖平台数据', children: <></> },
            { key: 'amc', label: 'AMC 机构数据', children: <></> },
          ]}
          tabBarExtraContent={
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增{activeTab === 'macro' ? '指标' : activeTab === 'auction' ? '平台' : '机构'}
            </Button>
          }
        />
        <div style={{ marginTop: 8 }}>
          {activeTab === 'macro' && <Table {...commonTableProps} columns={macroColumns} dataSource={data.macro} rowKey="id" />}
          {activeTab === 'auction' && <Table {...commonTableProps} columns={auctionColumns} dataSource={data.auction} rowKey="id" />}
          {activeTab === 'amc' && <Table {...commonTableProps} columns={amcColumns} dataSource={data.amc} rowKey="id" />}
        </div>
      </div>

      <Modal
        title={editing ? '编辑' : '新增'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          {activeTab === 'macro' && (
            <>
              <Form.Item name="category" label="类型" rules={[{ required: true }]}>
                <Select options={[{ value: 'macro', label: '宏观数据条' }, { value: 'kpi', label: 'KPI 卡片' }]} />
              </Form.Item>
              <Form.Item name="label" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                <Input placeholder="如：不良贷款余额" />
              </Form.Item>
              <Form.Item name="value" label="数值" rules={[{ required: true, message: '请输入数值' }]}>
                <Input placeholder="如：3.7" />
              </Form.Item>
              <Form.Item name="unit" label="单位">
                <Input placeholder="如：万亿 / % / 家" />
              </Form.Item>
              <Form.Item name="trend" label="趋势文案（KPI 用）">
                <Input placeholder="如：+3.2% 较上月" />
              </Form.Item>
              <Form.Item name="trend_up" label="趋势方向" valuePropName="checked">
                <Switch checkedChildren="上涨" unCheckedChildren="下跌" defaultChecked />
              </Form.Item>
              <Form.Item name="sort" label="排序">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="source" label="数据来源">
                <Input placeholder="如：金融监管总局" />
              </Form.Item>
            </>
          )}

          {activeTab === 'auction' && (
            <>
              <Form.Item name="platform" label="平台名称" rules={[{ required: true, message: '请输入平台名称' }]}>
                <Input placeholder="如：阿里资产" />
              </Form.Item>
              <Form.Item name="period" label="统计周期" rules={[{ required: true, message: '如 2026-07' }]}>
                <Input placeholder="YYYY-MM" />
              </Form.Item>
              <Form.Item name="on_auction" label="上拍数" rules={[{ required: true }]}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="sold" label="成交数" rules={[{ required: true }]}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="amount" label="成交额（万元）" rules={[{ required: true }]}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {activeTab === 'amc' && (
            <>
              <Form.Item name="org_name" label="机构名称" rules={[{ required: true, message: '请输入机构名称' }]}>
                <Input />
              </Form.Item>
              <Form.Item name="scope" label="范围" rules={[{ required: true }]}>
                <Select options={[{ value: 'national', label: '全国' }, { value: 'local', label: '地方' }]} />
              </Form.Item>
              <Form.Item name="period" label="统计周期" rules={[{ required: true, message: '如 2026-07' }]}>
                <Input placeholder="YYYY-MM" />
              </Form.Item>
              <Form.Item name="listed_count" label="挂牌笔数" rules={[{ required: true }]}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="market_share" label="市场份额（%）" rules={[{ required: true }]}>
                <InputNumber min={0} max={100} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="trend" label="趋势">
                <Select options={[{ value: 'up', label: '↑ 上升' }, { value: 'down', label: '↓ 下降' }, { value: 'flat', label: '→ 平稳' }]} />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </div>
  )
}
