<template>
  <div class="cw" :class="[`cw-${mode}`, { 'side-open': sideOpen }]">
    <!-- 左侧：会话管理（类似 DeepSeek「最近」列表） -->
    <aside class="cw-side">
      <button class="cw-new" @click="newSession">
        <el-icon><Plus /></el-icon>
        <span>新建对话</span>
      </button>

      <div class="cw-side-body">
        <template v-if="!memoryOpen">
          <div class="cw-side-label">
            <span>最近</span>
            <button v-if="sessions.length" class="cw-clear" title="清空全部会话" @click="clearSessions">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
          <div class="cw-sessions">
            <div
              v-for="s in sessions"
              :key="s.id"
              class="cw-item"
              :class="{ on: current && current.id === s.id }"
              @click="pickSession(s)"
            >
              <el-icon class="cw-item-icon"><ChatLineRound /></el-icon>
              <span class="cw-item-title">{{ s.title || '新会话' }}</span>
              <span class="cw-item-ops">
                <button title="重命名" @click.stop="renameSession(s)">
                  <el-icon><EditPen /></el-icon>
                </button>
                <button title="删除" @click.stop="removeSession(s)">
                  <el-icon><Delete /></el-icon>
                </button>
              </span>
            </div>
            <div v-if="!sessions.length" class="cw-empty">还没有会话，点上方「新建对话」开始</div>
          </div>
        </template>

        <!-- 长期记忆 -->
        <template v-else>
          <div class="cw-side-label">
            <span>长期记忆</span>
            <button v-if="memories.length" class="cw-clear" title="清空记忆" @click="clearMemories">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
          <p class="cw-mem-hint">跨会话保留的事实与偏好，回答时会自动召回。</p>
          <div class="cw-sessions">
            <div v-for="m in memories" :key="m.id" class="cw-mem">
              <el-tag size="small" :type="m.kind === 'fact' ? 'warning' : 'info'" effect="plain">
                {{ m.kind === 'fact' ? '事实' : '会话' }}
              </el-tag>
              <span class="cw-mem-text">{{ m.content }}</span>
              <button class="cw-mem-del" title="删除" @click="removeMemory(m)">
                <el-icon><Close /></el-icon>
              </button>
            </div>
            <div v-if="!memories.length" class="cw-empty">暂无长期记忆，对话几轮后会自动沉淀</div>
          </div>
        </template>
      </div>

      <div class="cw-side-foot">
        <button class="cw-foot-btn" :class="{ on: memoryOpen }" @click="toggleMemory">
          <el-icon><Collection /></el-icon>
          <span>记忆</span>
          <i v-if="memories.length">{{ memories.length }}</i>
        </button>
      </div>
    </aside>

    <!-- 右侧：对话区 -->
    <section class="cw-main">
      <header class="cw-head">
        <button class="cw-head-btn only-narrow" title="会话" @click="sideOpen = !sideOpen">
          <el-icon><Expand /></el-icon>
        </button>
        <div class="cw-head-title">
          <b>{{ current ? current.title : '智能问答' }}</b>
          <small>{{ headSub }}</small>
        </div>
        <span v-if="hasSummary" class="cw-chip">含历史摘要</span>
        <button
          class="cw-head-btn"
          :class="{ on: setupOpen }"
          title="模型与提示词设置"
          @click="setupOpen = !setupOpen"
        >
          <el-icon><Setting /></el-icon>
        </button>
        <button class="cw-head-btn" title="新建对话" @click="newSession">
          <el-icon><Plus /></el-icon>
        </button>
        <button v-if="mode === 'panel'" class="cw-head-btn" title="收起" @click="$emit('close')">
          <el-icon><Minus /></el-icon>
        </button>
      </header>

      <div v-if="setupOpen" class="cw-setup">
        <el-select
          v-model="llmId"
          size="small"
          class="cw-pick"
          placeholder="选择 LLM 模型"
          @change="applySelection"
        >
          <el-option v-for="m in llmOptions" :key="m.id" :label="m.name" :value="m.id">
            <span class="cw-opt-name">{{ m.name }}</span>
            <span class="cw-opt-sub">{{ m.model_name }}</span>
          </el-option>
        </el-select>

        <el-select
          v-model="promptId"
          size="small"
          clearable
          class="cw-pick"
          placeholder="不使用提示词"
          @change="applySelection"
        >
          <el-option-group v-for="g in promptGroups" :key="g.scene" :label="g.label">
            <el-option v-for="p in g.items" :key="p.id" :label="p.name" :value="p.id" />
          </el-option-group>
        </el-select>

        <label class="cw-rag" title="关闭后不检索知识库，直接由大模型作答">
          <el-switch v-model="useRag" size="small" @change="applySelection" />
          <span>知识库召回</span>
        </label>
      </div>

      <div ref="scrollRef" class="cw-msgs">
        <div v-if="!messages.length && !streaming" class="cw-welcome">
          <div class="cw-hi">你好，我是智析助手</div>
          <p>可以问我负荷与电价预测、气象特征影响、模型指标解读、报价策略等问题。未命中知识库时会直接依据大模型回答。</p>
          <div class="cw-chips">
            <button v-for="q in presets" :key="q" @click="send(q)">{{ q }}</button>
          </div>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="cw-msg" :class="m.role">
          <div class="cw-avatar">
            <el-icon v-if="m.role === 'assistant'"><MagicStick /></el-icon>
            <span v-else>我</span>
          </div>
          <div class="cw-bubble">
            <div v-if="m.role === 'assistant'" class="md" v-html="m.html" />
            <div v-else class="cw-plain">{{ m.content }}</div>
            <div v-if="m.snippets && m.snippets.length" class="cw-snips">
              <el-tag v-for="s in m.snippets.slice(0, 4)" :key="s.idx + (s.source || '')" size="small" type="info">
                {{ s.source }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 流式输出中 -->
        <div v-if="streaming" class="cw-msg assistant">
          <div class="cw-avatar"><el-icon><MagicStick /></el-icon></div>
          <div class="cw-bubble">
            <div v-if="streamText" class="md" v-html="renderedStream" />
            <div v-else-if="thinkText" class="cw-think-box">
              <div class="cw-think">
                <span class="cw-think-orb" />
                <span>深度思考中 · 已推理 {{ thinkLen }} 字</span>
              </div>
              <div class="cw-think-body">{{ thinkText }}</div>
            </div>
            <div v-else class="cw-typing"><i /><i /><i /></div>
            <span class="cw-caret" />
          </div>
        </div>
      </div>

      <div class="cw-composer">
        <el-input
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          resize="none"
          placeholder="输入问题，Enter 发送 / Shift+Enter 换行"
          @keydown.enter="onEnter"
        />
        <el-button v-if="streaming" type="danger" plain @click="stop">
          <el-icon><VideoPause /></el-icon>
        </el-button>
        <el-button v-else type="primary" :disabled="!draft.trim()" @click="send()">
          <el-icon><Promotion /></el-icon>
        </el-button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  clearChatMemories, clearChatSessions, createChatSession, deleteChatMemory,
  deleteChatSession, genChatTitle, listChatMemories, listChatMessages,
  listChatSessions, listLLM, listPrompts, renameChatSession, updateChatSession
} from '@/api'
import { streamChat } from '@/api/chatStream'

