import { useEffect, useRef, useState } from 'react'
import { Card, Steps, Typography, Spin, Modal, List, Button } from 'antd'
import { useParams, useNavigate } from 'react-router-dom'
import { taskApi, reportApi } from '../api'

const { Title, Text } = Typography

const NODES = [
  { title: '信息提取', desc: '提取结构化债权字段' },
  { title: '工商/司法查询', desc: '企业信息与司法风险' },
  { title: '法律检索', desc: '裁判文书与法规依据' },
  { title: '抵押物估值', desc: '三档估值与覆盖率' },
  { title: '本息计算', desc: '按判决书或LPR计算' },
  { title: '综合分析', desc: '生成尽调报告' },
]

export default function ProgressPage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [task, setTask] = useState(null)
  const [doneModal, setDoneModal] = useState(null) // { reports: [...] } 完成弹窗
  const timerRef = useRef(null)

  // 任务完成：加载报告列表，多份弹窗引导，单份直接跳转
  const onTaskDone = async (tId) => {
    try {
      const resp = await reportApi.get(tId)
      const reports = resp.data?.reports || []
      if (reports.length <= 1) {
        const rid = reports[0]?.id
        setTimeout(() => navigate(rid ? `/report/${tId}/${rid}` : `/report/${tId}`), 600)
      } else {
        // 多份报告：弹窗列出，用户点名称看对应报告
        setDoneModal({
          reports: reports.map((r) => ({
            id: r.id,
            name: r.content?.report_meta?.debtor_name || `债权#${r.id}`,
          })),
        })
      }
    } catch {
      navigate(`/report/${tId}`)
    }
  }

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
            await onTaskDone(taskId)
          }
        }
      } catch { /* 拦截器已提示 */ }
    }
    poll()
    timerRef.current = setInterval(poll, 3000)
    return () => { finished = true; clearInterval(timerRef.current) }
  }, [taskId])

  if (!task) {
    return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  }

  const nodeIndex = task.current_node ? NODES.findIndex((n) => n.title === task.current_node) : -1
  const current = nodeIndex >= 0 ? nodeIndex : Math.min(Math.floor(task.progress / 17), NODES.length - 1)

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '48px 16px' }}>
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

      {/* 多份报告完成弹窗：列出每份报告名称，用户点名称查看对应报告 */}
      <Modal
        title="尽调完成"
        open={doneModal != null}
        onCancel={() => { setDoneModal(null); navigate('/tasks') }}
        footer={[
          <Button key="tasks" onClick={() => { setDoneModal(null); navigate('/tasks') }}>去「我的任务」查看</Button>,
        ]}
        width={560}
      >
        <div style={{ marginBottom: 12, fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
          多份报告已生成，您可以在「我的任务」中查看、补充信息、重新生成报告。点击下方报告名称查看对应报告：
        </div>
        <List
          size="small"
          bordered
          dataSource={doneModal?.reports || []}
          renderItem={(r) => (
            <List.Item style={{ cursor: 'pointer' }} onClick={() => { setDoneModal(null); navigate(`/report/${taskId}/${r.id}`) }}>
              <Text strong style={{ color: 'var(--primary)' }}>📄 {r.name.split('；')[0]}</Text>
            </List.Item>
          )}
        />
      </Modal>
    </div>
  )
}
