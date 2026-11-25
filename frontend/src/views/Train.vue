<template>
  <div>
    <div class="page-head">
      <div>
        <h2>模型训练</h2>
        <p>查看训练任务列表与进度。点击新建配置数据源、算法与参数后再开训。</p>
      </div>
      <div class="head-actions">
        <el-button :disabled="!picked.length" :loading="comparing" @click="openCompare">
          实验对比{{ picked.length ? `（${picked.length}）` : '' }}
        </el-button>
        <el-button type="primary" @click="$router.push('/train/new')">新建训练任务</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>训练任务</span>
          <div class="head-right">
            <span v-if="busyJob" class="live">正在训练：{{ busyJob.name }} {{ busyJob.progress || 0 }}%</span>
            <el-input
              v-model="keyword"
              clearable
              placeholder="任务名 / 算法 / 目标列"
              style="width: 240px"
              @keyup.enter="search"
            />
            <el-select v-model="statusFilter" clearable placeholder="状态" style="width: 120px" @change="search">
              <el-option label="全部" value="" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="训练中" value="running" />
              <el-option label="排队中" value="pending" />
            </el-select>
            <el-button size="small" type="primary" @click="search">查询</el-button>
            <el-button size="small" @click="loadJobs">刷新</el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!picked.length"
              :loading="removing"
              @click="removePicked"
            >删除所选{{ picked.length ? `（${picked.length}）` : '' }}</el-button>
          </div>
        </div>
      </template>
      <el-table
        ref="tableRef"
        :data="jobs"
        row-key="id"
        stripe
        highlight-current-row
        empty-text="还没有训练任务，点击右上角新建"
        @selection-change="onSelectionChange"
        @row-click="onRowClick"
      >
        <el-table-column type="selection" width="42" reserve-selection />
        <el-table-column prop="name" label="任务名称" min-width="200" show-overflow-tooltip />
        <el-table-column prop="model_type" label="算法" width="140" />
        <el-table-column label="目标列" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ headerLabel(row.target_col, '') }}</template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }">
            <el-progress
              :percentage="progressOf(row)"
              :status="progressStatus(row)"
              :stroke-width="10"
            />
          </template>
        </el-table-column>
        <el-table-column label="指标" width="110">
          <template #default="{ row }">{{ fmtMetric(row) }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="88">
          <template #default="{ row }">{{ row.duration_sec ? row.duration_sec + 's' : '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="168">
          <template #default="{ row }">{{ fmtTime(row.create_time || row.update_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="188" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openJob(row)">查看</el-button>
            <el-button
              v-if="row.status === 'success'"
              link
              type="success"
              @click.stop="goPredict(row)"
            >预测</el-button>
            <el-button link type="danger" @click.stop="removeOne(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <ListPager
        v-model:page="page"
        v-model:pageSize="pageSize"
        :total="total"
        @change="onPager"
      />
    </el-card>

    <el-dialog
      v-model="compareOpen"
      title="实验对比"
      width="920px"
      destroy-on-close
      append-to-body
      @opened="renderCompareCharts"
      @closed="disposeCompareCharts"
    >
      <p class="compare-tip">雷达图越高越好；柱状图 RMSE / MAE 越低越好。关闭弹窗即可收起对比图。</p>
      <el-table :data="compareRows" size="small" stripe class="compare-table">
        <el-table-column prop="name" label="任务" min-width="180" show-overflow-tooltip />
        <el-table-column prop="model_type" label="算法" width="140" />
        <el-table-column label="RMSE" width="110"><template #default="{ row }">{{ n(row.rmse) }}</template></el-table-column>
        <el-table-column label="MAE" width="110"><template #default="{ row }">{{ n(row.mae) }}</template></el-table-column>
        <el-table-column label="R²" width="100"><template #default="{ row }">{{ n(row.r2) }}</template></el-table-column>
        <el-table-column label="MAPE" width="100"><template #default="{ row }">{{ n(row.mape) }}</template></el-table-column>
        <el-table-column label="RMSPE" width="100"><template #default="{ row }">{{ n(row.rmspe) }}</template></el-table-column>
      </el-table>
      <div class="compare-charts">
        <div ref="radarRef" class="compare-chart"></div>
        <div ref="barRef" class="compare-chart"></div>
      </div>
      <template #footer>
        <el-button @click="compareOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listJobs, deleteJob, deleteJobs, compareJobs } from '@/api'
