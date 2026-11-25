import request from '@/utils/request'

export const getOverview = () => request({ url: '/dashboard/overview' })

export const listProjects = (params) => request({ url: '/project/list', params })
export const getProject = (id) => request({ url: `/project/${id}` })
export const createProject = (data) => request({ url: '/project', method: 'post', data })
export const updateProject = (id, data) => request({ url: `/project/${id}`, method: 'put', data })
export const deleteProject = (id) => request({ url: `/project/${id}`, method: 'delete' })

export const listDatasets = (params) => request({ url: '/dataset/list', params })
export const uploadDatasets = (form) => request({ url: '/dataset/upload', method: 'post', data: form, headers: { 'Content-Type': 'multipart/form-data' } })
export const previewDataset = (id, params) => request({ url: `/dataset/${id}/preview`, params })
export const getDataset = (id) => request({ url: `/dataset/${id}` })
export const updateRoles = (id, roles) => request({ url: `/dataset/${id}/roles`, method: 'put', data: { roles } })
export const updateDatasetSchema = (id, data) => request({ url: `/dataset/${id}/schema`, method: 'put', data })
export const updateDatasetMeta = (id, data) => request({ url: `/dataset/${id}/meta`, method: 'put', data })
export const deleteDataset = (id) => request({ url: `/dataset/${id}`, method: 'delete' })
export const suggestJoins = (dataset_ids) => request({ url: '/dataset/suggest-joins', method: 'post', data: { dataset_ids } })
export const createBundle = (data) => request({ url: '/dataset/bundle', method: 'post', data })
export const rebuildBundle = (id, data) => request({ url: `/dataset/bundle/${id}/rebuild`, method: 'put', data })
export const listBundles = (params) => request({ url: '/dataset/bundle/list', params })
export const getBundle = (id) => request({ url: `/dataset/bundle/${id}` })
export const previewBundle = (id, params) => request({ url: `/dataset/bundle/${id}/preview`, params })
export const deleteBundle = (id) => request({ url: `/dataset/bundle/${id}`, method: 'delete' })
export const importDemo = (project_id, max_rows = 80000) => request({
  url: '/dataset/import-demo',
  method: 'post',
  data: { project_id, max_rows }
})
export const importExtremeWeather = (project_id, force_rebuild = false) => request({
  url: '/dataset/import-extreme-weather',
  method: 'post',
  data: { project_id, force_rebuild }
})

export const listDataSources = (params) => request({ url: '/datasource/list', params })
export const getDataSource = (id) => request({ url: `/datasource/${id}` })
export const saveDataSource = (data, id) => id
  ? request({ url: `/datasource/${id}`, method: 'put', data })
  : request({ url: '/datasource', method: 'post', data })
export const deleteDataSource = (id) => request({ url: `/datasource/${id}`, method: 'delete' })
export const testDataSource = (data, id) => id
  ? request({ url: `/datasource/${id}/test`, method: 'post', data: data || {} })
  : request({ url: '/datasource/test', method: 'post', data })
export const listSourceDatabases = (id) => request({ url: `/datasource/${id}/databases` })
export const listSourceTables = (id, databases) => request({
  url: `/datasource/${id}/tables`,
  method: 'post',
  data: { databases }
})
export const importSourceTables = (id, data) => request({
  url: `/datasource/${id}/import`,
  method: 'post',
  data
})
export const previewSourceTable = (id, data) => request({
  url: `/datasource/${id}/preview`,
  method: 'post',
  data
})
export const attachLiveTable = (id, data) => request({
  url: `/datasource/${id}/attach-live`,
  method: 'post',
  data
})

export const listOps = () => request({ url: '/clean/ops' })
export const listRules = (params) => request({ url: '/clean/rule/list', params })
export const getRule = (id) => request({ url: `/clean/rule/${id}` })
export const saveRule = (data, id) => id
  ? request({ url: `/clean/rule/${id}`, method: 'put', data })
  : request({ url: '/clean/rule', method: 'post', data })
