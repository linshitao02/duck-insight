<template>
  <div class="rt-page">
    <div class="rt-head">
      <div>
        <h2>实时同步任务</h2>
        <p class="sub">对齐 Taier 实时采集与 DataWorks 多表同步：勾表自动建主题并生成 Flink CDC SQL，支持转为脚本模式与断点续跑。</p>
      </div>
      <div class="rt-actions">
        <el-button @click="router.push('/realtime/ops')">运维中心</el-button>
        <el-button @click="loadAll" :loading="loading">刷新</el-button>
        <el-button type="primary" @click="router.push('/realtime/tasks/new')">新建同步任务</el-button>
      </div>
    </div>

    <el-card shadow="never" class="cluster-bar">
      <div class="cluster-grid">
        <div class="c-item">
          <span class="c-label">Flink 集群</span>
          <el-tag :type="overview.connected ? 'success' : 'info'" size="small">
            {{ overview.connected ? `已连接 v${overview.flink_version || ''}` : '未连接集群（仅配置预览）' }}
          </el-tag>
        </div>
        <div class="c-item">
          <span class="c-label">TaskManager / 槽位</span>
          <strong>{{ overview.connected ? `${overview.taskmanagers} / 可用 ${overview.slots_available}（共 ${overview.slots_total}）` : '-' }}</strong>
        </div>
        <div class="c-item">
          <span class="c-label">运行中作业</span>
          <strong>{{ overview.connected ? overview.jobs_running : '-' }}</strong>
        </div>
        <div class="c-item">
          <span class="c-label">Kafka 地址</span>
          <code>{{ overview.kafka_bootstrap || 'kafka:9092' }}</code>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="tasks" v-loading="loading" empty-text="还没有实时同步任务，点击右上角「新建同步任务」开始">
        <el-table-column prop="name" label="任务名称" min-width="180">
          <template #default="{ row }">
            <el-link type="primary" @click="router.push(`/realtime/tasks/${row.id}`)">{{ row.name }}</el-link>
            <div class="muted" v-if="row.description">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="开发模式" width="110">
          <template #default="{ row }">
            <el-tag :type="row.mode === 'script' ? 'warning' : 'primary'" size="small">
              {{ row.mode === 'script' ? '脚本模式' : '向导模式' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源库 / 同步表数" min-width="170">
          <template #default="{ row }">
            <span>{{ row.database_name || '-' }}</span>
            <el-tag size="small" type="info" style="margin-left: 6px">{{ (row.tables || []).length }} 张表</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="运行状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.job_status)" size="small">{{ statusLabel(row.job_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Flink Job ID" min-width="170">
          <template #default="{ row }">
            <code v-if="row.flink_job_id">{{ row.flink_job_id.slice(0, 12) }}...</code>
            <span v-else class="muted">未提交</span>
          </template>
        </el-table-column>
        <el-table-column prop="update_time" label="更新时间" width="170" />
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/realtime/tasks/${row.id}`)">配置 / SQL</el-button>
            <el-button link type="primary" @click="router.push({ path: '/realtime/ops', query: { taskId: row.id } })">运维</el-button>
            <el-button
              v-if="row.job_status !== 'running'"
              link
              type="success"
              @click="onSubmit(row)"
            >
              {{ row.last_checkpoint ? '断点续跑' : '提交运行' }}
            </el-button>
            <el-button v-else link type="warning" @click="onStop(row)">停止</el-button>
            <el-button link @click="onRefresh(row)">查状态</el-button>
            <el-popconfirm title="确定删除该同步任务？" @confirm="onDelete(row)">
              <template #reference>
                <el-button link type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  deleteRealtimeTask,
  getRealtimeOverview,
  listRealtimeTasks,
  refreshRealtimeTask,
  stopRealtimeTask,
  submitRealtimeTask
} from '@/api'

const router = useRouter()
const loading = ref(false)
const overview = ref({})
const tasks = ref([])

const statusLabel = (s) => ({
  draft: '草稿',
  running: '运行中',
  stopped: '已停止',
  failed: '失败'
}[s] || s || '草稿')

const statusType = (s) => ({
  draft: 'info',
  running: 'success',
  stopped: 'warning',
  failed: 'danger'
}[s] || 'info')

async function loadAll() {
  loading.value = true
  try {
    const [ov, list] = await Promise.all([getRealtimeOverview(), listRealtimeTasks()])
    overview.value = ov.data || {}
    tasks.value = list.data || []
  } catch (e) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onSubmit(row) {
  try {
    await submitRealtimeTask(row.id, true)
    ElMessage.success(row.last_checkpoint ? '已从最近检查点续跑' : '作业已提交')
    loadAll()
  } catch (e) {
    ElMessage.error(e?.message || '提交失败')
  }
}

async function onStop(row) {
  try {
    await stopRealtimeTask(row.id)
    ElMessage.success('作业已停止')
    loadAll()
  } catch (e) {
    ElMessage.error(e?.message || '停止失败')
  }
}

async function onRefresh(row) {
  try {
    await refreshRealtimeTask(row.id)
    ElMessage.success('状态已刷新')
    loadAll()
  } catch (e) {
    ElMessage.error(e?.message || '刷新失败')
  }
}

async function onDelete(row) {
  try {
    await deleteRealtimeTask(row.id)
    ElMessage.success('已删除')
    loadAll()
  } catch (e) {
    ElMessage.error(e?.message || '删除失败')
  }
}

onMounted(loadAll)
</script>

<style scoped>
.rt-page { display: flex; flex-direction: column; gap: 14px; }
.rt-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.rt-head h2 { margin: 0 0 4px; font-size: 20px; color: #0f172a; }
.sub { margin: 0; font-size: 13px; color: #64748b; }
.rt-actions { display: flex; gap: 8px; }
.cluster-bar { border-radius: 10px; }
.cluster-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.c-item { display: flex; flex-direction: column; gap: 4px; }
.c-label { font-size: 12px; color: #64748b; }
.table-card { border-radius: 10px; }
.muted { font-size: 12px; color: #94a3b8; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #334155; }
</style>
