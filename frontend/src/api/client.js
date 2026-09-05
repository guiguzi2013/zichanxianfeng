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
    let msg = typeof detail === 'string' ? detail : detail?.message
    // FastAPI 422 校验错误：detail 是数组，提取第一条人性化信息
    if (!msg && Array.isArray(detail) && detail.length > 0) {
      const d = detail[0]
      const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body').join(' → ') : ''
      msg = d.msg === 'Field required' ? `缺少必要内容：${loc || '请检查上传内容'}` : (loc ? `${loc}：${d.msg}` : d.msg)
    }
    if (!msg && status === 422) msg = '提交内容格式有误，请检查后重试（如页面较旧请强制刷新 Ctrl+F5）'
    if (!msg) msg = error.message || '请求失败'
    message.error(msg)
    return Promise.reject(error)
  }
)

export default client
