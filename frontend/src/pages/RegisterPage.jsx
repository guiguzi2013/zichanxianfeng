import { Card, Form, Input, Button, Typography } from 'antd'
import { UserOutlined, LockOutlined, SmileOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { authApi } from '../api'

const { Title, Text } = Typography

export default function RegisterPage() {
  const navigate = useNavigate()

  const onFinish = async (values) => {
    try {
      await authApi.register(values)
      navigate('/login')
    } catch {
      /* 拦截器已提示 */
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 16px', background: '#f5f7fa', minHeight: 'calc(100vh - 64px)' }}>
      <Card style={{ width: 400, boxShadow: '0 4px 12px rgba(0,0,0,.08)' }}>
        <Title level={3} style={{ textAlign: 'center', color: '#1a5fb4' }}>
          注册账号
        </Title>
        <Form onFinish={onFinish} size="large" style={{ marginTop: 24 }}>
          <Form.Item name="username" rules={[{ required: true, min: 2, message: '用户名至少2个字符' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名（登录用）" />
          </Form.Item>
          <Form.Item name="nickname" rules={[{ required: true, message: '请输入昵称' }]}>
            <Input prefix={<SmileOutlined />} placeholder="昵称" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 6, message: '密码至少6位' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>
              注册
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center' }}>
          <Text type="secondary">
            已有账号？<Link to="/login">去登录</Link>
          </Text>
        </div>
      </Card>
    </div>
  )
}