export const copyRule = (id, data) => request({
  url: `/clean/rule/${id}/copy`,
  method: 'post',
  data: data || {}
})
export const deleteRule = (id) => request({ url: `/clean/rule/${id}`, method: 'delete' })
export const previewClean = (data) => request({ url: '/clean/preview', method: 'post', data })
export const probeCleanTokens = (data) => request({ url: '/clean/probe-tokens', method: 'post', data })
export const getCleanSourceSchema = (params) => request({ url: '/clean/source-schema', params })
export const bindRule = (data) => request({ url: '/clean/bind', method: 'post', data })
export const listBindings = (params) => request({ url: '/clean/bind/list', params })
export const getBinding = (id) => request({ url: `/clean/bind/${id}` })
export const previewBinding = (id, params) => request({ url: `/clean/bind/${id}/preview`, params })
export const deleteBinding = (id, force = false) => request({
  url: `/clean/bind/${id}`,
  method: 'delete',
  params: force ? { force: 1 } : undefined
})

export const getZoo = () => request({ url: '/model/zoo' })
export const listJobs = (params) => request({ url: '/model/list', params })
export const getJob = (id) => request({ url: `/model/${id}` })
export const deleteJob = (id) => request({ url: `/model/${id}`, method: 'delete' })
export const deleteJobs = (ids) => request({ url: '/model/batch-delete', method: 'post', data: { ids } })
export const startTrain = (data) => request({ url: '/model/train', method: 'post', data })
export const compareJobs = (job_ids) => request({ url: '/model/compare', method: 'post', data: { job_ids } })
export const createInsight = (data) => request({ url: '/model/insight', method: 'post', data })
export const listInsights = (params) => request({ url: '/model/insight/list', params })
export const getInsight = (id) => request({ url: `/model/insight/${id}` })
export const deleteInsight = (id) => request({ url: `/model/insight/${id}`, method: 'delete' })
export const deleteInsights = (ids) => request({ url: '/model/insight/batch-delete', method: 'post', data: { ids } })
export const exportTrainPack = (id) => request({ url: `/model/${id}/export`, responseType: 'blob' })
export const exportInsightMd = (id) => request({ url: `/model/${id}/insight.md`, responseType: 'blob' })
export const exportInsightById = (id, fmt = 'md') => request({
  url: `/model/insight/${id}/export.${fmt}`,
  responseType: 'blob'
})

export const predictColumns = (id) => request({ url: `/predict/columns/${id}` })
export const runPredict = (data) => request({ url: '/predict/run', method: 'post', data })
export const runPredictExcel = (form) => request({ url: '/predict/run', method: 'post', data: form, headers: { 'Content-Type': 'multipart/form-data' } })
export const listPredicts = (params) => request({ url: '/predict/list', params })
export const getPredict = (id) => request({ url: `/predict/${id}` })
export const deletePredict = (id) => request({ url: `/predict/${id}`, method: 'delete' })
export const deletePredicts = (ids) => request({ url: '/predict/batch-delete', method: 'post', data: { ids } })
export const analyzePredict = (id, data) => request({ url: `/predict/${id}/analyze`, method: 'post', data })

export const listLLM = (params) => request({ url: '/llm/list', params })
export const saveLLM = (data, id) => id
  ? request({ url: `/llm/${id}`, method: 'put', data })
  : request({ url: '/llm', method: 'post', data })
export const deleteLLM = (id) => request({ url: `/llm/${id}`, method: 'delete' })
export const listPrompts = (params) => request({ url: '/prompt/list', params })
export const savePrompt = (data, id) => id
  ? request({ url: `/prompt/${id}`, method: 'put', data })
  : request({ url: '/prompt', method: 'post', data })
export const deletePrompt = (id) => request({ url: `/prompt/${id}`, method: 'delete' })

