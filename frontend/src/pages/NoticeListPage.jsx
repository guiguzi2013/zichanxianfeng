import { useEffect, useState } from 'react'
import { Card, List, Tag, Typography, Spin, Empty, Button, Space, Input } from 'antd'
import { BellOutlined, RightOutlined } from '@ant-design/icons'
import client from '../api/client'

const { Title, Text, Paragraph } = Typography

/** 平台公告列表页：展示平台发布的公告（notices 表，与首页公告版块同源） */
export default function NoticeListPage() {
  const [notices, setNotices] = useState([])
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState(null) // 详情弹层
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    client.get('/notices').then((resp) => {
      setNotices(resp.data?.notices || [])
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>

  // 2026-09-02：公告搜索（标题/内容过滤）
  const kw = keyword.trim().toLowerCase()
  const filtered = kw ? notices.filter((n) => `${n.title || ''} ${n.content || ''}`.toLowerCase().includes(kw)) : notices

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 80px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 4 }}>
        <Title level={3} style={{ marginBottom: 0 }}><BellOutlined style={{ marginRight: 8, color: 'var(--primary)' }} />平台公告</Title>
        <Input.Search allowClear placeholder="搜索公告标题/内容" style={{ width: 260 }} onSearch={(v) => setKeyword(v)} />
      </div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>平台发布的通知与说明（按时间排序）</Text>

      {filtered.length === 0 ? (
        <Empty description="暂无公告" style={{ padding: 60 }} />
      ) : (
        <List
          itemLayout="vertical"
          dataSource={filtered}
          pagination={{ pageSize: 10, showSizeChanger: false, showQuickJumper: true, align: 'center' }}
          renderItem={(n) => (
            <List.Item style={{ cursor: 'pointer', padding: '14px 4px' }} onClick={() => setDetail(n)}>
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
