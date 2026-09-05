import client from './client'

export const authApi = {
  register: (data) => client.post('/auth/register', data),
  login: (data) => client.post('/auth/login', data),
  me: () => client.get('/auth/me'),
  changePassword: (data) => client.post('/auth/change-password', data),
}

export const claimApi = {
  importText: (text) => client.post('/claims/import-text', { text }),
  importPackage: (headers, rows, title, sourceUrl) => client.post('/claims/import-package', { headers, rows, title, source_url: sourceUrl }),
  importExcel: (file) => {
    const form = new FormData()
    form.append('file', file)
    return client.post('/claims/import-excel', form, { timeout: 180000 })
  },
  importDoc: (files, onUploadProgress) => {
    // Word/PDF/TXT/图片 判决书等材料（可多份合并）→ 提交识别任务，返回 {job_id}；进度用 docJobStatus 轮询
    // onUploadProgress: 上传进度回调（大文件/慢带宽时前端展示真实上传百分比，2026-09-05 用户确认 A 项）
    const form = new FormData()
    ;(files || []).forEach((f) => form.append('files', f))
    return client.post('/claims/import-doc', form, {
      timeout: 600000, // 上传阶段仅算传输时间，大文件慢带宽需放宽
      onUploadProgress: onUploadProgress,
    })
  },
  docJobStatus: (jobId) => client.get(`/claims/import-doc/${jobId}/status`, { timeout: 30000 }),
  update: (id, data) => client.put(`/claims/${id}`, data),
  list: () => client.get('/claims'),
  checkExisted: (debtorNames) => client.post('/claims/check-existed', { debtor_names: debtorNames }),
}

export const taskApi = {
  create: (claimIds, sourceClaimIds) => client.post('/tasks', { claim_ids: claimIds, source_claim_ids: sourceClaimIds }),
  get: (id) => client.get(`/tasks/${id}`),
  list: () => client.get('/tasks'),
  saveOnly: (claimIds, sourceClaimIds) => client.post('/tasks/save-only', { claim_ids: claimIds, source_claim_ids: sourceClaimIds }),
  start: (id) => client.post(`/tasks/${id}/start`),
  claims: (id) => client.get(`/tasks/${id}/claims`),
}

export const activityApi = {
  list: (kind) => client.get(`/activity${kind ? `?kind=${kind}` : ''}`),
}

export const reportApi = {
  get: (taskId) => client.get(`/reports/${taskId}`),
  pdf: (id) => client.post(`/reports/${id}/pdf`),
  sectionNote: (id, section, note) => client.put(`/reports/${id}/section-note`, { section, note }),
  supplements: (id, files, note) => {
    const form = new FormData()
    ;(files || []).forEach((f) => form.append('files', f))
    if (note) form.append('note', note)
    return client.post(`/reports/${id}/supplements`, form, { timeout: 300000 })
  },
  versions: (id) => client.get(`/reports/${id}/versions`),
  versionDetail: (id, version) => client.get(`/reports/${id}/versions/${version}`),
  restoreVersion: (id, version) => client.post(`/reports/${id}/versions/${version}/restore`),
  rediligence: (id) => client.post(`/reports/${id}/re-diligence`),
}

export const dashboardApi = {
  get: () => client.get('/home/dashboard'),
}

// 管理后台：市场数据 CRUD
export const adminDataApi = {
  listMacroKpis: () => client.get('/admin/macro-kpis'),
  createMacroKpi: (data) => client.post('/admin/macro-kpis', data),
  updateMacroKpi: (id, data) => client.put(`/admin/macro-kpis/${id}`, data),
  deleteMacroKpi: (id) => client.delete(`/admin/macro-kpis/${id}`),
  listAuctionStats: () => client.get('/admin/auction-stats'),
  createAuctionStat: (data) => client.post('/admin/auction-stats', data),
  updateAuctionStat: (id, data) => client.put(`/admin/auction-stats/${id}`, data),
  deleteAuctionStat: (id) => client.delete(`/admin/auction-stats/${id}`),
  listAmcStats: () => client.get('/admin/amc-stats'),
  createAmcStat: (data) => client.post('/admin/amc-stats', data),
  updateAmcStat: (id, data) => client.put(`/admin/amc-stats/${id}`, data),
  deleteAmcStat: (id) => client.delete(`/admin/amc-stats/${id}`),
}

