import { useNavigate, useLocation } from 'react-router-dom'
import { HomeOutlined, ThunderboltOutlined, FundOutlined, UnorderedListOutlined, UserOutlined } from '@ant-design/icons'
import { useAuthStore } from '../store/auth'

/** 移动端底部 Tab 导航（技术文档 §13.4） */
export default function MobileTabbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const token = useAuthStore((s) => s.token)

  const tabs = [
    { key: '/', label: '首页', icon: <HomeOutlined /> },
    { key: '/property-clues', label: '财产线索', icon: <FundOutlined /> },
    { key: '/upload', label: '尽调', icon: <ThunderboltOutlined /> },
    { key: '/tasks', label: '任务', icon: <UnorderedListOutlined />, auth: true },
    { key: token ? '/tasks' : '/login', label: '我的', icon: <UserOutlined /> },
  ]

  const isActive = (key) => location.pathname === key
    || (key === '/property-clues' && location.pathname.startsWith('/property-clues'))
    || (key === '/tasks' && location.pathname.startsWith('/tasks'))

  // 2026-09-05：未登录点「我的」→ 登录页，登录成功后回到"我的"(/tasks)
  const goTab = (t) => {
    if (t.key === '/login') {
      navigate('/login', { state: { from: '/tasks' } })
      return
    }
    navigate(t.key)
  }

  return (
    <div className="mobile-tabbar">
      {tabs.map((t) => (
        <div key={t.label} className={`tab-item ${isActive(t.key) ? 'active' : ''}`} onClick={() => goTab(t)}>
          {t.icon}
          {t.label}
        </div>
      ))}
    </div>
  )
}