const props = defineProps({
  mode: { type: String, default: 'panel' }
})
defineEmits(['close'])

const LS_KEY = 'chat.llm.pref'

const SCENE_LABEL = {
  qa: '智能问答',
  insight: '洞察报告',
  predict: '数据预测',
  power_decision: '电力决策',
  price_forecast: '电价预测',
  predict_risk: '预测风险',
  power_train: '训练解读'
}

const sessions = ref([])
const current = ref(null)
const messages = ref([])
const memories = ref([])
const memoryOpen = ref(false)
const sideOpen = ref(false)
const draft = ref('')
const streaming = ref(false)
const streamText = ref('')
const thinkLen = ref(0)
const thinkText = ref('')
const hasSummary = ref(false)
const scrollRef = ref()

// 推理设置：LLM 模型 / 提示词 / 是否召回知识库
const setupOpen = ref(true)
const llmOptions = ref([])
const promptOptions = ref([])
const llmId = ref(null)
const promptId = ref(null)
const useRag = ref(true)

const presets = [
  '用电负荷预测主要受哪些气象特征影响？',
  '日前电价的误差形态说明什么？',
  '极端天气下的报价要注意什么？'
]

let controller = null
let streamBuf = ''
let renderTimer = null

const renderedStream = computed(() => marked.parse(streamText.value || ''))
const headSub = computed(() => {
  const n = current.value ? current.value.message_count || 0 : 0
  return n ? `已 ${n} 条消息 · 短期记忆最近 4 轮` : '气象 · 电力 · 数据分析'
})

