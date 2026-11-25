<template>
  <div class="dash">
    <!-- 气象 · 电力 主题顶部 -->
    <section class="hero">
      <div class="hero-bg" />
      <div class="hero-grid" />
      <div class="hero-glow g1" />
      <div class="hero-glow g2" />
      <div class="hero-inner">
        <div class="hero-copy">
          <div class="chip">
            <span class="pulse" />{{ scenarioName }} · 分析流水线
          </div>
          <h1>{{ isPower ? '把气象信号变成可确认的交易决策' : '把数据变成可行动的销量决策' }}</h1>
          <p v-if="isPower">
            多源气象治理 → 负荷 / 风光出力预测 → 电价研判 → 风险预警 → DAG 复盘。报价仅作建议，执行仍由交易员确认。
          </p>
          <p v-else>上传 → 智能编织 → 清洗绑定 → 训练评估 → 预测解读。当前场景可随时扩展为库存、客流等新分析域。</p>
          <div class="hero-btns">
            <template v-if="isPower">
              <el-button type="primary" @click="$router.push('/power')">进入电力决策舱</el-button>
              <el-button class="ghost" @click="$router.push('/dag')">打开 DAG 编排</el-button>
            </template>
            <template v-else>
              <el-button type="primary" @click="$router.push('/dataset')">导入数据</el-button>
              <el-button class="ghost" @click="$router.push('/train')">开始训练</el-button>
            </template>
          </div>
        </div>

        <div class="stat-grid">
          <div v-for="k in kpis" :key="k.label" class="stat" :style="{ '--c': k.color }">
            <span>{{ k.label }}</span>
            <b>{{ k.value }}</b>
            <i>{{ k.unit }}</i>
          </div>
        </div>
      </div>
    </section>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span>{{ isPower ? '气象 → 电力 决策链路' : '能力链路' }}</span>
          <span class="hint">点击进入对应模块</span>
        </div>
      </template>
      <div class="pipe">
        <div v-for="s in steps" :key="s.title" class="step" :style="{ '--c': s.color }" @click="$router.push(s.path)">
          <span class="step-icon"><el-icon><component :is="s.icon" /></el-icon></span>
          <b>{{ s.title }}</b>
          <span class="step-desc">{{ s.desc }}</span>
        </div>
      </div>
    </el-card>

    <el-row :gutter="16" class="block">
      <el-col :md="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>最近训练</span>
              <span class="hint">最近 6 条</span>
            </div>
          </template>
          <el-table :data="overview.recent_jobs || []" size="small">
            <el-table-column prop="name" label="任务" show-overflow-tooltip />
            <el-table-column prop="model_type" label="模型" width="120" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="progress" label="进度" width="90" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :md="10">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>近 7 日训练次数</span>
              <span class="trend-meta">
                <em>今日 {{ todayCount }}</em>
                <i>合计 {{ weekTotal }}</i>
              </span>
            </div>
          </template>
          <div ref="chartRef" style="height: 258px" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import * as echarts from 'echarts'
import { getOverview } from '@/api'
import { getScenarios as fetchScenes } from '@/api/user'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const overview = reactive({ stats: {}, recent_jobs: [], trend: [] })
const chartRef = ref()
const scenes = ref([])
let chart = null

const scenarioName = computed(() => scenes.value.find(s => s.code === userStore.scenario)?.name || '电力交易分析')
const isPower = computed(() => true)

const kpis = computed(() => ([
  { label: '数据集', value: overview.stats.datasets || 0, unit: '个', color: '#0ea5e9' },
  { label: '逻辑数据集', value: overview.stats.bundles || 0, unit: '个', color: '#14b8a6' },
  { label: '已训练模型', value: overview.stats.success_models || 0, unit: '个', color: '#f59e0b' },
  { label: '预测记录', value: overview.stats.predicts || 0, unit: '条', color: '#a78bfa' },
]))

