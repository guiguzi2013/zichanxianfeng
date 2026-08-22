import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from 'antd'
import AppHeader from './components/AppHeader'
import AppFooter from './components/AppFooter'
import MobileTabbar from './components/MobileTabbar'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import AdminLoginPage from './pages/AdminLoginPage'
import HomePage from './pages/HomePage'
import UploadPage from './pages/UploadPage'
import PreviewPage from './pages/PreviewPage'
import ProgressPage from './pages/ProgressPage'
import ReportPage from './pages/ReportPage'
import TasksPage from './pages/TasksPage'
import AssetDetailPage from './pages/AssetDetailPage'
import AdminFeedPage from './pages/AdminFeedPage'
import AdminDashboard from './pages/AdminDashboard'
import AdminDataPage from './pages/AdminDataPage'
import KnowledgePage from './pages/KnowledgePage'
import ComparePage from './pages/ComparePage'
import QccDemoPage from './pages/QccDemoPage'
import PropertyCluesPage from './pages/PropertyCluesPage'
import DebtListPage from './pages/DebtListPage'
import NoticeListPage from './pages/NoticeListPage'
import { useAuthStore } from './store/auth'

const { Content } = Layout

// 登录守卫
function RequireAuth({ children }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return children
}

// 管理后台守卫：未登录→/admin-login；普通用户→首页
function RequireBackend({ children }) {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  if (!token) return <Navigate to="/admin-login" replace />
  if (user?.role !== 'admin' && user?.role !== 'editor') return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout style={{ minHeight: '100vh', background: 'var(--bg-page)' }}>
        <AppHeader />
        <Content style={{ background: 'var(--bg-page)' }}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/admin-login" element={<AdminLoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/" element={<HomePage />} />
            <Route path="/upload" element={<RequireAuth><UploadPage /></RequireAuth>} />
            <Route path="/preview" element={<RequireAuth><PreviewPage /></RequireAuth>} />
            <Route path="/progress/:taskId" element={<RequireAuth><ProgressPage /></RequireAuth>} />
            <Route path="/report/:taskId" element={<RequireAuth><ReportPage /></RequireAuth>} />
            <Route path="/tasks" element={<RequireAuth><TasksPage /></RequireAuth>} />
            <Route path="/asset/:id" element={<AssetDetailPage />} />
            <Route path="/admin/feed" element={<RequireAuth><AdminFeedPage /></RequireAuth>} />
            <Route path="/compare" element={<RequireAuth><ComparePage /></RequireAuth>} />
            <Route path="/property-clues" element={<PropertyCluesPage />} />
            <Route path="/debts" element={<DebtListPage />} />
            <Route path="/notices" element={<NoticeListPage />} />
            <Route path="/demo/biz" element={<QccDemoPage />} />
            <Route path="/demo/risk" element={<QccDemoPage />} />
            <Route path="/admin" element={<RequireBackend><AdminDashboard /></RequireBackend>} />
            <Route path="/admin/data" element={<RequireBackend><AdminDataPage /></RequireBackend>} />
            <Route path="/admin/knowledge" element={<RequireBackend><KnowledgePage /></RequireBackend>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
        <AppFooter />
        <MobileTabbar />
      </Layout>
    </BrowserRouter>
  )
}
