<template>
  <div class="dash">
    <section class="hero">
      <div class="hero-grid" />
      <div class="hero-glow g1" />
      <div class="hero-glow g2" />
      <div class="hero-inner">
        <div class="hero-copy">
          <div class="chip">
            <img src="/duck.png?v=insight" alt="" />
            Duck Insight · 分析工作台
          </div>
          <h1>把一张表，洗成能回头看的洞察</h1>
          <p>接入数据，配好清洗规则，训练模型，再排成 DAG。指标留在看板上，结论写成可以复核的报告。</p>
          <div class="hero-btns">
            <el-button type="primary" @click="$router.push('/dataset')">导入数据</el-button>
            <el-button class="ghost" @click="$router.push('/bi')">打开 BI 看板</el-button>
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
          <span>数据分析链路</span>
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

const overview = reactive({ stats: {}, recent_jobs: [], trend: [] })
const chartRef = ref()
let chart = null

const kpis = computed(() => ([
  { label: '数据集', value: overview.stats.datasets || 0, unit: '个', color: '#0ea5e9' },
  { label: '逻辑数据集', value: overview.stats.bundles || 0, unit: '个', color: '#14b8a6' },
  { label: '已训练模型', value: overview.stats.success_models || 0, unit: '个', color: '#f59e0b' },
  { label: '预测记录', value: overview.stats.predicts || 0, unit: '条', color: '#a78bfa' },
]))

const steps = [
  { title: '数据接入', desc: '上传表格并看字段画像', path: '/dataset', icon: 'FolderOpened', color: '#e08a3c' },
  { title: '清洗规则', desc: '去重、日期和类别编码', path: '/clean', icon: 'SetUp', color: '#14b8a6' },
  { title: '模型训练', desc: '回归、分类和指标对比', path: '/train', icon: 'Cpu', color: '#38bdf8' },
  { title: 'DAG 编排', desc: '把清洗和训练串成流程', path: '/dag', icon: 'Share', color: '#a78bfa' },
]

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
    const ov = await getOverview()
    Object.assign(overview, ov.data || {})
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

.hero {
  position: relative;
  overflow: hidden;
  border-radius: 16px;
  margin-bottom: 16px;
  border: 1px solid #243044;
  box-shadow: 0 16px 40px rgba(18, 16, 14, 0.22);
  background:
    radial-gradient(520px 220px at 12% 0%, rgba(224, 138, 60, 0.28), transparent 70%),
    radial-gradient(480px 240px at 92% 110%, rgba(56, 189, 248, 0.22), transparent 68%),
    #1a1d24;
}

.hero-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(ellipse at 25% 40%, rgba(0, 0, 0, 0.7), transparent 78%);
}

.hero-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(42px);
}
.hero-glow.g1 {
  width: 220px; height: 220px; right: 22%; top: -80px;
  background: rgba(224, 138, 60, 0.28);
}
.hero-glow.g2 {
  width: 260px; height: 260px; right: 2%; bottom: -120px;
  background: rgba(56, 189, 248, 0.22);
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
  color: #ffe7c2;
  background: rgba(224, 138, 60, 0.16);
  border: 1px solid rgba(255, 196, 120, 0.35);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 4px 12px 4px 4px;
  border-radius: 999px;
}

.chip img {
  width: 22px;
  height: 22px;
  border-radius: 6px;
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
  background: rgba(18, 20, 26, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(10px);
  border-left: 3px solid var(--c);
}

.stat span { display: block; font-size: 12px; color: rgba(255, 236, 214, 0.78); }
.stat b { display: block; font-size: 24px; font-weight: 700; letter-spacing: -0.03em; color: #fffaf3; margin-top: 4px; }
.stat i { font-style: normal; font-size: 11px; color: rgba(186, 198, 214, 0.78); }

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

@media (max-width: 1100px) {
  .hero-inner { grid-template-columns: 1fr; }
  .pipe { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 640px) {
  .pipe { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: 1fr; }
}
</style>
