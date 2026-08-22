import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// 本次输入产生的债权草稿（跳转 preview 用）
// 用 sessionStorage 持久化，防止刷新丢失；关闭标签页自动清理
export const useClaimDraftStore = create(
  persist(
    (set) => ({
      claims: [],
      warnings: [], // 输入质量提醒（来自导入接口的 input_warnings）
      setClaims: (claims, warnings) => set({ claims, warnings: warnings || [] }),
      updateClaim: (id, patch) =>
        set((s) => ({ claims: s.claims.map((c) => (c.id === id ? { ...c, ...patch } : c)) })),
      clear: () => set({ claims: [], warnings: [] }),
    }),
    { name: 'zxf-claim-draft' }
  )
)
