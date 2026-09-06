import { useState } from 'react'
import { Card, Input, Button, Space, Typography, Modal, message } from 'antd'
import { SearchOutlined, FundOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { cluesApi } from '../api'
import { useAuthStore } from '../store/auth'
import { looksAbbrev, looksPerson } from '../utils/companyName'

const { Title, Text } = Typography

/**
 * 财产线索（2026-09-06 重构）：输入一家企业 → 查询即生成《财产线索报告》
 * 用户拍板：①单企业输入 ②查询结果直接生成报告(查询+追索分析) ③可下载PDF、在"我的报告"回看/重复下载
 * ④同企业只能查一次(重复提示已有) ⑤深度对比(深挖)待后续单独做
 */
export default function PropertyCluesPage() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const [company, setCompany] = useState('')
  const [loading, setLoading] = useState(false)

  const onQuery = () => {
    const name = company.trim()
    if (!name) { message.warning('请输入企业名称'); return }
    if (!token) { message.warning('请先登录后查询'); navigate('/login', { state: { from: window.location.pathname + window.location.search } }); return }
    if (looksPerson(name)) {
      message.error('财产线索仅支持企业，不接受自然人或姓名。请填写企业工商全称（如：XX置业有限公司）。')
      return
    }
    if (looksAbbrev(name)) {
      message.error('输入的名称疑似不完整。请填写企业工商全称，如：青岛市XX房地产开发有限公司。')
      return
    }
    Modal.confirm({
      title: '确认生成财产线索报告？',
      content: (
        <div style={{ fontSize: 13 }}>
          <p style={{ marginBottom: 8 }}>将查询「{name}」并生成《{name}财产线索报告》，涵盖：</p>
          <p style={{ color: '#595959', lineHeight: 1.9, marginBottom: 8 }}>
            企业概况 · 股权与对外投资 · 财产线索（动产/土地抵押、司法拍卖等）· 无形资产（专利/商标/备案等，可评估变现）· 司法与风险（失信/被执行/限高等）· 权利主张案件（该企业作为原告/权利方的涉诉，胜诉可能产生执行回款）· 追索分析与建议
          </p>
          <p style={{ fontSize: 12, color: '#8c8c8c' }}>查询过的企业将直接复用结果快速返回；报告将存入「我的报告」，可随时回看与重复下载。</p>
        </div>
      ),
      okText: '查询并生成',
      cancelText: '取消',
      onOk: () => doQuery(name),
    })
  }

  const doQuery = async (name) => {
    setLoading(true)
    message.info('正在查询企业财产线索并生成报告，首次查询约需 1-2 分钟，请勿关闭页面…', 6)
    try {
      const resp = await cluesApi.queryReport(name)
      if (resp?.ok && resp.report) {
        message.success('财产线索报告已生成')
        navigate(`/clue-report/${resp.report.id}`)
      } else if (resp?.already) {
        // 重复企业：引导去我的报告查看（2026-09-06 用户拍板）
        Modal.confirm({
          title: '该企业报告已存在',
          content: resp.error || '该企业已生成过财产线索报告。',
          okText: '去「我的报告」查看',
          cancelText: '知道了',
          onOk: () => navigate('/tasks?tab=reports'),
        })
      } else {
        message.error(resp?.error || '查询失败，请稍后重试')
      }
    } catch (e) {
      message.error(e.message || '查询失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 60px' }}>
      <Title level={3} style={{ marginBottom: 4 }}>财产线索</Title>
      <Text type="secondary" style={{ fontSize: 13, display: 'block', marginBottom: 16 }}>
        输入债务人/担保人企业全称，一键生成《财产线索报告》：查询企业对外投资、股权、动产/土地抵押、司法拍卖等财产线索，
        结合失信/被执行/限高等风险给出追索建议。可下载 PDF，自动存入「我的报告」。
      </Text>

      <Card style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%', maxWidth: 700 }}>
          <Input
            size="large"
            placeholder="请输入企业工商全称，如：青岛多元房地产开发有限公司"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            onPressEnter={onQuery}
            maxLength={100}
          />
          <Button size="large" type="primary" icon={<SearchOutlined />} loading={loading} onClick={onQuery}>
            查询并生成报告
          </Button>
        </Space.Compact>
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-weak)' }}>
          仅支持企业（一次一家）；自然人请通过线下渠道调查，或结合其关联企业查询。
        </div>
      </Card>

      <Card>
        <Space align="start" style={{ width: '100%' }}>
          <FundOutlined style={{ fontSize: 20, color: 'var(--primary)', marginTop: 2 }} />
          <div>
            <Text strong>报告内容</Text>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 2, marginTop: 4 }}>
              企业概况（工商登记）→ 股权与对外投资 → 财产线索（动产/土地抵押、司法拍卖、询价评估）→
              无形资产（专利/商标/网络服务备案/特许经营/知产出质等核验与变现提示）→
              司法与风险（失信/被执行/限高/终本/冻结等命中记录与明细）→
              权利主张案件（该企业作为原告/权利方的涉诉，胜诉回款属其未来财产）→ 追索分析与建议（按可执行性给出处置优先级）。
              查询过的企业走缓存快速返回；报告存入「我的报告」可重复下载 PDF。
            </div>
          </div>
        </Space>
      </Card>
    </div>
  )
}
