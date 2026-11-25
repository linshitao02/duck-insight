<template>
  <div class="gate" :class="{ still: !motion }">
    <div class="streaks" aria-hidden="true">
      <i v-for="n in streaks" :key="n" :style="{ '--n': n }" />
    </div>

    <aside class="stage" aria-hidden="true">
      <div class="stage-bg" />
      <video
        v-if="motion && live"
        ref="videoRef"
        class="portrait"
        src="/login/duck-insight-idle.mp4"
        poster="/login/duck-insight-still.jpg"
        muted
        loop
        autoplay
        playsinline
        preload="auto"
        @error="live = false"
      />
      <img v-else class="portrait" src="/login/duck-insight-still.jpg" alt="" />
      <div class="lattice" />
      <div class="veil" />
      <p class="corner">SEE<br />THE DATA<br />KEEP<br />THE INSIGHT</p>
    </aside>

    <section class="panel">
      <div class="sheet">
      <header class="brand">
        <img src="/duck.png?v=insight" alt="" />
        <div>
          <strong>Duck Insight</strong>
          <em>DATA TO INSIGHT</em>
        </div>
      </header>

      <ol class="status">
        <li v-for="(item, index) in statuses" :key="item" :class="{ on: index === activeStatus }">{{ item }}</li>
      </ol>

      <h1>
        <span class="duck">Duck</span>
        <span class="insight">Insight</span>
      </h1>
      <p class="welcome">{{ isLogin ? '欢迎回来' : '建立你的分析台' }}</p>
      <p class="sub">
        {{ isLogin
          ? '通用数据分析平台。把接入、清洗、训练和预测收成可追溯的洞察。'
          : '注册后即可管理数据集、模型、看板和洞察报告。' }}
      </p>

      <div class="kpis">
        <div><b>Duck</b><span>看数入口</span></div>
        <div><b>Data</b><span>资产与模型</span></div>
        <div><b>Insight</b><span>结论可追溯</span></div>
      </div>

      <el-form v-if="isLogin" :model="loginForm" @keyup.enter="doLogin">
        <el-form-item>
          <el-input v-model="loginForm.username" size="large" placeholder="用户名" prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="loginForm.password" size="large" type="password" show-password placeholder="密码" prefix-icon="Lock" />
        </el-form-item>
        <el-button class="btn" :loading="loading" @click="doLogin">{{ loading ? '正在进入' : '进入平台' }}</el-button>
      </el-form>
      <el-form v-else :model="regForm" @keyup.enter="doRegister">
        <el-form-item>
          <el-input v-model="regForm.username" size="large" placeholder="用户名" prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="regForm.nickname" size="large" placeholder="昵称" prefix-icon="Postcard" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="regForm.password" size="large" type="password" show-password placeholder="密码" prefix-icon="Lock" />
        </el-form-item>
        <el-button class="btn" :loading="loading" @click="doRegister">{{ loading ? '正在创建' : '注册' }}</el-button>
      </el-form>

      <button class="switch" type="button" @click="isLogin = !isLogin">
        {{ isLogin ? '没有账号，去注册' : '已有账号，去登录' }}
      </button>
      <p v-if="isLogin" class="hint">默认管理员 admin / admin123</p>
      <pre class="term" aria-hidden="true">{{ typed }}<b>_</b></pre>
      <button class="intro" type="button" @click="introOpen = true">
        <span class="pulse" />
        系统简介
        <em>数据 · 模型 · 洞察</em>
      </button>
      </div>
    </section>

    <transition name="fade">
      <div v-if="introOpen" class="intro-mask" @click.self="introOpen = false">
        <div class="intro-modal" role="dialog" aria-modal="true" aria-labelledby="intro-title">
          <header class="im-head">
            <div class="im-title">
              <img src="/duck.png?v=insight" alt="" />
              <div>
                <strong id="intro-title">Duck Insight</strong>
                <small>通用数据分析平台 · 系统简介</small>
              </div>
            </div>
            <button class="im-close" type="button" @click="introOpen = false" aria-label="关闭">
              <el-icon><Close /></el-icon>
            </button>
          </header>

          <div class="im-body">
            <section class="im-block">
              <h5>系统介绍</h5>
              <p>
                Duck Insight 是面向分析与业务团队的通用数据分析平台。以 Duck 为看数入口，
                把数据源、数据集、清洗规则、模型训练、预测推演、自助看板、洞察报告和智能问答收在同一条链路里。
                过程可以回放，结论留有依据，由使用的人确认后再往下用。
              </p>
            </section>

            <section class="im-block">
              <h5>功能模块</h5>
              <div class="mod-groups">
                <div v-for="g in moduleGroups" :key="g.name" class="mod-group">
                  <div class="mod-group-name">{{ g.name }}</div>
                  <div class="mod-items">
                    <div v-for="m in g.items" :key="m.name" class="mod-item" :style="{ '--c': m.color }">
                      <span class="mod-icon"><el-icon><component :is="m.icon" /></el-icon></span>
                      <b>{{ m.name }}</b>
                      <i>{{ m.desc }}</i>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section class="im-block">
              <h5>实现技术</h5>
              <div class="tech">
                <span v-for="t in techs" :key="t">{{ t }}</span>
              </div>
            </section>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, register } from '@/api/user'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const isLogin = ref(true)
