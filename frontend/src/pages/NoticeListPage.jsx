import { useEffect, useState } from 'react'
import { Card, List, Tag, Typography, Pagination, Spin, Empty, Button, Space, Alert } from 'antd'
import { BellOutlined, RightOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import client from '../api/client'

const { Title, Text, Paragraph } = Typography

export default function NoticeListPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [notices, setNotices] = useState([])
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState(null) // 详情弹层

  useEffect(() => {
    client.get('/notices').then((resp) => setNotices(resp.data?.notices || [])).catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const openDetail = async (id) => {
    try {
      const resp = await client.get(`/notices/${id}`)
      setDetail(resp.data)
    } catch { /* 拦截器已提示 */ }
  }

  const noticeList = notices

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 16px 80px' }}>
      <Title level={3} style={{ marginBottom: 4 }}><BellOutlined style={{ marginRight: 8, color: 'var(--primary)' }} />平台公告</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>平台运营通知、功能更新、债权转让与拍卖动态</Text>

      {noticeList.length === 0 ? (
        <Empty description="暂无公告" style={{ padding: 60 }} />
      ) : (
        <List
          itemLayout="vertical"
          dataSource={noticeList}
          pagination={{
            pageSize: 8,
            showSizeChanger: false,
            showQuickJumper: true,
            align: 'center',
          }}
          renderItem={(n) => (
            <List.Item
              style={{ cursor: 'pointer', padding: '14px 4px' }}
              onClick={() => openDetail(n.id)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                    {n.is_pinned && <Tag color="red" style={{ marginRight: 6 }}>置顶</Tag>}
                    {n.title}
                  </div>
                  {n.content && (
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                      {n.content}
                    </div>
                  )}
                  <Text type="secondary" style={{ fontSize: 11 }}>{n.published_at?.slice(0, 10) || ''}</Text>
                </div>
                <RightOutlined style={{ color: 'var(--text-weak)', marginTop: 6 }} />
              </div>
            </List.Item>
          )}
        />
      )}

      {/* 公告详情弹层 */}
      {detail && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }} onClick={() => setDetail(null)}>
          <Card style={{ maxWidth: 640, width: '100%' }} onClick={(e) => e.stopPropagation()}>
            <Space style={{ marginBottom: 8 }}>
              {detail.is_pinned && <Tag color="red">置顶</Tag>}
              <Text type="secondary" style={{ fontSize: 11 }}>{detail.published_at?.slice(0, 10) || ''}</Text>
            </Space>
            <Title level={4} style={{ marginTop: 0 }}>{detail.title}</Title>
            <Paragraph style={{ whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.8 }}>{detail.content || '暂无内容'}</Paragraph>
            <Button type="primary" onClick={() => setDetail(null)}>关闭</Button>
          </Card>
        </div>
      )}
    </div>
  )
}
