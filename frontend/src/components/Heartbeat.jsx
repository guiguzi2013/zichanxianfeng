import { useEffect, useRef } from 'react'
import { useAuthStore } from '../store/auth'

/**
 * 在线心跳(2026-09-08 用户批准, 内存版零负担):
 * 登录后页面可见时每 5 分钟静默上报一次 /auth/heartbeat;
 * 页面切后台/关闭自动停发(10 分钟后后台判定离线), 让管理员看到真实在线情况。
 */
const BEAT_MS = 5 * 60 * 1000

export default function Heartbeat() {
  const token = useAuthStore((s) => s.token)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!token) return

    const beat = () => {
      if (document.visibilityState !== 'visible') return
      fetch('/api/auth/heartbeat', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        keepalive: true,
      }).catch(() => { /* 静默: 网络/401 不影响使用 */ })
    }

    const onVisible = () => { if (document.visibilityState === 'visible') beat() }

    beat() // 登录/刷新后立即上报一次
    timerRef.current = setInterval(beat, BEAT_MS)
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      clearInterval(timerRef.current)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [token])

  return null
}
