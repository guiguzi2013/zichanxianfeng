import { useState } from 'react'
import { Modal, Form, Input, Button, message, Typography } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { authApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Text } = Typography

/**
 * 通用登录弹窗（2026-09-01）：未登录点击需登录的功能（如下载附件）时弹出，
 * 登录成功后留在原页面，自动继续未完成的操作（onSuccess 回调）。
 */
export default function LoginModal({ open, onClose, onSuccess }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const setAuth = useAuthStore((s) => s.setAuth)

  const onFinish = async (values) => {
    setLoading(true)
    try {
      const resp = await authApi.login(values)
      setAuth(resp.data.access_token, resp.data.user)
      message.success('登录成功')
      form.resetFields()
      onClose()
      onSuccess && onSuccess()
    } catch {
      /* 拦截器已提示 */
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="登录后继续"
      open={open}
      onCancel={onClose}
      footer={null}
      width={380}
      destroyOnClose
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 13 }}>
        下载重要文件需登录账号，登录后将继续刚才的操作（不会离开当前页面）。
      </Text>
      <Form form={form} onFinish={onFinish} size="large">
        <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
          <Input prefix={<UserOutlined />} placeholder="用户名" autoFocus />
        </Form.Item>
        <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password prefix={<LockOutlined />} placeholder="密码" />
        </Form.Item>
        <Form.Item style={{ marginBottom: 4 }}>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  )
}
