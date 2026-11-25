import Cookies from 'js-cookie'

/**
 * 流式问答（SSE over fetch）。
 *
 * 事件类型：
 * - start   : { session_id, snippets, memories, has_summary }
 * - delta   : { content }            逐段回答
 * - replace : { content }            正文需要整体替换（清洗推理内容）
 * - done    : { session, answer, snippets, memories, title_pending }
 * - error   : { message }
 */
export async function streamChat(sessionId, payload, handlers = {}, signal) {
  const token = Cookies.get('token')
  const res = await fetch(`/api/chat/sessions/${sessionId}/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(payload || {}),
    signal
  })

  if (res.status === 401) {
    Cookies.remove('token')
    Cookies.remove('user')
    window.location.href = '/login'
    return
  }
  if (!res.ok || !res.body) {
    let message = `请求失败（${res.status}）`
    try {
      const body = await res.json()
      if (body && body.message) message = body.message
    } catch { /* 忽略解析失败 */ }
    throw new Error(message)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatch = (raw) => {
    const line = raw.split('\n').find((l) => l.startsWith('data:'))
    if (!line) return
    const text = line.slice(5).trim()
    if (!text) return
    let event
    try { event = JSON.parse(text) } catch { return }
    const fn = handlers[event.type]
    if (fn) fn(event)
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    blocks.forEach(dispatch)
  }
  if (buffer.trim()) dispatch(buffer)
}
