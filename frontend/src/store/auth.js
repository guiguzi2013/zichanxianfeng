import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import client from '../api/client'

export const useAuthStore = create(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      logout: async () => {
        // 记录最后登出时间（在线统计，2026-09-01）：静默调用，失败不影响本地登出
        const token = get().token
        if (token) {
          try {
            await client.post('/auth/logout')
          } catch { /* 忽略（如 token 已过期） */ }
        }
        // 主动清除持久化存储，避免刷新后旧登录态残留
        try {
          localStorage.removeItem('zxf-auth')
          sessionStorage.removeItem('zxf-auth')
        } catch { /* 忽略 */ }
        set({ token: null, user: null })
      },
    }),
    { name: 'zxf-auth' }
  )
)