import ListPager from '@/components/ListPager.vue'
import { unwrapPage } from '@/utils/paging'
import { headerLabel } from '@/utils/fieldLabels'

const router = useRouter()
const tableRef = ref()
const jobs = ref([])
const picked = ref([])
const removing = ref(false)
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const comparing = ref(false)
const compareOpen = ref(false)
const compareRows = ref([])
const radarRef = ref()
const barRef = ref()
let timer = null
let radarChart = null
let barChart = null
const PALETTE = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#4d7c0f']
const colorOf = (i) => PALETTE[i % PALETTE.length]
const n = (v) => (v == null || v === '' ? '-' : Number(v).toFixed(4))

const busyJob = computed(() => jobs.value.find(j => j.status === 'running' || j.status === 'pending') || null)
const statusText = (s) => ({ pending: '排队中', running: '训练中', success: '成功', failed: '失败' }[s] || s || '-')
const statusType = (s) => ({ pending: 'info', running: 'warning', success: 'success', failed: 'danger' }[s] || 'info')
const progressOf = (row) => {
  if (!row) return 0
  if (row.status === 'success') return 100
  return Math.max(0, Math.min(100, Number(row.progress || 0)))
}
const progressStatus = (row) => {
  if (row?.status === 'success') return 'success'
  if (row?.status === 'failed') return 'exception'
  return undefined
}
const fmtMetric = (row) => {
  const m = row.metrics || {}
  if (m.rmse != null) return `RMSE ${Number(m.rmse).toFixed(2)}`
  if (m.r2 != null) return `R² ${Number(m.r2).toFixed(3)}`
  if (m.accuracy != null) return Number(m.accuracy).toFixed(3)
  return '-'
}

const fmtTime = (v) => {
  if (!v) return '-'
  const s = String(v).replace('T', ' ')
  return s.slice(0, 16)
}

const loadJobs = async () => {
  const packed = unwrapPage(await listJobs({
    page: page.value,
    page_size: pageSize.value,
    keyword: keyword.value.trim() || undefined,
    status: statusFilter.value || undefined
  }))
  jobs.value = packed.items
  total.value = packed.total
  if (!jobs.value.length && total.value > 0 && page.value > 1) {
    page.value -= 1
    return loadJobs()
  }
}

const search = () => {
  page.value = 1
  loadJobs()
}

const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  loadJobs()
}

const onSelectionChange = (rows) => {
  picked.value = rows || []
}

const openJob = (row) => {
  if (!row?.id) return
  router.push(`/train/${row.id}`)
}

const onRowClick = (row, column) => {
  if (column?.type === 'selection') return
  openJob(row)
}

const clearPicked = () => {
  picked.value = []
  tableRef.value?.clearSelection?.()
}

const goPredict = (row) => {
  if (!row?.id) return
  router.push({ path: '/predict', query: { job_id: String(row.id) } })
}

