import { useState } from 'react'
import { Layout, Menu, Button, Dropdown, Avatar } from 'antd'
import { UserOutlined, LogoutOutlined, MenuOutlined, UnorderedListOutlined, FileTextOutlined, SettingOutlined, IdcardOutlined } from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/auth'

const { Header } = Layout

export default function AppHeader() {
  const navigate = useNavigate()
  const location = useLocation()
  const { token, user, logout } = useAuthStore()
  const [logoError, setLogoError] = useState(false)

  // 前台导航（管理后台不在此显示，走独立 /admin-login）
  // 去掉「首页」「公告」两个无用菜单（用户确认）
  const menuItems = [
    { key: '/debts', label: '债权信息' },
    { key: '/property-clues', label: '财产线索' },
    { key: '/upload', label: '智能尽调' },
    { key: '/valuation', label: '土地厂房估价' },
    { key: '/valuation/commercial', label: '商业房产估价' },
  ]

  // 用户下拉（登录后）：
  // 员工（admin/editor）只保留「管理后台 + 退出登录」（用户功能对其无用）
  // 普通用户保留「我的任务 / 我的报告 / 账户信息 + 退出登录」
  const isBackend = user?.role === 'admin' || user?.role === 'editor'
  const userMenuItems = isBackend
    ? [
        { key: 'admin', icon: <SettingOutlined />, label: '管理后台' },
        { type: 'divider' },
        { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
      ]
    : [
        { key: 'tasks', icon: <UnorderedListOutlined />, label: '我的任务' },
        { key: 'reports', icon: <FileTextOutlined />, label: '我的报告' },
        { key: 'profile', icon: <IdcardOutlined />, label: '账户信息' },
        { type: 'divider' },
        { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
      ]
  const userMenu = {
    items: userMenuItems,
    onClick: ({ key }) => {
      if (key === 'logout') {
        logout()
        navigate('/login')
      } else if (key === 'tasks') navigate('/tasks')
      else if (key === 'reports') navigate('/tasks?tab=reports')
      else if (key === 'profile') navigate('/tasks?tab=profile')
      else if (key === 'admin') navigate('/admin')
    },
  }

  return (
    <Header
      style={{
        background: '#fff',
        borderBottom: '1px solid var(--border)',
        padding: '0 16px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
        height: 60,
        lineHeight: '60px',
      }}
    >
      <div style={{ maxWidth: 1200, margin: '0 auto', width: '100%', height: '100%', display: 'flex', alignItems: 'center', gap: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', height: '100%', cursor: 'pointer', flexShrink: 0 }} onClick={() => navigate('/')}>
          {!logoError ? (
            <img src="/logo.png?v=3" alt="NPL中国" style={{ height: 45, maxWidth: 300, objectFit: 'contain' }} onError={() => setLogoError(true)} />
          ) : (
            <>
              <div style={{ width: 44, height: 44, borderRadius: 8, background: 'linear-gradient(135deg, #1B6FE8, #3D8BF5)', color: '#fff', fontSize: 20, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 10 }}>N</div>
              <div style={{ lineHeight: 1.1 }}>
                <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-main)' }}>NPL中国</div>
                <div style={{ fontSize: 11, color: 'var(--text-weak)' }}>中国不良资产 · 尽调与投融资平台</div>
              </div>
            </>
          )}
        </div>

        <Menu
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, borderBottom: 'none', minWidth: 0 }}
          className="header-menu-desktop"
        />

        {/* 移动端：汉堡菜单 */}
        <div className="header-menu-mobile">
          <Dropdown
            menu={{
              items: menuItems.map((m) => ({ key: m.key, label: m.label })),
              onClick: ({ key }) => navigate(key),
            }}
            placement="bottomRight"
          >
            <Button type="text" icon={<MenuOutlined style={{ fontSize: 20 }} />} />
          </Dropdown>
        </div>

        {token ? (
          <Dropdown menu={userMenu}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <Avatar style={{ background: 'var(--primary)', cursor: 'pointer' }} icon={<UserOutlined />}>
                {user?.nickname?.[0]?.toUpperCase()}
              </Avatar>
              <span className="header-username" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{user?.nickname || user?.username}</span>
            </div>
          </Dropdown>
        ) : (
          <Button type="primary" onClick={() => navigate('/login')}>登录</Button>
        )}
      </div>
    </Header>
  )
}
