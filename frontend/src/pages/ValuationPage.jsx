import { useState } from 'react'
import { Card, Input, Button, Typography, Form, Select, InputNumber, Descriptions, Tag, Alert, Divider, Row, Col, message, Upload, Tooltip, Modal } from 'antd'
import { CalculatorOutlined, EnvironmentOutlined, ExperimentOutlined, BulbOutlined, UploadOutlined, FileProtectOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { valuationApi } from '../api'
import client from '../api/client'
import { useAuthStore } from '../store/auth'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const fmtWan = (cents) => (cents != null ? `${(cents / 100 / 10000).toFixed(4)} 万元` : '—')
const fmtYuan = (cents) => (cents != null ? `¥${(cents / 100).toLocaleString()}` : '—')

const STRUCTURE_OPTIONS = [
  { value: 'light_steel', label: '轻钢结构（600~1000元/㎡）' },
  { value: 'heavy_steel', label: '重钢结构（1000~1500元/㎡）' },
  { value: 'brick', label: '砖混/框架（800~1200元/㎡）' },
  { value: 'unknown', label: '未知结构（平均档700~1100元/㎡）' },
]

export default function ValuationPage({ mode = 'industrial' }) {
  const isCommercial = mode === 'commercial'
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const [form] = Form.useForm()
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  const onEstimate = async (values) => {
    if (!values.collateral_text || values.collateral_text.trim().length < 5) {
      return message.warning('请填写抵押物描述（至少包含抵押物类型与面积）')
    }
    // 未登录：可浏览页面/查看估价说明，发起估价需先登录
    if (!token) {
      Modal.confirm({
        title: '登录后即可估价',
        content: '发起估价将保存估价记录，请先登录。（未登录可浏览估价页面与说明）',
        okText: '去登录',
        cancelText: '取消',
        onOk: () => navigate('/login'),
      })
      return
    }
    setLoading(true)
    try {
      const resp = await valuationApi.estimate({
        collateral_text: values.collateral_text,
        collateral_type: isCommercial ? '商业' : (values.collateral_type || '工业'),
        region: values.region || null,
        land_area_sqm: values.land_area_sqm ?? null,
        building_area_sqm: values.building_area_sqm ?? null,
        structure_type: values.structure_type || null,
        build_year: values.build_year ?? null,
      })
      setResult(resp.data)
      message.success(isCommercial ? '商业房产估值完成' : '估值完成（成本法粗估）')
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  const v = result?.valuation || {}
  const land = result?.land
  const building = result?.building
  const isCost = result?.method === 'cost'

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px 48px' }}>
      <Title level={3} style={{ marginBottom: 4 }}>{isCommercial ? '商业房产估价' : '土地厂房估价'}</Title>
      <Text type="secondary">{isCommercial
        ? '商业房产按市场价区间粗估，取最低价（经济下行口径）。估算结果仅供参考，不替代专业评估。'
        : '成本法粗估：土地出让价 + 建筑建安造价 × 折旧（20年/残值5%）。估算结果仅供参考，不替代专业评估。'}</Text>

      <Card style={{ marginTop: 16 }}>
        <Form form={form} layout="vertical" onFinish={onEstimate}>
          <Form.Item
            name="collateral_text"
            label="抵押物描述"
            rules={[{ required: true, message: '请填写抵押物描述' }]}
            extra={isCommercial
              ? '建议写明：类型（商业房产/商铺/写字楼）、建筑面积。例：青岛市市北区XX路商业网点，建筑面积687.34㎡'
              : '建议写明：类型（工业/厂房/土地）、土地总面积、建筑面积、建成年份（如建于2010年）。例：青岛市黄岛区XX路工业厂房，土地总面积4881平方米，建筑面积5306平方米，建于2010年'}
          >
            <TextArea rows={4} placeholder={isCommercial ? '粘贴或输入商业房产描述…' : '粘贴或输入抵押物描述…'} />
          </Form.Item>

          <Row gutter={12}>
            {!isCommercial && (
              <Col xs={24} md={8}>
                <Form.Item name="collateral_type" label="抵押物类型">
                  <Select allowClear placeholder="工业土地厂房" options={[
                    { value: '工业', label: '工业土地厂房' },
                  ]} />
                </Form.Item>
              </Col>
            )}
            <Col xs={24} md={isCommercial ? 12 : 8}>
              <Form.Item name="region" label="地区（影响单价档位）">
                <Input placeholder="如：山东青岛" prefix={<EnvironmentOutlined />} />
              </Form.Item>
            </Col>
            {!isCommercial && (
              <Col xs={24} md={8}>
                <Form.Item name="structure_type" label="建筑结构">
                  <Select allowClear placeholder="自动识别" options={STRUCTURE_OPTIONS} />
                </Form.Item>
              </Col>
            )}
          </Row>

          <Row gutter={12}>
            {!isCommercial && (
              <Col xs={12} md={6}>
                <Form.Item name="land_area_sqm" label={<span>土地面积（㎡）<Text type="secondary" style={{ fontSize: 12 }}>可选</Text></span>}>
                  <InputNumber min={0} style={{ width: '100%' }} placeholder="自动提取" />
                </Form.Item>
              </Col>
            )}
            <Col xs={12} md={isCommercial ? 8 : 6}>
              <Form.Item name="building_area_sqm" label={<span>{isCommercial ? '建筑面积（㎡）' : '建筑面积（㎡）'}<Text type="secondary" style={{ fontSize: 12 }}>可选</Text></span>}>
                <InputNumber min={0} style={{ width: '100%' }} placeholder="自动提取" />
              </Form.Item>
            </Col>
            {!isCommercial && (
              <Col xs={12} md={6}>
                <Form.Item name="build_year" label={<span>建成年份<Text type="secondary" style={{ fontSize: 12 }}>可选</Text></span>}>
                  <InputNumber min={1950} max={2100} style={{ width: '100%' }} placeholder="如 2010" />
                </Form.Item>
              </Col>
            )}
            <Col xs={12} md={isCommercial ? 8 : 6} style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: 24 }}>
              <Button type="primary" icon={<CalculatorOutlined />} htmlType="submit" loading={loading} block>
                {isCommercial ? '开始估价' : '开始估价'}
              </Button>
            </Col>
          </Row>
        </Form>

        <Alert
          type="info"
          showIcon
          icon={<BulbOutlined />}
          message="估价说明"
          description={isCommercial
            ? '商业房产（商铺/商业网点/写字楼）按公开市场单价区间粗估（15000~50000元/㎡），取最低价作为主参考（经济下行口径）。市场价波动大，不替代专业评估报告。'
            : '土地按各地出让价区间粗估（沿海 600~1200元/㎡、内地 450~750元/㎡、未知地区取全国中值）；建筑按建安造价粗估（轻钢600~1000、重钢1000~1500、砖混800~1200元/㎡）；折旧按房屋建筑物 20 年、残值 5% 直线折旧（年 4.75%）。只有土地算土地，有土地+建筑则合计。具体参数后期将按公示数据细化。'}
        />

        {/* 证件上传（房产证/土地证存档，供人工核对面积与建成年份） */}
        <Card size="small" title={<span><FileProtectOutlined style={{ color: 'var(--primary)', marginRight: 6 }} />补充证件（可选）</span>} style={{ marginTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 12.5, display: 'block', marginBottom: 8 }}>
            上传房产证 / 土地证照片或扫描件，系统存档供人工核对土地面积、建筑面积与建成年份，提升估值准确性（当前仅存档，不自动解析）。
          </Text>
          <Upload
            multiple
            beforeUpload={(file, fileList) => {
              const formData = new FormData()
              fileList.forEach((f) => formData.append('files', f))
              // 后端校验+存档；这里手动控制请求
              return false
            }}
            onChange={async ({ fileList }) => {
              // 只在新增/移除完成时触发上传（简化：选中即上传）
              const last = fileList[fileList.length - 1]
              if (!last || last.originFileObj === undefined) return
              const formData = new FormData()
              fileList.forEach((f) => f.originFileObj && formData.append('files', f.originFileObj))
              try {
                const resp = await client.post('/valuation/upload-docs', formData, { timeout: 120000 })
                message.success(resp.data?.message || '证件已存档')
              } catch { /* 拦截器已提示 */ }
            }}
          >
            <Button icon={<UploadOutlined />}>上传房产证/土地证</Button>
          </Upload>
        </Card>
      </Card>

      {result && v && (
        <Card title={<span><ExperimentOutlined style={{ color: 'var(--primary)' }} /> 估值结果（{isCost ? '成本法粗估' : '市场价区间粗估'}）</span>} style={{ marginTop: 16 }}>
          {v.reference_cents != null && (
            <div style={{ marginBottom: 16, padding: '12px 16px', borderRadius: 8, background: 'linear-gradient(135deg, #1B6FE8, #3D8BF5)', color: '#fff' }}>
              <div style={{ fontSize: 12, opacity: 0.9 }}>{v.reference_label || '主参考估值'}</div>
              <div style={{ fontSize: 24, fontWeight: 700, marginTop: 2 }}>{fmtWan(v.reference_cents)}</div>
              <div style={{ fontSize: 11, opacity: 0.85 }}>{fmtYuan(v.reference_cents)} · 经济下行口径取档（商业最低价 / 工业中间值）</div>
            </div>
          )}
          <Row gutter={[16, 16]}>
            <Col xs={24} md={8}>
              <div className="kpi-card" style={{ textAlign: 'center', padding: '16px 8px' }}>
                <div className="kpi-label">保守估值</div>
                <div className="kpi-value" style={{ fontSize: 20, color: 'var(--text-main)' }}>{fmtWan(v.conservative_cents)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>{fmtYuan(v.conservative_cents)}</div>
              </div>
            </Col>
            <Col xs={24} md={8}>
              <div className="kpi-card" style={{ textAlign: 'center', padding: '16px 8px' }}>
                <div className="kpi-label">中性估值</div>
                <div className="kpi-value" style={{ fontSize: 20, color: 'var(--text-main)' }}>{fmtWan(v.neutral_cents)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>{fmtYuan(v.neutral_cents)}</div>
              </div>
            </Col>
            <Col xs={24} md={8}>
              <div className="kpi-card" style={{ textAlign: 'center', padding: '16px 8px' }}>
                <div className="kpi-label">乐观估值</div>
                <div className="kpi-value" style={{ fontSize: 20, color: 'var(--success)' }}>{fmtWan(v.optimistic_cents)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>{fmtYuan(v.optimistic_cents)}</div>
              </div>
            </Col>
          </Row>

          <Divider style={{ margin: '16px 0' }} />

          {isCost && (
            <Row gutter={16}>
              {land && (
                <Col xs={24} md={12}>
                  <Card size="small" title="土地部分" style={{ background: '#fafafa' }}>
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="面积">{land.area_sqm} ㎡</Descriptions.Item>
                      <Descriptions.Item label="单价参考">{land.unit_range}</Descriptions.Item>
                      <Descriptions.Item label="土地价值">{fmtWan(land.neutral_cents)}（中性）</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              )}
              {building && (
                <Col xs={24} md={12}>
                  <Card size="small" title="建筑部分" style={{ background: '#fafafa' }}>
                    <Descriptions size="small" column={1}>
                      <Descriptions.Item label="面积">{building.area_sqm} ㎡</Descriptions.Item>
                      <Descriptions.Item label="建安造价">{building.cost_range}</Descriptions.Item>
                      {building.build_year && <Descriptions.Item label="建成年份">{building.build_year}</Descriptions.Item>}
                      <Descriptions.Item label="折旧">{building.depreciation_note}</Descriptions.Item>
                      <Descriptions.Item label="建筑价值">{fmtWan(building.neutral_cents)}（中性）</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              )}
            </Row>
          )}

          {!isCost && (
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="单价区间">{v.unit_price_range}</Descriptions.Item>
              <Descriptions.Item label="面积">{v.area_sqm} ㎡</Descriptions.Item>
            </Descriptions>
          )}

          <Divider style={{ margin: '16px 0' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            计算明细：
          </Text>
          <ul style={{ marginTop: 8, paddingLeft: 20 }}>
            {(result?.notes || []).map((n, i) => <li key={i} style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.8 }}>{n}</li>)}
          </ul>
          <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
            ⚠️ 本估算为成本法粗估，土地价格与建安成本为区间参考值，未考虑市场波动、税费、区位溢价、抵押物占用等；不替代专业评估机构出具的正式评估报告。处置决策请结合专业律师意见和实地尽调结果。
          </Paragraph>
        </Card>
      )}
    </div>
  )
}