const promptGroups = computed(() => {
  const groups = new Map()
  promptOptions.value.forEach((p) => {
    const scene = p.scene || 'other'
    if (!groups.has(scene)) groups.set(scene, [])
    groups.get(scene).push(p)
  })
  return [...groups.entries()]
    .map(([scene, items]) => ({ scene, label: SCENE_LABEL[scene] || scene, items }))
    .sort((a, b) => (a.scene === 'qa' ? -1 : b.scene === 'qa' ? 1 : a.scene.localeCompare(b.scene)))
})

const readPref = () => {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || 'null') || {}
  } catch {
    return {}
  }
}

const savePref = () => {
  localStorage.setItem(LS_KEY, JSON.stringify({
    llm_config_id: llmId.value ?? null,
    prompt_id: promptId.value ?? null,
    use_rag: useRag.value ? 1 : 0
  }))
}

function toView(rows) {
  return rows.map((m) => ({
    role: m.role,
    content: m.content || '',
    snippets: m.snippets || [],
    html: m.role === 'assistant' ? marked.parse(m.content || '') : ''
  }))
}

const scrollToEnd = async () => {
  await nextTick()
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function scheduleRender() {
  if (renderTimer) return
  renderTimer = setTimeout(() => {
    renderTimer = null
    streamText.value = streamBuf
  }, 60)
}

async function loadOptions() {
  const [llmRes, promptRes] = await Promise.all([
    listLLM().catch(() => ({ data: [] })),
    listPrompts().catch(() => ({ data: [] }))
  ])
  llmOptions.value = llmRes.data || []
  promptOptions.value = promptRes.data || []
}

async function applySelection() {
  savePref()
  if (!current.value) return
  try {
    const res = await updateChatSession(current.value.id, {
      llm_config_id: llmId.value ?? null,
      prompt_id: promptId.value ?? null,
      use_rag: useRag.value ? 1 : 0
    })
    upsertSession(res.data)
    current.value = { ...current.value, ...res.data }
  } catch {
    ElMessage.error('模型设置保存失败')
  }
}

/** 会话有显式设置就用会话的，否则用上次选择，最后才落到系统默认模型。 */
function syncSelection(session) {
  const pref = readPref()
  const fallbackLlm = pref.llm_config_id ?? (llmOptions.value.find((m) => Number(m.is_default) === 1) || llmOptions.value[0] || {}).id ?? null
  llmId.value = (session && session.llm_config_id) ?? fallbackLlm
  promptId.value = (session && session.prompt_id) ?? pref.prompt_id ?? null
  if (session && session.use_rag !== null && session.use_rag !== undefined) {
    useRag.value = !!Number(session.use_rag)
  } else if (pref.use_rag !== undefined) {
    useRag.value = !!Number(pref.use_rag)
  } else {
    useRag.value = true
  }
}

async function loadSessions() {
  const res = await listChatSessions()
  sessions.value = res.data || []
}

async function loadMessages(id) {
  const res = await listChatMessages(id)
  messages.value = toView(res.data || [])
  await scrollToEnd()
}

async function loadMemories() {
  const res = await listChatMemories({ limit: 100 })
  memories.value = res.data || []
}

async function toggleMemory() {
  memoryOpen.value = !memoryOpen.value
  if (memoryOpen.value) await loadMemories()
}

function upsertSession(row) {
  if (!row || !row.id) return
  const idx = sessions.value.findIndex((x) => x.id === row.id)
  if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...row }
  else sessions.value = [row, ...sessions.value]
  sessions.value = [...sessions.value].sort((a, b) => (b.id || 0) - (a.id || 0))
}

async function pickSession(s) {
  if (streaming.value) return
  current.value = s
  memoryOpen.value = false
  sideOpen.value = false
  hasSummary.value = !!s.has_summary
  syncSelection(s)
  await loadMessages(s.id)
}

async function newSession() {
  if (streaming.value) return
  savePref()
  const res = await createChatSession({
    llm_config_id: llmId.value ?? null,
    prompt_id: promptId.value ?? null,
    use_rag: useRag.value ? 1 : 0
  })
  const s = res.data
  upsertSession(s)
  current.value = s
  messages.value = []
  hasSummary.value = false
  memoryOpen.value = false
  sideOpen.value = false
  draft.value = ''
}

