import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from 'antd'
import AppHeader from './components/AppHeader'
import AppFooter from './components/AppFooter'
import MobileTabbar from './components/MobileTabbar'
import IdleTimeout from './components/IdleTimeout'
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
import ValuationPage from './pages/ValuationPage'
import TaskClaimsPage from './pages/TaskClaimsPage'
import AdminLandPricePage from './pages/AdminLandPricePage'
import QccDemoPage from './pages/QccDemoPage'
import PropertyCluesPage from './pages/PropertyCluesPage'
import DebtListPage from './pages/DebtListPage'
import NoticeListPage from './pages/NoticeListPage'
import SearchPage from './pages/SearchPage'
import { useAuthStore } from './store/auth'

const { Content } = Layout

// 登录守卫：普通用户访问前台用户功能；员工（editor/admin）无用户功能，重定向管理后台
function RequireAuth({ children }) {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  if (!token) return <Navigate to="/login" replace />
  if (user?.role === 'editor' || user?.role === 'admin') return <Navigate to="/admin" replace />
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

// 仅管理员守卫（知识库等核心后台功能）：editor 无权访问，直接访问链接会被拦回后台首页
function RequireAdmin({ children }) {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  if (!token) return <Navigate to="/admin-login" replace />
  if (user?.role !== 'admin') return <Navigate to="/admin" replace />
  return children
}

// 报告页守卫：普通用户（看自己的）或员工/管理员（后台查看用户报告）均可
function RequireReportView({ children }) {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)
  if (!token) return <Navigate to="/login" replace />
  if (user?.role === 'admin' || user?.role === 'editor') return children
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout style={{ minHeight: '100vh', background: 'var(--bg-page)' }}>
        <AppHeader />
        <IdleTimeout />
        <Content style={{ background: 'var(--bg-page)' }}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/admin-login" element={<AdminLoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/" element={<HomePage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/preview" element={<RequireAuth><PreviewPage /></RequireAuth>} />
            <Route path="/progress/:taskId" element={<RequireAuth><ProgressPage /></RequireAuth>} />
            <Route path="/report/:taskId/:reportId" element={<RequireReportView><ReportPage /></RequireReportView>} />
            <Route path="/tasks" element={<RequireAuth><TasksPage /></RequireAuth>} />
            <Route path="/asset/:id" element={<AssetDetailPage />} />
            <Route path="/admin/feed" element={<RequireBackend><AdminFeedPage /></RequireBackend>} />
            <Route path="/valuation" element={<ValuationPage mode="industrial" />} />
            <Route path="/valuation/commercial" element={<ValuationPage mode="commercial" />} />
            <Route path="/task/:taskId/edit" element={<RequireAuth><TaskClaimsPage /></RequireAuth>} />
            <Route path="/property-clues" element={<PropertyCluesPage />} />
            <Route path="/debts" element={<DebtListPage />} />
            <Route path="/notices" element={<NoticeListPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/demo/biz" element={<QccDemoPage />} />
            <Route path="/demo/risk" element={<QccDemoPage />} />
            <Route path="/admin" element={<RequireBackend><AdminDashboard /></RequireBackend>} />
            <Route path="/admin/data" element={<RequireBackend><AdminDataPage /></RequireBackend>} />
            <Route path="/admin/knowledge" element={<RequireAdmin><KnowledgePage /></RequireAdmin>} />
            <Route path="/admin/land-prices" element={<RequireBackend><AdminLandPricePage /></RequireBackend>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
        <AppFooter />
        <MobileTabbar />
      </Layout>
    </BrowserRouter>
  )
}
