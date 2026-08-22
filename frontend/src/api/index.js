import client from './client'

export const authApi = {
  register: (data) => client.post('/auth/register', data),
  login: (data) => client.post('/auth/login', data),
  me: () => client.get('/auth/me'),
  changePassword: (data) => client.post('/auth/change-password', data),
}

export const claimApi = {
  importText: (text) => client.post('/claims/import-text', { text }),
  importLink: (url) => client.post('/claims/import-link', { url }),
  importExcel: (file) => {
    const form = new FormData()
    form.append('file', file)
    return client.post('/claims/import-excel', form, { timeout: 180000 })
  },
  update: (id, data) => client.put(`/claims/${id}`, data),
  list: () => client.get('/claims'),
}

export const taskApi = {
  create: (claimIds) => client.post('/tasks', { claim_ids: claimIds }),
  get: (id) => client.get(`/tasks/${id}`),
  list: () => client.get('/tasks'),
  saveOnly: (claimIds) => client.post('/tasks/save-only', { claim_ids: claimIds }),
  start: (id) => client.post(`/tasks/${id}/start`),
}

export const reportApi = {
  get: (taskId) => client.get(`/reports/${taskId}`),
  pdf: (id) => client.post(`/reports/${id}/pdf`),
  sectionNote: (id, section, note) => client.put(`/reports/${id}/section-note`, { section, note }),
  supplements: (id, files) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return client.post(`/reports/${id}/supplements`, form, { timeout: 300000 })
  },
  versions: (id) => client.get(`/reports/${id}/versions`),
  versionDetail: (id, version) => client.get(`/reports/${id}/versions/${version}`),
  restoreVersion: (id, version) => client.post(`/reports/${id}/versions/${version}/restore`),
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

export const knowledgeApi = {
  listLegalDocs: () => client.get('/knowledge/legal-docs'),
  createLegalDoc: (data) => client.post('/admin/legal-docs', data),
  updateLegalDoc: (id, data) => client.put(`/admin/legal-docs/${id}`, data),
  deleteLegalDoc: (id) => client.delete(`/admin/legal-docs/${id}`),
  uploadLegalDoc: (file) => {
    const form = new FormData()
    form.append('file', file)
    return client.post('/admin/legal-docs/upload', form, { timeout: 120000 })
  },
  listCases: () => client.get('/knowledge/cases'),
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
