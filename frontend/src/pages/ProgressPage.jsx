import { useEffect, useRef, useState } from 'react'
import { Card, Steps, Typography, Spin } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import { taskApi } from '../api'

const { Title, Text } = Typography

const NODES = [
  { title: '信息提取', desc: '提取结构化债权字段' },
  { title: '工商/司法查询', desc: '企业信息与司法风险' },
  { title: '法律检索', desc: '裁判文书与法规依据' },
  { title: '抵押物估值', desc: '三档估值与覆盖率' },
  { title: '本息计算', desc: '按判决书或LPR计算' },
  { title: '综合分析', desc: '生成九版块报告' },
]

export default function ProgressPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [task, setTask] = useState(null)
  const timerRef = useRef(null)

  useEffect(() => {
    let finished = false
    const poll = async () => {
      try {
        const resp = await taskApi.get(taskId)
        setTask(resp.data)
        if (resp.data.status === 'done' || resp.data.status === 'failed' || resp.data.status === 'partial') {
          finished = true
          clearInterval(timerRef.current)
          if (resp.data.status === 'done') {
            setTimeout(() => navigate(`/report/${taskId}`), 800)
          }
        }
      } catch { /* 拦截器已提示 */ }
    }
    poll()
    timerRef.current = setInterval(poll, 3000)
    return () => { finished = true; clearInterval(timerRef.current) }
  }, [taskId, navigate])

  if (!task) {
    return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  }

  const nodeIndex = task.current_node ? NODES.findIndex((n) => n.title === task.current_node) : -1
  const current = nodeIndex >= 0 ? nodeIndex : Math.min(Math.floor(task.progress / 17), NODES.length - 1)

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '48px 16px' }}>
      <Title level={3} style={{ textAlign: 'center' }}>尽调进行中</Title>
      <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginBottom: 40 }}>
        当前进度 {task.progress}%（{task.current_node || '排队中'}）
      </Text>
      <Card>
        <Steps
          direction="vertical"
          size="small"
          current={current}
          items={NODES.map((n, i) => ({
            title: n.title,
            description: i < current ? '已完成' : i === current ? <Spin size="small" style={{ marginRight: 4 }} /> : n.desc,
            status: i < current ? 'finish' : i === current ? 'process' : 'wait',
          }))}
        />
      </Card>
      {task.status === 'failed' && (
        <Card style={{ marginTop: 16 }} status="error">
          <Text type="danger">尽调失败：{task.error || '未知错误'}。请返回重试或补充材料。</Text>
        </Card>
      )}
    </div>
  )
}
