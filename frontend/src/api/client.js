import axios from 'axios'
import { useAuthStore } from '../store/auth'
import { message } from 'antd'

const client = axios.create({ baseURL: '/api', timeout: 120000 })

// 请求拦截：附加 token
client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：统一错误提示
client.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const status = error.response?.status
    // 401：未登录/登录过期 —— 不在此弹错（调用方自行弹登录框），避免显示原始英文错误
    if (status === 401) {
      return Promise.reject(error)
    }
    const detail = error.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : detail?.message || error.message || '请求失败'
    message.error(msg)
    return Promise.reject(error)
  }
)

export default client
