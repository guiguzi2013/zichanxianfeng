import { Card, Form, Input, Button, Typography, message, Alert } from 'antd'
import { UserOutlined, LockOutlined, SafetyOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { authApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Title, Text } = Typography

/** 管理后台独立登录入口（/admin-login）：仅管理员/运营编辑可进 */
export default function AdminLoginPage() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const onFinish = async (values) => {
    try {
      const resp = await authApi.login(values)
      const user = resp.data.user
      if (user.role !== 'admin' && user.role !== 'editor') {
        message.warning('该账号不是管理账号，请使用用户端登录')
        return
      }
      setAuth(resp.data.access_token, user)
      message.success(`欢迎，${user.nickname || user.username}`)
      navigate('/admin')
    } catch {
      /* 拦截器已提示 */
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 16px', background: '#f0f2f5', minHeight: 'calc(100vh - 64px)' }}>
      <Card style={{ width: 400, boxShadow: '0 4px 12px rgba(0,0,0,.08)' }}>
        <Title level={3} style={{ textAlign: 'center', color: '#1a5fb4' }}>
          <SafetyOutlined /> 管理后台登录
        </Title>
        <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginBottom: 20 }}>
          资产先锋 · 管理员 / 运营编辑入口
        </Text>
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message="运营编辑账号仅可维护『精选债权』『热门捡漏』栏目；系统配置与用户管理仅管理员可用。" />
        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="管理账号" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>登录管理后台</Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center' }}>
          <Text type="secondary"><Link to="/login">← 返回用户端登录</Link></Text>
        </div>
      </Card>
    </div>
  )
}
