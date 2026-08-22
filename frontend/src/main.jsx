import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles/global.css'

// 设计令牌（对应技术文档 §13.2：定制商务蓝，参考智收云风格但差异化配色）
const theme = {
  token: {
    colorPrimary: '#1B6FE8',
    colorInfo: '#1B6FE8',
    colorSuccess: '#16A36A',
    colorWarning: '#F7A41E',
    colorError: '#E6453F',
    colorTextBase: '#1F2D3D',
    colorText: '#1F2D3D',
    colorTextSecondary: '#51617B',
    colorBorder: '#E5E9F0',
    colorBorderSecondary: '#EEF1F6',
    colorBgLayout: '#F6F8FB',
    borderRadius: 6,
    fontSize: 14,
    fontFamily: "-apple-system, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif",
  },
  components: {
    Layout: { headerBg: '#FFFFFF', bodyBg: '#F6F8FB', headerHeight: 60 },
    Card: { borderRadiusLG: 8, boxShadowTertiary: '0 2px 12px rgba(31,45,61,.06)' },
    Button: { borderRadius: 6, controlHeight: 36 },
    Table: { headerBg: '#F7F9FC', rowHoverBg: '#F5F9FF' },
    Tag: { borderRadiusSM: 4 },
    Menu: { itemSelectedColor: '#1B6FE8', itemHoverColor: '#1B6FE8' },
  },
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={theme}>
      <App />
    </ConfigProvider>
  </React.StrictMode>
)
