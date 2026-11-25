<template>
  <div class="cockpit">
    <header class="hero">
      <div>
        <div class="chip">电力交易员 · 决策舱</div>
        <h2>气象 — 负荷 — 风光 — 电价 四联监测</h2>
        <p>
          实况 ERA5 + ECMWF/GFS 融合预报 + 17–45 日气候态展望。电能量与价格由气象驱动物理-统计模型推演，报价建议需人工确认。
        </p>
      </div>
      <div class="hero-actions">
        <el-button :loading="syncing" type="primary" @click="syncWeather">同步气象并刷新</el-button>
        <el-button @click="$router.push('/dag')">打开 DAG 编排</el-button>
      </div>
    </header>

    <div v-if="empty" class="empty">
      <p>尚未入库气象序列。点击「同步气象并刷新」从 Open-Meteo 拉取华东三站点数据。</p>
    </div>

    <template v-else>
      <div class="duty-rail">
        <button
          v-for="d in duties"
          :key="d.id"
          class="duty"
          :class="{ on: duty === d.id }"
          @click="duty = d.id"
        >
          <span class="n">{{ d.id }}</span>
          <b>{{ d.title }}</b>
          <em>{{ d.hint }}</em>
        </button>
      </div>

      <section class="kpis">
        <article v-for="k in kpiCards" :key="k.label" class="kpi" :style="{ '--c': k.color }">
          <span>{{ k.label }}</span>
          <strong>{{ k.value }}</strong>
          <small>{{ k.sub }}</small>
        </article>
      </section>

      <el-row :gutter="14">
        <el-col :lg="16">
          <el-card shadow="never" class="panel">
            <template #header>
              <div class="card-head">
                <span>{{ chartTitle }}</span>
                <el-radio-group v-model="horizonView" size="small">
                  <el-radio-button label="h72">未来 72h</el-radio-button>
                  <el-radio-button label="d45">17–45 日展望</el-radio-button>
                </el-radio-group>
              </div>
            </template>
            <div ref="powerChart" class="chart" />
          </el-card>
          <el-card shadow="never" class="panel" style="margin-top: 14px">
            <template #header>气象驱动层 · 气温 / 风速 / 辐照</template>
            <div ref="wxChart" class="chart sm" />
          </el-card>
        </el-col>
        <el-col :lg="8">
          <el-card shadow="never" class="panel">
            <template #header>极端天气冲击推演</template>
            <div class="shocks">
              <button
                v-for="s in shockKinds"
                :key="s.id"
                :class="{ on: shockKind === s.id }"
                @click="applyShock(s.id)"
              >
                {{ s.label }}
                <b v-if="data.shocks?.[s.id]">Δ负荷 {{ data.shocks[s.id].delta_load_mw }} MW</b>
              </button>
            </div>
            <p class="shock-note">
              {{ shockNote }}
            </p>
          </el-card>
          <el-card shadow="never" class="panel" style="margin-top: 14px">
            <template #header>交易支持（人工确认）</template>
            <p class="summary">{{ data.strategy?.summary }}</p>
            <div v-for="(a, i) in data.strategy?.actions || []" :key="i" class="action">
              <b>{{ a.title }}</b>
              <span>{{ a.detail }}</span>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="14" style="margin-top: 14px">
        <el-col :span="24">
          <el-card shadow="never" class="panel">
            <template #header>风险预警流</template>
            <div v-if="!(data.alerts || []).length" class="muted">未来 72h 暂无触发阈值的告警。</div>
            <div v-for="a in data.alerts || []" :key="a.id" class="alert" :class="a.level">
              <div>
                <el-tag size="small" :type="alertType(a.level)">{{ a.title }}</el-tag>
                <time>{{ a.ts }}</time>
              </div>
              <p>{{ a.message }}</p>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { powerCockpit, powerIngest } from '@/api'

const data = ref({})
const empty = ref(false)
const syncing = ref(false)
const duty = ref('1')
const horizonView = ref('h72')
const shockKind = ref('heatwave')
const powerChart = ref()
const wxChart = ref()
let chartA
let chartB

const duties = [
  { id: '1', title: '气象治理', hint: 'ERA5 / ECMWF / GFS / 气候态' },
  { id: '2', title: '负荷与风光', hint: '气象驱动 + 极端冲击' },
  { id: '3', title: '电价与交易', hint: '报价带 / 套利 / 对冲' },
  { id: '4', title: '风险看板', hint: '突变预警 + 阈值告警' },
  { id: '5', title: '模型迭代', hint: 'DAG 自动化与复盘' }
]