const retailSteps = [
  { title: '数据编织', desc: '多表智能关联', path: '/dataset', icon: 'Connection', color: '#0ea5e9' },
  { title: '清洗绑定', desc: '规则可复用', path: '/clean', icon: 'SetUp', color: '#14b8a6' },
  { title: '小模型训练', desc: '14 种算法', path: '/train', icon: 'Cpu', color: '#f59e0b' },
  { title: '预测解读', desc: '表单/Excel + LLM', path: '/predict', icon: 'Promotion', color: '#a78bfa' },
]
const powerSteps = [
  { title: '气象治理', desc: 'ERA5 / ECMWF / GFS', path: '/power', icon: 'Cloudy', color: '#0ea5e9' },
  { title: '负荷风光电价', desc: '气象驱动预测', path: '/power', icon: 'Lightning', color: '#f59e0b' },
  { title: 'DAG 编排', desc: '日前闭环可回放', path: '/dag', icon: 'Share', color: '#14b8a6' },
  { title: '决策报告', desc: '本地 qwen3:4b', path: '/power', icon: 'Notebook', color: '#a78bfa' },
]
const steps = computed(() => (isPower.value ? powerSteps : retailSteps))

const trend = computed(() => overview.trend || [])
const todayCount = computed(() => (trend.value.length ? trend.value[trend.value.length - 1].count : 0))
const weekTotal = computed(() => trend.value.reduce((sum, t) => sum + (t.count || 0), 0))

const statusText = (s) => ({ success: '成功', running: '运行中', failed: '失败', queued: '排队中' }[s] || s)
const statusType = (s) => ({ success: 'success', running: 'warning', failed: 'danger', queued: 'info' }[s] || 'info')

function drawTrend() {
  if (!chartRef.value) return
  chart = chart || echarts.init(chartRef.value)
  const rows = trend.value
  const last = rows.length - 1
  const values = rows.map((t, i) => ({
    value: t.count,
    itemStyle: {
      borderRadius: [5, 5, 0, 0],
      color: i === last
        ? new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#fbbf24' },
          { offset: 1, color: '#f59e0b' }
        ])
        : new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#60a5fa' },
          { offset: 1, color: '#1d6fd8' }
        ])
    }
  }))
  chart.setOption({
    backgroundColor: 'transparent',
    textStyle: { color: '#64748b' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => `${p[0].axisValue}<br/>训练 ${p[0].value} 次`
    },
    grid: { left: 42, right: 16, top: 26, bottom: 36 },
    xAxis: {
      type: 'category',
      data: rows.map(t => t.date),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#d5dee8' } },
      axisLabel: {
        color: (v, i) => (i === last ? '#d97706' : '#64748b'),
        lineHeight: 14,
        formatter: (v, i) => (i === last ? `今天\n${v.slice(5)}` : v.slice(5))
      }
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#e8eef5' } },
      axisLabel: { color: '#64748b' }
    },
    series: [{
      type: 'bar',
      data: values,
      barMaxWidth: 24,
      showBackground: true,
      backgroundStyle: { color: 'rgba(29,111,216,.06)', borderRadius: [5, 5, 0, 0] },
      label: {
        show: true,
        position: 'top',
        color: '#64748b',
        fontSize: 11,
        formatter: (p) => (p.value ? p.value : '')
      }
    }]
  }, true)
}

function onResize() {
  chart?.resize()
}