export const ragStatus = () => request({ url: '/rag/status' })
export const ragDocs = (params) => request({ url: '/rag/docs', params })
export const ragDocDetail = (name) => request({ url: '/rag/docs/detail', params: { name } })
export const ragChunks = (params) => request({ url: '/rag/chunks', params })
export const ragUpload = (form) => request({ url: '/rag/docs', method: 'post', data: form, headers: { 'Content-Type': 'multipart/form-data' } })
export const ragDelete = (name) => request({ url: '/rag/docs', method: 'delete', data: { name } })
export const ragRebuild = () => request({ url: '/rag/rebuild', method: 'post' })
export const ragAsk = (data) => request({ url: '/rag/ask', method: 'post', data })

export const listChatSessions = (params) => request({ url: '/chat/sessions', params })
export const createChatSession = (data) => request({ url: '/chat/sessions', method: 'post', data: data || {} })
export const getChatSession = (id) => request({ url: `/chat/sessions/${id}` })
export const renameChatSession = (id, title) => request({ url: `/chat/sessions/${id}`, method: 'put', data: { title } })
export const updateChatSession = (id, data) => request({ url: `/chat/sessions/${id}`, method: 'put', data })
export const deleteChatSession = (id) => request({ url: `/chat/sessions/${id}`, method: 'delete' })
export const clearChatSessions = () => request({ url: '/chat/sessions', method: 'delete' })
export const listChatMessages = (id) => request({ url: `/chat/sessions/${id}/messages` })
export const askChat = (id, data) => request({ url: `/chat/sessions/${id}/ask`, method: 'post', data })
export const genChatTitle = (id, data) => request({ url: `/chat/sessions/${id}/title`, method: 'post', data: data || {} })
export const listChatMemories = (params) => request({ url: '/chat/memories', params })
export const deleteChatMemory = (id) => request({ url: `/chat/memories/${id}`, method: 'delete' })
export const clearChatMemories = () => request({ url: '/chat/memories', method: 'delete' })

export const graphComponents = () => request({ url: '/graph/components' })
export const listGraphs = (params) => request({ url: '/graph/list', params })
export const getGraph = (id) => request({ url: `/graph/${id}` })
export const saveGraph = (data, id) => id
  ? request({ url: `/graph/${id}`, method: 'put', data })
  : request({ url: '/graph', method: 'post', data })
export const cloneGraph = (id, data) => request({ url: `/graph/${id}/clone`, method: 'post', data })
export const runGraph = (id) => request({ url: `/graph/${id}/run`, method: 'post' })
export const getGraphRun = (id) => request({ url: `/graph/run/${id}` })
export const patchGraphSchedule = (id, data) => request({ url: `/graph/${id}/schedule`, method: 'put', data })
export const deleteGraph = (id) => request({ url: `/graph/${id}`, method: 'delete' })
export const deleteGraphs = (ids) => request({ url: '/graph/batch-delete', method: 'post', data: { ids } })
export const listGraphRuns = (params) => request({ url: '/graph/runs', params })

export const powerIngest = () => request({ url: '/power/ingest', method: 'post' })
export const powerCockpit = () => request({ url: '/power/cockpit' })
export const powerAlerts = () => request({ url: '/power/alerts' })
export const powerShock = (kind) => request({ url: '/power/shock', method: 'post', data: { kind } })
export const powerReport = () => request({ url: '/power/report', method: 'post' })
export const powerReportLatest = () => request({ url: '/power/report/latest' })

export const biCatalog = () => request({ url: '/bi/catalog' })
export const biSources = (params) => request({ url: '/bi/sources', params })
export const biSourceDetail = (kind, id) => request({ url: `/bi/source/${kind}/${id}` })
export const listBoards = (params) => request({ url: '/bi/list', params })
export const getBoard = (id) => request({ url: `/bi/${id}` })
export const saveBoard = (data, id) => id
  ? request({ url: `/bi/${id}`, method: 'put', data })
  : request({ url: '/bi', method: 'post', data })
export const deleteBoard = (id) => request({ url: `/bi/${id}`, method: 'delete' })
export const queryBoardLayout = (id, data) => request({ url: `/bi/${id}/query`, method: 'post', data })
export const queryBiWidget = (data) => request({ url: '/bi/query', method: 'post', data })
export const recommendBoard = (data) => request({ url: '/bi/recommend', method: 'post', data })