const kpiCards = computed(() => {
  const k = data.value.kpis || {}
  return [
    { label: '气温', value: fmt(k.temp, 1, '℃'), sub: '上海负荷中心', color: '#0ea5e9' },
    { label: '系统负荷', value: fmt(k.load, 0, ' MW'), sub: '气象驱动', color: '#f59e0b' },
    { label: '风光出力', value: fmt((k.wind || 0) + (k.solar || 0), 0, ' MW'), sub: `渗透 ${k.renew_share || 0}%`, color: '#22c55e' },
    { label: '日前电价', value: fmt(k.price_da, 0, ' 元/MWh'), sub: `实时 ${fmt(k.price_rt, 0)}`, color: '#ef4444' },
    { label: '阻塞指数', value: fmt(k.congestion, 2), sub: '残余负荷压力', color: '#8b5cf6' }
  ]
})

const chartTitle = computed(() => (
  horizonView.value === 'h72' ? '未来 72 小时：负荷 / 风光 / 日前电价' : '中长期日均展望（气候态平移）'
))

const shockKinds = [
  { id: 'heatwave', label: '热浪' },
  { id: 'coldwave', label: '寒潮' },
  { id: 'typhoon', label: '台风/大风' },
  { id: 'storm', label: '强对流' }
]

const shockNote = computed(() => {
  const s = data.value.shocks?.[shockKind.value]
  if (!s) return '选择情景查看相对基准的负荷与电价偏移。'
  return `${shockKinds.find(x => x.id === shockKind.value)?.label}：平均负荷 ${s.delta_load_mw} MW，电价 ${s.delta_price} 元/MWh。`
})

function fmt(v, d = 0, suffix = '') {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return Number(v).toFixed(d).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + suffix
}

function alertType(level) {
  return { danger: 'danger', warn: 'warning', info: 'info' }[level] || 'info'
}

function axisTheme() {
  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#64748b' },
    grid: { left: 52, right: 48, top: 28, bottom: 36 },
    tooltip: { trigger: 'axis' }
  }
}

function renderCharts() {
  const series = data.value.series || []
  const daily = data.value.daily || []
  if (!powerChart.value) return
  chartA = chartA || echarts.init(powerChart.value)
  chartB = chartB || echarts.init(wxChart.value)

  if (horizonView.value === 'd45') {
    chartA.setOption({
      ...axisTheme(),
      legend: { top: 0, textStyle: { color: '#64748b' } },
      xAxis: { type: 'category', data: daily.map(d => d.date), axisLabel: { color: '#64748b' } },
      yAxis: [
        { type: 'value', name: 'MW', splitLine: { lineStyle: { color: '#e8eef5' } } },
        { type: 'value', name: '元', splitLine: { show: false } }
      ],
      series: [
        { name: '负荷', type: 'line', data: daily.map(d => d.load), smooth: true, color: '#f59e0b' },
        { name: '风电', type: 'line', data: daily.map(d => d.wind), smooth: true, color: '#0ea5e9' },
        { name: '光伏', type: 'line', data: daily.map(d => d.solar), smooth: true, color: '#22c55e' },
        { name: '日前电价', type: 'line', yAxisIndex: 1, data: daily.map(d => d.price), smooth: true, color: '#ef4444' }
      ]
    }, true)
  } else {
    const shockPts = data.value.shocks?.[shockKind.value]?.points || []
    const shockMap = Object.fromEntries(shockPts.map(p => [String(p.ts).slice(0, 16).replace('T', ' '), p]))
    chartA.setOption({
      ...axisTheme(),
      legend: { top: 0, textStyle: { color: '#64748b' } },
      xAxis: { type: 'category', data: series.map(r => r.ts?.slice(5)), axisLabel: { color: '#64748b' } },
      yAxis: [
        { type: 'value', name: 'MW', splitLine: { lineStyle: { color: '#e8eef5' } } },
        { type: 'value', name: '元', splitLine: { show: false } }
      ],
      series: [
        { name: '负荷', type: 'line', data: series.map(r => r.load_mw), smooth: true, color: '#f59e0b', areaStyle: { color: 'rgba(245,158,11,.12)' } },
        { name: '风电', type: 'bar', stack: 're', data: series.map(r => r.wind_mw), color: '#0ea5e9' },
        { name: '光伏', type: 'bar', stack: 're', data: series.map(r => r.solar_mw), color: '#22c55e' },
        { name: '日前电价', type: 'line', yAxisIndex: 1, data: series.map(r => r.price_da), smooth: true, color: '#ef4444' },
        {
          name: '冲击负荷',
          type: 'line',
          data: series.map(r => shockMap[r.ts]?.load_mw ?? null),
          smooth: true,
          color: '#c026d3',
          lineStyle: { type: 'dashed' }
        }
      ]
    }, true)
  }

  chartB.setOption({
    ...axisTheme(),
    grid: { left: 48, right: 40, top: 28, bottom: 32 },
    legend: { top: 0, textStyle: { color: '#64748b' } },
    xAxis: { type: 'category', data: series.map(r => r.ts?.slice(5)), axisLabel: { color: '#64748b' } },
    yAxis: [
      { type: 'value', name: '℃ / m/s', splitLine: { lineStyle: { color: '#e8eef5' } } },
      { type: 'value', name: 'W/m²', splitLine: { show: false } }
    ],
    series: [
      { name: '气温', type: 'line', data: series.map(r => r.temp_c), color: '#f97316', smooth: true },
      { name: '100m 风', type: 'line', data: series.map(r => r.wind_100m), color: '#0284c7', smooth: true },
      { name: '辐照', type: 'line', yAxisIndex: 1, data: series.map(r => r.radiation), color: '#ca8a04', smooth: true }
    ]
  }, true)
}

