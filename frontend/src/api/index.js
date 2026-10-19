import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// 统一把后端的 detail 错误信息抛出来，便于页面提示
api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    const detail = err.response?.data?.detail
    return Promise.reject(new Error(detail || err.message || '请求失败'))
  },
)

/* ========= 词条 ========= */
export const createWord = (data) => api.post('/words', data).then((r) => r.data)
export const listWords = (params = {}) => api.get('/words', { params }).then((r) => r.data)
export const getWord = (id) => api.get(`/words/${id}`).then((r) => r.data)
export const updateWord = (id, data) => api.put(`/words/${id}`, data).then((r) => r.data)
export const deleteWord = (id) => api.delete(`/words/${id}`).then((r) => r.data)
export const listTags = () => api.get('/tags').then((r) => r.data)

/* ========= 批量导入 / 导出 ========= */
export const batchImport = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api
    .post('/words/batch', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data)
}

export const exportCsvUrl = (params = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== '' && v != null),
  ).toString()
  return `/api/words/export${qs ? `?${qs}` : ''}`
}

/* ========= 词典自动补全 ========= */
export const lookupDictionary = (word) =>
  api.get(`/dictionary/${encodeURIComponent(word)}`).then((r) => r.data)

/* ========= 图片取词 ========= */
export const extractWordsFromImage = (file) => {
  const form = new FormData()
  form.append('file', file)
  // 视觉模型响应较慢，单独放宽超时（实例默认 15s）
  return api
    .post('/ocr/extract', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    .then((r) => r.data)
}

/* ========= 记忆复习 ========= */
export const getReviewOverview = () => api.get('/review/overview').then((r) => r.data)
export const getDueWords = (params = {}) => api.get('/review/due', { params }).then((r) => r.data)
export const submitReviewAnswer = (wordId, result) =>
  api.post(`/review/${wordId}/answer`, { result }).then((r) => r.data)

/* ========= 学习统计 ========= */
export const getStatsSummary = () => api.get('/stats/summary').then((r) => r.data)

/* ========= 大模型配置 ========= */
export const getLlmConfig = () => api.get('/llm/config').then((r) => r.data)
export const saveLlmConfig = (data) => api.put('/llm/config', data).then((r) => r.data)
export const testLlmConfig = (data) => api.post('/llm/test', data).then((r) => r.data)
export const resetLlmConfig = () => api.delete('/llm/config').then((r) => r.data)
