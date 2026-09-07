import { useState } from 'react'
import { Card, Descriptions, Tag, Button, Space, Typography, Modal, Form, Input, message } from 'antd'
import { ArrowLeftOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api'
import { useAuthStore } from '../store/auth'

const { Title, Text } = Typography

/** 账户信息独立页(2026-09-08 用户中心 Tab 重构: 账户信息移出, 用户中心只留 任务/报告/回收站) */
export default function AccountPage() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const [pwdModal, setPwdModal] = useState(false)
  const [pwdForm] = Form.useForm()

  const changePassword = async () => {
    const v = await pwdForm.validateFields()
    try {
      await authApi.changePassword({ old_password: v.old_password, new_password: v.new_password })
      message.success('密码已修改，请重新登录')
      setPwdModal(false)
      useAuthStore.getState().logout()
      navigate('/login', { state: { from: '/account' } })
    } catch { /* 拦截器已提示 */ }
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 16px' }}>
      <Button type="link" icon={<ArrowLeftOutlined />} style={{ paddingLeft: 0, marginBottom: 8 }} onClick={() => navigate('/tasks')}>返回用户中心</Button>
      <Title level={3}>账户信息</Title>
      <Card>
        <Descriptions column={1} bordered size="small" style={{ maxWidth: 560 }}>
          <Descriptions.Item label="用户名">{user?.username}</Descriptions.Item>
          <Descriptions.Item label="昵称">{user?.nickname || '—'}</Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={user?.role === 'admin' ? 'gold' : user?.role === 'editor' ? 'blue' : 'green'}>
              {user?.role === 'admin' ? '管理员' : user?.role === 'editor' ? '运营编辑' : '注册用户'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="积分余额">{user?.points ?? 0}</Descriptions.Item>
          <Descriptions.Item label="注册时间">{user?.created_at ? String(user.created_at).replace('T', ' ').slice(0, 16) : '—'}</Descriptions.Item>
        </Descriptions>
        <Space style={{ marginTop: 16 }}>
          <Button type="primary" icon={<SafetyCertificateOutlined />} onClick={() => setPwdModal(true)}>修改密码</Button>
        </Space>
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>任务与报告管理在「用户中心」（我的任务 / 我的报告 / 回收站）。</Text>
        </div>
      </Card>

      <Modal title="修改密码" open={pwdModal} onOk={changePassword} onCancel={() => setPwdModal(false)} okText="确认修改" destroyOnClose>
        <Form form={pwdForm} layout="vertical">
          <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 6, message: '至少6位' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, v) => (!v || getFieldValue('new_password') === v ? Promise.resolve() : Promise.reject(new Error('两次密码不一致'))),
              }),
            ]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