onMounted(async () => {
  try {
    const [ov, sc] = await Promise.all([getOverview(), fetchScenes()])
    Object.assign(overview, ov.data || {})
    scenes.value = sc.data || []
  } finally {
    drawTrend()
  }
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.dash { display: block; }

/* —— Hero：气象 + 电力 —— */
.hero {
  position: relative;
  overflow: hidden;
  border-radius: 16px;
  margin-bottom: 16px;
  border: 1px solid #0d3b52;
  box-shadow: 0 16px 44px rgba(6, 24, 40, 0.28);
  background: #061422;
}

.hero-bg {
  position: absolute;
  inset: -10%;
  background: url('/hero-power.jpg') center 46% / cover no-repeat;
  filter: saturate(1.15) contrast(1.1);
  opacity: 0.5;
}

.hero-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(125, 211, 252, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(125, 211, 252, 0.08) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse at 30% 50%, rgba(0, 0, 0, 0.75), transparent 76%);
}

.hero::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(760px 320px at 88% 0%, rgba(14, 165, 233, 0.26), transparent 62%),
    linear-gradient(102deg, rgba(3, 11, 22, 0.95) 0%, rgba(5, 20, 36, 0.86) 48%, rgba(4, 26, 40, 0.72) 100%);
}

.hero-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(48px);
}
.hero-glow.g1 {
  width: 260px; height: 260px; right: 18%; top: -90px;
  background: rgba(245, 158, 11, 0.24);
}
.hero-glow.g2 {
  width: 300px; height: 300px; right: 4%; bottom: -140px;
  background: rgba(20, 184, 166, 0.28);
}

.hero-inner {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 1fr);
  gap: 26px;
  align-items: center;
  padding: 26px 28px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #a5f3fc;
  background: rgba(13, 148, 136, 0.2);
  border: 1px solid rgba(45, 212, 191, 0.4);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  padding: 5px 12px;
  border-radius: 999px;
}

.pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #34d399;
  animation: pulse 2.2s ease-out infinite;
}

.hero h1 {
  margin: 12px 0 8px;
  font-size: 26px;
  letter-spacing: -0.02em;
  color: #f8fbff;
}

.hero p {
  color: rgba(214, 231, 248, 0.8);
  max-width: 620px;
  line-height: 1.65;
  font-size: 13px;
}

.hero-btns { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 18px; }

.hero-btns :deep(.ghost) {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(147, 197, 253, 0.4);
  color: #dbeafe;
}
.hero-btns :deep(.ghost:hover) {
  background: rgba(255, 255, 255, 0.12);
  border-color: #93c5fd;
  color: #fff;
}

.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.stat {
  position: relative;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(9, 26, 44, 0.62);
  border: 1px solid rgba(125, 211, 252, 0.18);
  backdrop-filter: blur(10px);
  border-left: 3px solid var(--c);
}

.stat span { display: block; font-size: 12px; color: rgba(191, 219, 254, 0.78); }
.stat b { display: block; font-size: 24px; font-weight: 700; letter-spacing: -0.03em; color: #f0f8ff; margin-top: 4px; }
.stat i { font-style: normal; font-size: 11px; color: rgba(148, 197, 240, 0.72); }

/* —— 卡片区 —— */
.block { margin-bottom: 16px; }

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.hint { color: var(--muted); font-size: 12px; font-weight: 400; }

.trend-meta { display: inline-flex; gap: 10px; align-items: center; font-size: 12px; font-weight: 400; }
.trend-meta em {
  font-style: normal;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}
.trend-meta i { font-style: normal; color: var(--muted); }

.pipe { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }

.step {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background-color: var(--panel-soft);
  background-image: linear-gradient(180deg, rgba(125, 211, 252, 0.1), transparent 62%);
  border-top: 3px solid var(--c);
  transition: border-color 0.15s, transform 0.15s;
}

.step:hover {
  border-color: var(--c);
  transform: translateY(-2px);
}

.step-icon {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--c);
  box-shadow: 0 6px 16px rgba(26, 36, 51, 0.18);
}

.step b { font-size: 14px; color: var(--text); }
.step-desc { color: var(--muted); font-size: 12px; }

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.8); }
  70% { box-shadow: 0 0 0 8px rgba(52, 211, 153, 0); }
  100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
}

@media (max-width: 1100px) {
  .hero-inner { grid-template-columns: 1fr; }
  .pipe { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 640px) {
  .pipe { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: 1fr; }
}
</style>