export const noticeApi = {
  list: () => client.get('/notices'),
}

// 债权附件（2026-09-01：京东公告信息类附件下载，需登录）
export const feedAttachmentApi = {
  downloadUrl: (itemId, attIndex) => `/feed/${itemId}/attachments/${attIndex}`,
}

export const cluesApi = {
  parseJudgment: (files) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return client.post('/clues/parse-judgment', form, { timeout: 300000 })
  },
  verifyNames: (names) => client.post('/clues/verify-names', { names }),
  caseReport: (entities) => client.post('/clues/case-report', { entities }, { timeout: 600000 }),
  caseReportDeep: (entities) => client.post('/clues/case-report-deep', { entities }, { timeout: 600000 }),
  resolveName: (name) => client.post('/clues/resolve-name', { name }, { timeout: 180000 }),
  deepInvestigation: (company) => client.post('/clues/deep-investigation', { company }, { timeout: 300000 }),
}

export const feedbackApi = {
  submit: (data) => client.post('/feedback', data),
}

// 管理后台：财产线索/深挖报告留存（2026-09-01）
export const adminClueApi = {
  list: (params) => client.get('/admin/clue-reports', { params }),
  get: (id) => client.get(`/admin/clue-reports/${id}`),
  clearCache: (id) => client.post(`/admin/clue-reports/${id}/clear-cache`),
  clearReportCache: (id) => client.post(`/admin/reports/${id}/clear-cache`),
}

export const knowledgeApi = {
  categories: () => client.get('/knowledge/categories'),
  classify: (text, isCase) => client.post('/knowledge/classify', { text, is_case: isCase }),
  renameCategory: (old, next) => client.put('/admin/knowledge/categories', { old, new: next }),
  deleteCategory: (name) => client.delete(`/admin/knowledge/categories/${encodeURIComponent(name)}`),
  listLegalDocs: (category) => client.get('/knowledge/legal-docs', { params: category ? { category } : {} }),
  createLegalDoc: (data) => client.post('/admin/legal-docs', data),
  updateLegalDoc: (id, data) => client.put(`/admin/legal-docs/${id}`, data),
  deleteLegalDoc: (id) => client.delete(`/admin/legal-docs/${id}`),
  uploadLegalDoc: (file) => {
    const form = new FormData()
    form.append('file', file)
    return client.post('/admin/legal-docs/upload', form, { timeout: 120000 })
  },
  listCases: (category) => client.get('/knowledge/cases', { params: category ? { category } : {} }),
  createCase: (data) => client.post('/admin/knowledge-cases', data),
  updateCase: (id, data) => client.put(`/admin/knowledge-cases/${id}`, data),
  deleteCase: (id) => client.delete(`/admin/knowledge-cases/${id}`),
  uploadCase: (file) => {
    const form = new FormData()
    form.append('file', file)
    return client.post('/admin/knowledge-cases/upload', form, { timeout: 120000 })
  },
  match: (features) => client.post('/knowledge/match', { features }),
}

export const valuationApi = {
  estimate: (data) => client.post('/valuation/estimate', data, { timeout: 60000 }),
}

// 债务人画像（2026-09-04）：企业速览查询 + 报告查看/下载
export const debtorProfileApi = {
  // 首次查询需逐维度采集，可能 1-3 分钟 → 超时放宽到 10 分钟
  query: (company) => client.post('/debtor-profile/query', { company }, { timeout: 600000 }),
  detail: (id) => client.get(`/debtor-profile/${id}`),
  downloadUrl: (id) => `/debtor-profile/${id}/download`,
}
