import { useEffect, useRef } from 'react'
import { message } from 'antd'
import { useAuthStore } from '../store/auth'

/**
 * 登录不活动超时：用户 30 分钟内无任何操作（点击/按键/滚动）则自动登出。
 * 2026-09-07 用户拍板：超时登出后不强制跳登录页——留在当前页(公开内容可继续浏览，
 * 受保护页显示"请登录"占位)，使用需登录功能时再提示登录。
 */
const IDLE_TIMEOUT_MS = 30 * 60 * 1000 // 30 分钟

export default function IdleTimeout() {
  const token = useAuthStore((s) => s.token)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!token) return

    const resetTimer = () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        useAuthStore.getState().logout()
        message.warning('长时间未操作，已自动退出登录，使用需登录的功能时请重新登录')
      }, IDLE_TIMEOUT_MS)
    }

    const events = ['mousedown', 'keydown', 'scroll', 'touchstart']
    events.forEach((e) => window.addEventListener(e, resetTimer))
    resetTimer()

    return () => {
      events.forEach((e) => window.removeEventListener(e, resetTimer))
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [token])

  return null
}
