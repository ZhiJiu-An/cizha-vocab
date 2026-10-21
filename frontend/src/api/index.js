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

// 本地库精确查找（v0.11）：搜索页据此判断「是否已收藏」，命中则不调用大模型
export const findLocalWord = (word) =>
  api.get('/words/lookup', { params: { word } }).then((r) => r.data)

/* ========= 批量操作（v0.11） ========= */
// 单请求 + 单事务，替代原来前端循环发 N 个单条请求
export const bulkDeleteWords = (ids) =>
  api.post('/words/bulk-delete', { ids }).then((r) => r.data)

export const bulkAddTags = (ids, tags) =>
  api.post('/words/bulk-tag', { ids, tags }).then((r) => r.data)

// 撤销删除：把删除时缓存的完整词条回灌（含复习进度与创建时间）
export const restoreWords = (items) =>
  api.post('/words/restore', { items }).then((r) => r.data)

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

// 错词本（v0.11）：按「忘记」次数降序，供复习页错词优先与统计页错词榜使用
export const getMistakes = (params = {}) =>
  api.get('/review/mistakes', { params }).then((r) => r.data)

// 重置复习进度（v0.11）：把档位 / 下次复习 / 累计次数清零，当作新词重学
export const resetReviewProgress = (wordId) =>
  api.post(`/review/${wordId}/reset`).then((r) => r.data)

/* ========= 学习统计 ========= */
export const getStatsSummary = (params = {}) =>
  api.get('/stats/summary', { params }).then((r) => r.data)

/* ========= 模型配置（v0.12：模型列表 + 提示词） ========= */
// 连通测试要真连一次模型，视觉模型还带图，故单独放宽超时
const TEST_TIMEOUT = 30000

export const listModels = () => api.get('/llm/models').then((r) => r.data)
// 新增 / 编辑都会先做连通测试，通过才写入
export const createModel = (data) => api.post('/llm/models', data).then((r) => r.data)
export const updateModel = (id, data) => api.put(`/llm/models/${id}`, data).then((r) => r.data)
export const deleteModel = (id) => api.delete(`/llm/models/${id}`).then((r) => r.data)
export const testModel = (data) =>
  api.post('/llm/models/test', data, { timeout: TEST_TIMEOUT }).then((r) => r.data)
export const setDefaultModel = (id) =>
  api.post(`/llm/models/${id}/default`).then((r) => r.data)
