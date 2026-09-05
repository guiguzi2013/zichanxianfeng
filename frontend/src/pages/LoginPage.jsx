import { Card, Form, Input, Button, Typography, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { authApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Title, Text } = Typography

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const setAuth = useAuthStore((s) => s.setAuth)

  const onFinish = async (values) => {
    try {
      const resp = await authApi.login(values)
      setAuth(resp.data.access_token, resp.data.user)
      message.success('登录成功')
      // 2026-09-05：登录后回到被拦截前的页面（state.from），而不是跳首页
      const role = resp.data.user?.role
      const from = location.state?.from
      if (role === 'admin' || role === 'editor') {
        navigate(from && from.startsWith('/admin') ? from : '/admin', { replace: true })
      } else {
        navigate(from && from.startsWith('/') ? from : '/', { replace: true })
      }
    } catch {
      /* 拦截器已提示 */
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 16px', background: '#f5f7fa', minHeight: 'calc(100vh - 64px)' }}>
      <Card style={{ width: 400, boxShadow: '0 4px 12px rgba(0,0,0,.08)' }}>
        <Title level={3} style={{ textAlign: 'center', color: '#1a5fb4' }}>
          NPL中国
        </Title>
        <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginBottom: 24 }}>
          中国不良资产 · 尽调与投融资平台
        </Text>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>
              登录
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center' }}>
          <Text type="secondary">
            还没有账号？<Link to="/register">立即注册</Link>
          </Text>
        </div>
      </Card>
    </div>
  )
}