async function renameSession(s) {
  try {
    const { value } = await ElMessageBox.prompt('输入新的会话标题', '重命名会话', {
      inputValue: s.title || '新会话',
      inputPattern: /\S+/,
      inputErrorMessage: '标题不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消'
    })
    const res = await renameChatSession(s.id, value.trim())
    upsertSession(res.data)
    if (current.value && current.value.id === s.id) current.value = { ...current.value, ...res.data }
    ElMessage.success('标题已更新')
  } catch (e) { /* 取消 */ }
}

async function removeSession(s) {
  try {
    await ElMessageBox.confirm(`确认删除会话「${s.title || '新会话'}」？该会话的消息将一并删除。`, '删除会话', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消'
    })
  } catch (e) {
    return
  }
  await deleteChatSession(s.id)
  sessions.value = sessions.value.filter((x) => x.id !== s.id)
  if (current.value && current.value.id === s.id) {
    current.value = sessions.value[0] || null
    if (current.value) await loadMessages(current.value.id)
    else messages.value = []
  }
  ElMessage.success('已删除会话')
}

async function clearSessions() {
  try {
    await ElMessageBox.confirm('确认清空全部会话与长期记忆？此操作不可恢复。', '清空会话', {
      type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消'
    })
  } catch (e) {
    return
  }
  await clearChatSessions()
  sessions.value = []
  memories.value = []
  current.value = null
  messages.value = []
  ElMessage.success('已清空会话')
}

async function removeMemory(m) {
  await deleteChatMemory(m.id)
  memories.value = memories.value.filter((x) => x.id !== m.id)
}

async function clearMemories() {
  await clearChatMemories()
  memories.value = []
  ElMessage.success('已清空长期记忆')
}

function onEnter(e) {
  if (e.shiftKey) return
  e.preventDefault()
  send()
}

function stop() {
  if (controller) controller.abort()
}

async function send(preset) {
  const text = (preset || draft.value || '').trim()
  if (!text || streaming.value) return
  if (!current.value) await newSession()

  draft.value = ''
  messages.value.push({ role: 'user', content: text, snippets: [], html: '' })
  streaming.value = true
  streamBuf = ''
  streamText.value = ''
  thinkLen.value = 0
  thinkText.value = ''
  await scrollToEnd()

  controller = new AbortController()
  const sid = current.value.id

  try {
    await streamChat(sid, {
      question: text,
      llm_config_id: llmId.value ?? null,
      prompt_id: promptId.value ?? null,
      use_rag: useRag.value ? 1 : 0
    }, {
      start: (e) => {
        hasSummary.value = !!e.has_summary
      },
      thinking: (e) => {
        thinkLen.value = e.length || 0
        thinkText.value = (thinkText.value + (e.text || '')).slice(-900)
        scrollToEnd()
      },
      delta: (e) => {
        streamBuf += e.content || ''
        scheduleRender()
      },
      replace: (e) => {
        streamBuf = e.content || ''
        scheduleRender()
      },
      done: async (e) => {
        if (renderTimer) { clearTimeout(renderTimer); renderTimer = null }
        streamText.value = streamBuf
        const sess = e.session || {}
        messages.value = toView(sess.messages || [])
        current.value = { ...(current.value || {}), ...sess }
        upsertSession(sess)
        hasSummary.value = !!sess.has_summary
        streaming.value = false

        if (e.title_pending) {
          try {
            const t = await genChatTitle(sid, { question: text, answer: e.answer || '' })
            if (t.data) {
              upsertSession(t.data)
              current.value = { ...(current.value || {}), ...t.data }
            }
          } catch (err) { /* 标题失败不影响对话 */ }
        }
        loadMemories().catch(() => {})
      },
      error: (e) => {
        ElMessage.error(e.message || '回答失败')
      }
    }, controller.signal)
  } catch (err) {
    if (err.name !== 'AbortError') ElMessage.error(err.message || '请求失败')
  } finally {
    if (renderTimer) { clearTimeout(renderTimer); renderTimer = null }
    streaming.value = false
    streamText.value = ''
    streamBuf = ''
    thinkLen.value = 0
    thinkText.value = ''
    controller = null
    await scrollToEnd()
  }
}

