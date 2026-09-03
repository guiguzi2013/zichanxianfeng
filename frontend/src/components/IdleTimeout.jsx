import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { message } from 'antd'
import { useAuthStore } from '../store/auth'

/**
 * 登录不活动超时：用户 30 分钟内无任何操作（点击/按键/滚动）则自动登出，需重新登录。
 * 活动（操作）会重置计时器；仅登录状态下生效。
 */
const IDLE_TIMEOUT_MS = 30 * 60 * 1000 // 30 分钟

export default function IdleTimeout() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!token) return

    const resetTimer = () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        useAuthStore.getState().logout()
        message.warning('长时间未操作，已自动退出登录，请重新登录')
        navigate('/login', { replace: true })
      }, IDLE_TIMEOUT_MS)
    }

    const events = ['mousedown', 'keydown', 'scroll', 'touchstart']
    events.forEach((e) => window.addEventListener(e, resetTimer))
    resetTimer()

    return () => {
      events.forEach((e) => window.removeEventListener(e, resetTimer))
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [token, navigate])

  return null
}
