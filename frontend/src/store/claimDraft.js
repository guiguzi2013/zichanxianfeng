import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// 本次输入产生的债权草稿（跳转 preview 用）
// 用 sessionStorage 持久化，防止刷新丢失；关闭标签页自动清理
export const useClaimDraftStore = create(
  persist(
    (set) => ({
      claims: [],
      warnings: [], // 输入质量提醒（来自导入接口的 input_warnings）
      dedup: null,  // 重复检测信息 {removed, file_duplicate, batch_dups, existing_dups}
      setClaims: (claims, warnings, dedup) => set({ claims, warnings: warnings || [], dedup: dedup || null }),
      updateClaim: (id, patch) =>
        set((s) => ({ claims: s.claims.map((c) => (c.id === id ? { ...c, ...patch } : c)) })),
      clear: () => set({ claims: [], warnings: [], dedup: null }),
    }),
    { name: 'zxf-claim-draft' }
  )
)