const loading = ref(false)
const introOpen = ref(false)
const motion = ref(!window.matchMedia('(prefers-reduced-motion: reduce)').matches)
const live = ref(true)
const videoRef = ref(null)
const activeStatus = ref(0)
const typed = ref('')
const loginForm = reactive({ username: 'admin', password: 'admin123' })
const regForm = reactive({ username: '', nickname: '', password: '' })

const streaks = [0, 1, 2, 3, 4, 5]
const statuses = ['待命', '接入数据', '打开工作台', '生成洞察']
const lines = ['> connect data', '> train model', '> insight ready']

const moduleGroups = [
  {
    name: '决策运营',
    items: [
      { name: '工作台', icon: 'DataBoard', desc: '全局指标与分析链路', color: '#e08a3c' },
      { name: 'BI 看板', icon: 'DataAnalysis', desc: '自助拖拽可视化', color: '#14b8a6' },
      { name: '洞察报告', icon: 'Notebook', desc: '把训练结果写成可读结论', color: '#f59e0b' },
      { name: 'DAG 编排', icon: 'Share', desc: '流程编排可回放', color: '#38bdf8' }
    ]
  },
  {
    name: '数据资产',
    items: [
      { name: '数据集配置', icon: 'FolderOpened', desc: '导入与智能编织', color: '#e08a3c' },
      { name: '数据源配置', icon: 'Connection', desc: '库表直连与活表', color: '#14b8a6' },
      { name: '清洗规则', icon: 'SetUp', desc: '可复用清洗流水线', color: '#f59e0b' }
    ]
  },
  {
    name: '模型实验',
    items: [
      { name: '模型训练', icon: 'Cpu', desc: '多算法训练与评估', color: '#38bdf8' },
      { name: '数据预测', icon: 'Promotion', desc: '表单与表格推演', color: '#e08a3c' }
    ]
  },
  {
    name: '智能体',
    items: [
      { name: '洞察报告', icon: 'Notebook', desc: '结构化解读报告', color: '#f59e0b' },
      { name: '知识库 RAG', icon: 'Collection', desc: '文档召回与引用', color: '#14b8a6' },
      { name: '智能问答', icon: 'ChatDotRound', desc: '多会话分析助手', color: '#38bdf8' }
    ]
  },
  {
    name: '系统',
    items: [
      { name: 'LLM / 提示词', icon: 'Setting', desc: '模型与模板配置', color: '#d6a16a' },
      { name: '用户管理', icon: 'User', desc: '账号与权限', color: '#d6a16a' }
    ]
  }
]

const techs = ['Vue 3', 'Element Plus', 'ECharts', 'Plotly Dash', 'Flask', 'Pandas', 'MySQL', 'XGBoost', 'RAG / FAISS', 'LLM 报告']

const doLogin = async () => {
  loading.value = true
  try {
    const res = await login(loginForm)
    userStore.setSession(res.data.token, res.data.user)
    ElMessage.success('登录成功')
    router.push('/')
  } finally {
    loading.value = false
  }
}

