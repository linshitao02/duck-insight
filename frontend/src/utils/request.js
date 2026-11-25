import axios from 'axios'
import { ElMessage } from 'element-plus'
import Cookies from 'js-cookie'

const service = axios.create({
  baseURL: '/api',
  timeout: 600000
})

let redirecting = false
function handleUnauthorized(message) {
  ElMessage.error(message || '登录已过期，请重新登录')
  Cookies.remove('token')
  Cookies.remove('user')
  if (redirecting) return
  redirecting = true
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
  setTimeout(() => { redirecting = false }, 1500)
}

service.interceptors.request.use((config) => {
  const token = Cookies.get('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

service.interceptors.response.use(
  async (response) => {
    if (response.config.responseType === 'blob') {
      const type = String(response.headers['content-type'] || '').toLowerCase()
      if (type.includes('application/json')) {
        const text = await response.data.text()
        let json = {}
        try { json = JSON.parse(text) } catch { json = { message: text } }
        ElMessage.error(json.message || '请求失败')
        return Promise.reject(new Error(json.message || '请求失败'))
      }
      return response
    }
    const res = response.data
    // 后端若返回了非法 JSON（例如 NaN/Infinity），axios 会退化成原始字符串，
    // 此时 res.code 是 undefined，直接按失败处理并给出可理解的原因。
    if (typeof res === 'string') {
      ElMessage.error('服务返回的数据无法解析，请重试或联系管理员')
      return Promise.reject(new Error('unparsable response'))
    }
    if (res.code !== 200) {
      if (res.code === 401) {
        handleUnauthorized(res.message)
        return Promise.reject(new Error(res.message || '请求失败'))
      }
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message || '请求失败'))
    }
    return res
  },
  (error) => {
    const status = error.response?.status
    const body = error.response?.data
    // 后端登录校验失败直接返回 HTTP 401，这里统一按「登录已过期」处理，避免只弹一段英文报错
    if (status === 401 && !String(error.config?.url || '').includes('/user/login')) {
      handleUnauthorized(body?.message)
      return Promise.reject(error)
    }
    ElMessage.error(body?.message || error.message || '网络错误')
    return Promise.reject(error)
  }
)

export default service