async function bootstrap() {
  await loadOptions()
  const pref = readPref()
  llmId.value = pref.llm_config_id ?? (llmOptions.value.find((m) => Number(m.is_default) === 1) || llmOptions.value[0] || {}).id ?? null
  promptId.value = pref.prompt_id ?? null
  useRag.value = pref.use_rag === undefined ? true : !!Number(pref.use_rag)

  await loadSessions()
  if (sessions.value.length) await pickSession(sessions.value[0])
  else await newSession()
  loadMemories().catch(() => {})
}

onMounted(bootstrap)
defineExpose({ bootstrap, focusComposer: () => draft.value })
</script>

<style scoped>
.cw {
  display: flex;
  min-height: 0;
  height: 100%;
  background: var(--panel);
  color: var(--text);
}

/* ---------------- 左侧会话栏 ---------------- */
.cw-side {
  flex: none;
  width: 224px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--line);
  background: var(--panel-soft);
}

.cw-new {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 10px 10px 6px;
  height: 38px;
  border: 0;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #1d6fd8 60%, #0f766e);
  box-shadow: 0 8px 20px rgba(29, 111, 216, 0.28);
}
.cw-new:hover { filter: brightness(1.06); }

.cw-side-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.cw-side-label {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px 4px;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--muted);
}

.cw-clear {
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--muted);
  font-size: 12px;
  padding: 2px;
}
.cw-clear:hover { color: #ef4444; }

.cw-mem-hint {
  flex: none;
  margin: 0 12px 6px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--muted);
}

.cw-sessions {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 8px 10px;
}

.cw-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 9px;
  margin-bottom: 2px;
  border-radius: 9px;
  cursor: pointer;
  font-size: 13px;
}
.cw-item:hover { background: rgba(29, 111, 216, 0.08); }
.cw-item.on { background: var(--accent-soft); }
.cw-item-icon { flex: none; color: var(--muted); font-size: 14px; }
.cw-item.on .cw-item-icon { color: var(--accent); }

.cw-item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cw-item-ops {
  flex: none;
  display: none;
  gap: 1px;
}
.cw-item:hover .cw-item-ops { display: flex; }
.cw-item-ops button {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
  color: var(--muted);
  background: transparent;
  font-size: 12px;
}
.cw-item-ops button:hover { background: var(--accent-soft); color: var(--accent); }

.cw-mem {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 7px 9px;
  margin-bottom: 6px;
  border-radius: 9px;
  font-size: 12px;
  line-height: 1.6;
  background: rgba(148, 163, 184, 0.1);
}
.cw-mem-text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.cw-mem-del {
  flex: none;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--muted);
  font-size: 11px;
  padding: 2px;
}
.cw-mem-del:hover { color: #ef4444; }

.cw-empty {
  padding: 22px 10px;
  text-align: center;
  font-size: 12px;
  line-height: 1.7;
  color: var(--muted);
}

.cw-side-foot {
  flex: none;
  padding: 8px;
  border-top: 1px solid var(--line);
}

.cw-foot-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  border: 0;
  border-radius: 9px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text);
  background: transparent;
}
.cw-foot-btn:hover { background: rgba(29, 111, 216, 0.08); }
.cw-foot-btn.on { background: var(--accent-soft); color: var(--accent); }
.cw-foot-btn i {
  margin-left: auto;
  font-style: normal;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(29, 111, 216, 0.16);
}

/* ---------------- 右侧对话区 ---------------- */
.cw-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.cw-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  color: #fff;
  background: linear-gradient(120deg, #1d6fd8, #0f766e);
}

.cw-head-btn {
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  cursor: pointer;
  color: #eaf5ff;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.18);
}
.cw-head-btn:hover { background: rgba(255, 255, 255, 0.28); }
.cw-head-btn.on { background: #fff; color: #1d6fd8; border-color: #fff; }
.only-narrow { display: none; }

/* 模型 / 提示词 / RAG 设置行 */
.cw-setup {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-soft);
}
.cw-pick { flex: 1 1 148px; min-width: 122px; max-width: 228px; }
.cw-opt-name { margin-right: 8px; }
.cw-opt-sub { color: var(--muted); font-size: 11px; }

.cw-rag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  white-space: nowrap;
}