const doRegister = async () => {
  loading.value = true
  try {
    await register(regForm)
    ElMessage.success('注册成功，请登录')
    isLogin.value = true
  } finally {
    loading.value = false
  }
}

let statusTimer = 0
let typeTimer = 0
let onKeydown = () => {}

const playType = () => {
  let line = 0
  let count = 0
  const step = () => {
    const text = lines[line]
    count += 1
    typed.value = lines.slice(0, line).concat(text.slice(0, count)).join('\n')
    if (count >= text.length) {
      line += 1
      count = 0
      if (line >= lines.length) {
        line = 0
        typed.value = ''
      }
    }
    typeTimer = window.setTimeout(step, count === 0 ? 700 : 46)
  }
  step()
}

onMounted(() => {
  document.title = 'Duck Insight · 数据分析平台'
  onKeydown = (e) => {
    if (e.key === 'Escape' && introOpen.value) introOpen.value = false
  }
  window.addEventListener('keydown', onKeydown)
  const video = videoRef.value
  if (video) video.play().catch(() => {})
  if (!motion.value) {
    typed.value = lines.join('\n')
    return
  }
  statusTimer = window.setInterval(() => {
    activeStatus.value = (activeStatus.value + 1) % statuses.length
  }, 1400)
  playType()
})

onUnmounted(() => {
  window.clearInterval(statusTimer)
  window.clearTimeout(typeTimer)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.gate {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  grid-template-columns: minmax(420px, 86vh) minmax(400px, 1fr);
  background:
    radial-gradient(ellipse at 78% 8%, rgba(244, 168, 84, 0.14), transparent 36%),
    radial-gradient(ellipse at 92% 88%, rgba(56, 189, 248, 0.08), transparent 32%),
    #120f0c;
  color: #fff4e8;
  overflow: hidden;
}

.streaks {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.streaks i {
  position: absolute;
  top: -20%;
  left: calc(46% + var(--n) * 9%);
  width: 2px;
  height: 28%;
  background: linear-gradient(180deg, transparent, rgba(244, 168, 84, 0.72), transparent);
  transform: rotate(18deg);
  animation: fall 7.5s linear infinite;
  animation-delay: calc(var(--n) * -1.15s);
  opacity: 0.7;
}

.streaks i:nth-child(3),
.streaks i:nth-child(5) {
  background: linear-gradient(180deg, transparent, rgba(125, 211, 252, 0.55), transparent);
  height: 22%;
}

.stage {
  position: relative;
  z-index: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: #100e0c;
}

.stage-bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse at 50% 38%, rgba(244, 168, 84, 0.28), transparent 46%),
    radial-gradient(ellipse at 16% 18%, rgba(56, 189, 248, 0.18), transparent 30%),
    radial-gradient(ellipse at 84% 74%, rgba(45, 212, 191, 0.12), transparent 34%),
    linear-gradient(165deg, #1c140f 0%, #100e0c 52%, #0c1218 100%);
}

.stage-bg::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(125, 211, 252, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(244, 176, 110, 0.06) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: radial-gradient(ellipse at 50% 46%, transparent 28%, #000 76%);
}

.portrait {
  position: relative;
  z-index: 1;
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 34%;
  background: #100e0c;
}

.lattice {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(186, 230, 253, 0.09) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 214, 168, 0.06) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: radial-gradient(ellipse at 50% 42%, transparent 34%, rgba(0, 0, 0, 0.9) 78%);
}

.veil {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  background:
    linear-gradient(90deg, rgba(16, 13, 11, 0.18), transparent 18%, transparent 70%, rgba(18, 15, 12, 0.78)),
    linear-gradient(180deg, rgba(16, 13, 11, 0.34), transparent 18%, transparent 72%, rgba(16, 13, 11, 0.62));
}

.corner {
  position: absolute;
  z-index: 3;
  left: 7%;
  top: 7%;
  margin: 0;
  color: rgba(255, 228, 196, 0.78);
  letter-spacing: 0.2em;
  font-size: 12px;
  line-height: 1.7;
  text-shadow: 0 2px 16px rgba(0, 0, 0, 0.45);
}

.panel {
  position: relative;
  z-index: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 36px 32px 28px;
  scrollbar-width: thin;
  scrollbar-color: rgba(244, 176, 110, 0.35) transparent;
}

.sheet {
  position: relative;
  z-index: 1;
  width: min(420px, 100%);
  margin: auto;
  flex: none;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand img {
  width: 46px;
  height: 46px;
  border-radius: 14px;
  object-fit: cover;
  box-shadow: 0 8px 22px rgba(224, 122, 47, 0.28);
}

.brand strong {
  display: block;
  letter-spacing: 0.08em;
  font-size: 14px;
}

.brand em {
  display: block;
  margin-top: 3px;
  color: rgba(255, 228, 196, 0.52);
  font-style: normal;
  font-size: 10px;
  letter-spacing: 0.18em;
}

.status {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  list-style: none;
  margin: 26px 0 16px;
  padding: 0;
  color: rgba(244, 176, 110, 0.42);
  font-size: 12px;
  letter-spacing: 0.12em;
}

.status li.on {
  color: #ffd7a8;
  text-shadow: 0 0 12px rgba(244, 168, 84, 0.7);
}

h1 {
  margin: 0;
  font-size: clamp(56px, 5.4vw, 78px);
  line-height: 1.05;
  font-weight: 700;
  letter-spacing: -0.03em;
  overflow: visible;
}

h1 .duck {
  display: block;
  color: #fff8f1;
  line-height: 1;
  text-shadow: 0 0 28px rgba(244, 168, 84, 0.32);
}

h1 .insight {
  display: inline-block;
  margin-top: 2px;
  padding: 0.04em 0.08em 0.28em 0;
  line-height: 1.35;
  background: linear-gradient(90deg, #ffd7a8 0%, #f6b15a 46%, #7dd3fc 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.welcome {
  margin: 16px 0 0;
  font-size: 22px;
  letter-spacing: 0.02em;
}

.sub {
  margin: 6px 0 0;
  max-width: 40em;
  color: rgba(255, 236, 214, 0.68);
  font-size: 13px;
  line-height: 1.7;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 18px 0 18px;
}

.kpis div {
  padding: 10px 10px 9px;
  border-radius: 12px;
  background: rgba(255, 244, 232, 0.04);
  border: 1px solid rgba(244, 176, 110, 0.18);
}

.kpis b {
  display: block;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: #ffd7a8;
}

.kpis span {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  color: rgba(255, 236, 214, 0.62);
}

.btn {
  width: 100%;
  height: 44px;
  margin-top: 2px;
  border: 0 !important;
  border-radius: 8px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #2a1408 !important;
  background: linear-gradient(90deg, #e07a2f, #f6b15a) !important;
  box-shadow: 0 10px 26px rgba(224, 122, 47, 0.28);
}

.btn:hover,
.btn:focus {
  color: #2a1408 !important;
  filter: brightness(1.05);
}

.switch,
.intro {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.switch {
  margin-top: 14px;
  padding: 0;
  text-align: left;
  color: #ffc27a;
  font-size: 13px;
}

.switch:hover { color: #ffe0bc; }

.hint {
  margin: 8px 0 0;
  color: rgba(255, 228, 196, 0.46);
  font-size: 12px;
}

.term {
  margin: 16px 0 0;
  min-height: 4.2em;
  color: #f0c48a;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 13px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.term b { animation: blink 1s steps(1) infinite; }

.intro {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  padding: 0;
  color: rgba(255, 236, 214, 0.78);
  font-size: 13px;
}

.intro em {
  font-style: normal;
  color: rgba(255, 214, 168, 0.48);
  font-size: 12px;
}

.intro:hover { color: #fff6ea; }

.pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.7);
  animation: pulse 2.2s ease-out infinite;
}

:deep(.el-form-item) { margin-bottom: 12px; }

:deep(.el-input__wrapper) {
  background-color: rgba(32, 20, 12, 0.72) !important;
  box-shadow: 0 0 0 1px rgba(244, 176, 110, 0.38) inset !important;
  border-radius: 8px;
}

:deep(.el-input__wrapper:hover),
:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #ffc27a inset !important;
}

:deep(.el-input__inner) {
  color: #fff8f0 !important;
  -webkit-text-fill-color: #fff8f0;
}

:deep(.el-input__inner::placeholder) {
  color: rgba(255, 228, 196, 0.62) !important;
  -webkit-text-fill-color: rgba(255, 228, 196, 0.62);
}

:deep(.el-input__prefix),
:deep(.el-input__suffix),
:deep(.el-input__password) {
  color: #ffd7a8;
}

:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus) {
  -webkit-text-fill-color: #fff8f0;
  box-shadow: 0 0 0 1000px #24180f inset;
  transition: background-color 9999s ease-out;
}

.intro-mask {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(10, 8, 6, 0.72);
  backdrop-filter: blur(8px);
}

.intro-modal {
  width: min(780px, 100%);
  max-height: min(86vh, 760px);
  display: flex;
  flex-direction: column;
  border-radius: 18px;
  overflow: hidden;
  background: linear-gradient(165deg, rgba(32, 22, 16, 0.98), rgba(14, 12, 11, 0.98));
  border: 1px solid rgba(244, 176, 110, 0.28);
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.55);
  animation: pop 0.26s ease both;
}

.im-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(244, 176, 110, 0.16);
  background: linear-gradient(90deg, rgba(224, 122, 47, 0.22), rgba(56, 189, 248, 0.08));
}

.im-title { display: flex; align-items: center; gap: 11px; }
.im-title img { width: 34px; height: 34px; border-radius: 10px; object-fit: cover; }
.im-title strong { display: block; color: #fff6ea; font-size: 16px; letter-spacing: 0.04em; }
.im-title small {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: rgba(255, 214, 168, 0.72);
}

.im-close {
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  cursor: pointer;
  color: #ffe7c8;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(244, 176, 110, 0.24);
}

.im-close:hover { background: rgba(255, 255, 255, 0.12); }

.im-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
}

.im-block + .im-block { margin-top: 20px; }

.im-block h5 {
  margin-bottom: 9px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: #ffd7a8;
}

.im-block p {
  font-size: 13px;
  line-height: 1.8;
  color: rgba(255, 236, 214, 0.78);
}

.mod-groups { display: grid; gap: 14px; }

.mod-group-name {
  margin-bottom: 7px;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: rgba(255, 214, 168, 0.62);
}

.mod-items {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.mod-item {
  display: grid;
  gap: 3px;
  padding: 10px;
  border-radius: 11px;
  background: rgba(255, 244, 232, 0.04);
  border: 1px solid rgba(244, 176, 110, 0.14);
  border-top: 2px solid var(--c);
}

.mod-item:hover { background: rgba(244, 168, 84, 0.1); }

.mod-icon {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #1a120c;
  background: var(--c);
}

.mod-item b { font-size: 13px; color: #fff6ea; font-weight: 600; }
.mod-item i { font-style: normal; font-size: 11px; color: rgba(255, 228, 196, 0.58); }

.tech { display: flex; flex-wrap: wrap; gap: 6px; }

.tech span {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  color: #d9fff6;
  background: rgba(20, 120, 110, 0.22);
  border: 1px solid rgba(45, 212, 191, 0.28);
}

.fade-enter-active,
.fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from,
.fade-leave-to { opacity: 0; }

@keyframes fall { to { transform: translateY(140vh) rotate(18deg); } }
@keyframes blink { 50% { opacity: 0; } }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.7); }
  70% { box-shadow: 0 0 0 8px rgba(52, 211, 153, 0); }
  100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
}
@keyframes pop {
  from { opacity: 0; transform: translateY(12px) scale(0.98); }
  to { opacity: 1; transform: none; }
}

@media (max-width: 1180px) {
  .mod-items { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 980px) {
  .gate {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(280px, 46vh) auto;
    overflow-x: hidden;
    overflow-y: auto;
  }
  .stage { min-height: 46vh; height: 46vh; }
  .panel {
    height: auto;
    overflow: visible;
    align-items: stretch;
    padding: 28px 22px 40px;
  }
  .sheet { width: 100%; }
  h1 { font-size: 64px; }
  .mod-items { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (prefers-reduced-motion: reduce) {
  .streaks i,
  .term b,
  .pulse,
  .intro-modal {
    animation: none !important;
  }
}
</style>