async function load() {
  const res = await powerCockpit()
  data.value = res.data || {}
  empty.value = Boolean(data.value.empty) || !(data.value.series || []).length
  await nextTick()
  if (!empty.value) renderCharts()
}

async function syncWeather() {
  syncing.value = true
  try {
    const res = await powerIngest()
    ElMessage.success(`已同步 ${res.data?.rows || 0} 小时`)
    await load()
  } finally {
    syncing.value = false
  }
}

function applyShock(id) {
  shockKind.value = id
  nextTick(renderCharts)
}

watch([horizonView, duty], () => nextTick(renderCharts))

onMounted(async () => {
  await load()
  window.addEventListener('resize', onResize)
})
function onResize() {
  chartA?.resize()
  chartB?.resize()
}
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chartA?.dispose()
  chartB?.dispose()
})
</script>

<style scoped>
.hero {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-end;
  padding: 22px 24px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background:
    radial-gradient(600px 180px at 90% 0%, rgba(245, 158, 11, .14), transparent 50%),
    linear-gradient(135deg, rgba(14, 165, 233, .12), #fff 42%, rgba(34, 197, 94, .08));
  box-shadow: var(--shadow);
  margin-bottom: 16px;
}
.chip {
  display: inline-block;
  color: #0f766e;
  background: #ccfbf1;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
}
.hero h2 { margin: 8px 0 6px; font-size: 24px; letter-spacing: -0.03em; }
.hero p { color: var(--muted); max-width: 720px; line-height: 1.6; font-size: 13px; }
.hero-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.empty {
  padding: 48px;
  text-align: center;
  background: var(--panel);
  border: 1px dashed var(--line);
  border-radius: 16px;
  color: var(--muted);
}
.duty-rail {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.duty {
  text-align: left;
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 12px;
  padding: 12px 14px;
  cursor: pointer;
  display: grid;
  gap: 4px;
}
.duty.on { border-color: #0f766e; background: #f0fdfa; }
.duty .n {
  width: 22px; height: 22px; border-radius: 6px;
  background: #0f766e; color: #fff; display: grid; place-items: center;
  font-size: 12px; font-weight: 700;
}
.duty em { font-style: normal; color: var(--muted); font-size: 12px; }
.kpis {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.kpi {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 16px;
  box-shadow: var(--shadow);
  border-top: 3px solid var(--c);
}
.kpi span { color: var(--muted); font-size: 12px; }
.kpi strong { display: block; font-size: 22px; letter-spacing: -0.03em; margin: 6px 0 4px; }
.kpi small { color: var(--muted); }
.chart { height: 320px; }
.chart.sm { height: 220px; }
.shocks { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.shocks button {
  border: 1px solid var(--line);
  background: var(--panel-soft);
  border-radius: 10px;
  padding: 10px;
  cursor: pointer;
  display: grid;
  gap: 4px;
  text-align: left;
}
.shocks button.on { border-color: #c026d3; background: #fdf4ff; }
.shocks b { font-size: 12px; color: #86198f; font-weight: 600; }
.shock-note, .summary, .muted { color: var(--muted); font-size: 13px; line-height: 1.6; }
.action {
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--panel-soft);
  border-radius: 10px;
  display: grid;
  gap: 4px;
}
.action span { color: var(--muted); font-size: 13px; line-height: 1.55; }
.alert { padding: 10px 0; border-bottom: 1px solid var(--line); }
.alert:last-child { border-bottom: none; }
.alert div { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.alert time { color: var(--muted); font-size: 12px; }
.alert p { margin-top: 6px; font-size: 13px; color: var(--text); }
@media (max-width: 1100px) {
  .duty-rail, .kpis { grid-template-columns: 1fr 1fr; }
}
</style>