.cw-head-title { flex: 1; min-width: 0; }
.cw-head-title b {
  display: block;
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cw-head-title small {
  display: block;
  font-size: 11px;
  color: rgba(226, 240, 255, 0.82);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cw-chip {
  flex: none;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  color: #d9f99d;
  background: rgba(132, 204, 22, 0.2);
  border: 1px solid rgba(190, 242, 100, 0.4);
}

.cw-msgs {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
}

.cw-welcome { padding: 6px 2px; }
.cw-hi { font-size: 15px; font-weight: 700; }
.cw-welcome p { margin-top: 6px; font-size: 12.5px; line-height: 1.75; color: var(--muted); }
.cw-chips { display: flex; flex-direction: column; gap: 7px; margin-top: 14px; }
.cw-chips button {
  text-align: left;
  padding: 9px 11px;
  border-radius: 10px;
  font-size: 12.5px;
  cursor: pointer;
  color: var(--text);
  background: var(--panel-soft);
  border: 1px solid var(--line);
}
.cw-chips button:hover { border-color: var(--accent); background: var(--accent-soft); }

.cw-msg { display: flex; gap: 9px; margin-bottom: 15px; }
.cw-msg.user { flex-direction: row-reverse; }

.cw-avatar {
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #0f766e);
}
.cw-msg.user .cw-avatar { background: linear-gradient(135deg, #64748b, #334155); }

.cw-bubble {
  max-width: 84%;
  padding: 9px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.72;
  color: var(--text);
  background: var(--panel-soft);
  border: 1px solid var(--line);
  overflow-wrap: anywhere;
}
.cw-msg.user .cw-bubble { background: var(--accent-soft); border-color: #c5daf5; }
.cw-plain { white-space: pre-wrap; }

.md :deep(h1), .md :deep(h2), .md :deep(h3) { font-size: 14px; margin: 8px 0 6px; }
.md :deep(p) { margin: 6px 0; }
.md :deep(ul), .md :deep(ol) { padding-left: 18px; margin: 6px 0; }
.md :deep(code) {
  background: rgba(29, 111, 216, 0.1);
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 12px;
}
.md :deep(pre) { background: #0f1e30; color: #dbeafe; padding: 10px; border-radius: 8px; overflow-x: auto; }
.md :deep(table) { border-collapse: collapse; width: 100%; font-size: 12px; }
.md :deep(th), .md :deep(td) { border: 1px solid var(--line); padding: 4px 6px; }

.cw-snips { margin-top: 8px; display: flex; gap: 5px; flex-wrap: wrap; }

.cw-typing { display: flex; gap: 4px; align-items: center; padding: 6px 2px; }
.cw-typing i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.4;
  animation: cw-blink 1.2s infinite;
}
.cw-typing i:nth-child(2) { animation-delay: 0.2s; }
.cw-typing i:nth-child(3) { animation-delay: 0.4s; }

.cw-think-box { min-width: 260px; }
.cw-think-body {
  margin-top: 6px;
  max-height: 148px;
  overflow-y: auto;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--muted);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: rgba(148, 163, 184, 0.1);
  border-left: 2px solid rgba(29, 111, 216, 0.35);
}

.cw-think {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 2px;
  font-size: 12.5px;
  font-weight: 600;
  background: linear-gradient(90deg, #1d6fd8, #0f766e, #1d6fd8);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: cw-flow 2.4s linear infinite;
}
.cw-think-orb {
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: linear-gradient(135deg, #38bdf8, #0f766e);
  box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.6);
  animation: cw-orb 1.4s ease-out infinite;
}

@keyframes cw-flow {
  0% { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
@keyframes cw-orb {
  0% { box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.55); }
  100% { box-shadow: 0 0 0 10px rgba(56, 189, 248, 0); }
}

.cw-caret {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--accent);
  animation: cw-caret 1s steps(2) infinite;
}

.cw-composer {
  flex: none;
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--line);
  background: var(--panel);
}
.cw-composer :deep(.el-textarea) { flex: 1; }
.cw-composer :deep(.el-textarea__inner) { font-size: 13px; }

@keyframes cw-blink {
  0%, 100% { opacity: 0.25; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-2px); }
}
@keyframes cw-caret {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}

/* ---------------- 窄屏：会话栏改为抽屉 ---------------- */
@media (max-width: 900px) {
  .only-narrow { display: grid; }
  .cw-side {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 3;
    width: 232px;
    transform: translateX(-100%);
    transition: transform 0.22s ease;
    box-shadow: 0 12px 40px rgba(15, 30, 48, 0.28);
  }
  .cw.side-open .cw-side { transform: none; }
  .cw { position: relative; }
}
</style>