const removeOne = async (row) => {
  if (!row?.id) return
  const busy = row.status === 'running' || row.status === 'pending'
  try {
    await ElMessageBox.confirm(
      busy
        ? `「${row.name}」仍在训练中，删除后列表里会消失。确定删除？`
        : `删除训练记录「${row.name}」？模型文件会一并删除。`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  await deleteJob(row.id)
  ElMessage.success('已删除')
  clearPicked()
  await loadJobs()
}

const disposeCompareCharts = () => {
  radarChart?.dispose()
  barChart?.dispose()
  radarChart = null
  barChart = null
}

const renderCompareCharts = () => {
  disposeCompareCharts()
  const rows = compareRows.value
  if (!rows.length || !radarRef.value || !barRef.value) return

  const maxRmse = Math.max(...rows.map(m => Number(m.rmse || 0)), 1)
  const radarData = rows.map((m, i) => {
    const rmse = Number(m.rmse || 0)
    const r2 = Math.max(0, Math.min(1, Number(m.r2 || 0)))
    const mape = Number(m.mape || 0)
    const color = colorOf(i)
    return {
      name: m.name || `任务 ${m.id}`,
      value: [
        Math.max(0, 1 - rmse / maxRmse),
        r2,
        Math.max(0, Math.min(1, 1 - mape))
      ],
      itemStyle: { color },
      lineStyle: { color, width: 2.5 },
      areaStyle: { color, opacity: 0.16 },
      symbol: 'circle',
      symbolSize: 7
    }
  })

  radarChart = echarts.init(radarRef.value)
  radarChart.setOption({
    color: PALETTE,
    tooltip: { trigger: 'item' },
    legend: {
      type: 'scroll',
      bottom: 0,
      textStyle: { color: '#334155', fontSize: 12 }
    },
    radar: {
      indicator: [
        { name: 'RMSE↓ 归一', max: 1 },
        { name: 'R²', max: 1 },
        { name: '1-MAPE', max: 1 }
      ],
      axisName: { color: '#475569', fontSize: 12 },
      splitArea: { areaStyle: { color: ['#f8fafc', '#eef2f7'] } },
      splitLine: { lineStyle: { color: '#cbd5e1' } }
    },
    series: [{ type: 'radar', data: radarData }]
  })

  barChart = echarts.init(barRef.value)
  barChart.setOption({
    color: ['#2563eb', '#d97706'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: '#334155' } },
    grid: { left: 48, right: 16, top: 36, bottom: 48 },
    xAxis: {
      type: 'category',
      data: rows.map(m => m.name || `任务 ${m.id}`),
      axisLabel: { color: '#64748b', interval: 0, rotate: rows.length > 3 ? 18 : 0 }
    },
    yAxis: { type: 'value', name: '误差', nameTextStyle: { color: '#64748b' }, axisLabel: { color: '#64748b' } },
    series: [
      { name: 'RMSE', type: 'bar', barMaxWidth: 22, data: rows.map((m, i) => ({ value: Number(m.rmse || 0), itemStyle: { color: colorOf(i) } })) },
      { name: 'MAE', type: 'bar', barMaxWidth: 22, data: rows.map((m, i) => ({ value: Number(m.mae || 0), itemStyle: { color: colorOf(i), opacity: 0.55 } })) }
    ]
  })
}

const openCompare = async () => {
  const ok = picked.value.filter(r => r.status === 'success')
  if (ok.length < 2) return ElMessage.warning('请至少勾选 2 个训练成功的任务')
  if (ok.length < picked.value.length) {
    ElMessage.info(`已忽略 ${picked.value.length - ok.length} 个未成功任务`)
  }
  comparing.value = true
  try {
    const res = await compareJobs(ok.map(r => r.id))
    compareRows.value = res.data?.metrics || []
    if (compareRows.value.length < 2) return ElMessage.warning('可对比的成功任务不足 2 个')
    compareOpen.value = true
  } finally {
    comparing.value = false
  }
}

const removePicked = async () => {
  const rows = picked.value.filter(r => r?.id)
  if (!rows.length) return ElMessage.warning('请先勾选要删除的训练任务')
  const busy = rows.some(r => r.status === 'running' || r.status === 'pending')
  try {
    await ElMessageBox.confirm(
      busy
        ? `已选 ${rows.length} 条，其中含训练中/排队中的任务，删除后记录和模型文件都会消失。确定删除？`
        : `确定删除选中的 ${rows.length} 条训练记录？模型文件会一并删除。`,
      '批量删除',
      { type: 'warning' }
    )
  } catch {
    return
  }
  removing.value = true
  try {
    const res = await deleteJobs(rows.map(r => r.id))
    ElMessage.success(res.message || `已删除 ${res.data?.deleted || rows.length} 条`)
    clearPicked()
    await loadJobs()
  } finally {
    removing.value = false
  }
}

onMounted(async () => {
  await loadJobs()
  timer = setInterval(() => {
    if (!picked.value.length) loadJobs()
  }, 1500)
})
onUnmounted(() => {
  timer && clearInterval(timer)
  disposeCompareCharts()
})
</script>

<style scoped>
.head-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.head-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.live { color: #d97706; font-size: 12px; font-weight: 600; }
.compare-tip { color: var(--muted); font-size: 13px; margin: 0 0 12px; }
.compare-table { margin-bottom: 14px; }
.compare-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.compare-chart { height: 320px; }
@media (max-width: 860px) {
  .compare-charts { grid-template-columns: 1fr; }
}
</style>
