<template>
  <div class="ops-page">
    <!-- 顶部标题与全局运维操作 -->
    <div class="ops-head">
      <div>
        <h2>实时运维中心</h2>
        <p class="sub">
          对齐 Taier 实时运维中心与 DataWorks 运维中心：统一监控 Flink CDC 作业运行态、算子流量、Checkpoint 历史断点恢复与异常诊断。
        </p>
      </div>
      <div class="ops-actions">
        <div class="auto-refresh">
          <span class="ar-label">自动刷新(10s)</span>
          <el-switch v-model="autoRefresh" size="small" />
        </div>
        <el-button @click="loadOps(true)" :loading="syncing">同步集群状态</el-button>
        <el-button type="primary" @click="router.push('/realtime/tasks/new')">新建同步任务</el-button>
      </div>
    </div>

    <!-- 状态统计卡片（点击联动过滤，对齐 Taier / DataWorks 运维大盘） -->
    <div class="stat-grid">
      <div
        v-for="card in statCards"
        :key="card.key"
        class="stat-card"
        :class="[card.tone, { active: statusFilter === card.key }]"
        @click="statusFilter = card.key"
      >
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-val">{{ card.value }}</div>
      </div>
    </div>

    <!-- 集群资源状态条 -->
    <el-card shadow="never" class="cluster-card">
      <div class="cluster-row">
        <div class="c-cell">
          <span class="c-k">Flink 集群</span>
          <el-tag :type="overview.connected ? 'success' : 'danger'" size="small" effect="light">
            {{ overview.connected ? `在线 v${overview.flink_version || ''}` : '离线 / 未连接' }}
          </el-tag>
        </div>
        <div class="c-cell">
          <span class="c-k">TaskManager</span>
          <strong>{{ overview.connected ? overview.taskmanagers : '-' }}</strong>
        </div>
        <div class="c-cell slot-cell">
          <div class="slot-head">
            <span class="c-k">槽位占用</span>
            <span class="slot-text">
              {{ overview.connected ? `已用 ${slotsUsed} / 共 ${overview.slots_total}（可用 ${overview.slots_available}）` : '-' }}
            </span>
          </div>
          <el-progress
            :percentage="slotUsagePercent"
            :status="slotUsagePercent >= 100 ? 'warning' : undefined"
            :stroke-width="6"
            :show-text="false"
          />
        </div>
        <div class="c-cell">
          <span class="c-k">Kafka 集群</span>
          <div class="kafka-line">
            <el-tag :type="overview.kafka_connected ? 'success' : 'info'" size="small" effect="light">
              {{ overview.kafka_connected ? '已连通' : '未检测' }}
            </el-tag>
            <code>{{ overview.kafka_admin_bootstrap || overview.kafka_bootstrap || '-' }}</code>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 筛选栏 + 实时作业运维列表 -->
    <el-card shadow="never" class="table-card">
      <div class="filter-bar">
        <div class="filter-left">
          <el-input
            v-model="keyword"
            placeholder="搜索任务名称 / Flink Job ID / 来源库"
            clearable
            style="width: 280px"
          />
          <el-select v-model="modeFilter" placeholder="开发模式" style="width: 130px">
            <el-option label="全部模式" value="all" />
            <el-option label="向导模式" value="wizard" />
            <el-option label="脚本模式" value="script" />
          </el-select>
          <el-select v-model="statusFilter" placeholder="运行状态" style="width: 130px">
            <el-option label="全部状态" value="all" />
            <el-option label="运行中" value="running" />
            <el-option label="已停止" value="stopped" />
            <el-option label="失败" value="failed" />
            <el-option label="待提交" value="draft" />
          </el-select>
        </div>
        <div class="filter-right">
          <span class="muted">共 {{ filteredTasks.length }} 个任务 · 最近更新 {{ lastRefreshedAt || '-' }}</span>
        </div>
      </div>

      <el-table :data="filteredTasks" v-loading="loading" empty-text="暂无符合条件的实时任务">
        <el-table-column label="任务名称" min-width="210">
          <template #default="{ row }">
            <div class="task-name-cell">
              <el-link type="primary" @click="openDetail(row)">{{ row.name }}</el-link>
              <el-tag :type="row.mode === 'script' ? 'warning' : 'primary'" size="small" effect="plain">
                {{ row.mode === 'script' ? '脚本' : '向导' }}
              </el-tag>
            </div>
            <div class="muted">
              {{ row.database_name || '-' }} · {{ (row.tables || []).length }} 张表
              <span v-if="row.description"> · {{ row.description }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="运行状态" width="120">
          <template #default="{ row }">
            <span class="status-pill" :class="row.job_status || 'draft'">
              <i class="dot" />
              {{ statusLabel(row.job_status) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="Flink Job ID" min-width="180">
          <template #default="{ row }">
            <div v-if="row.flink_job_id" class="jid-cell">
              <code>{{ row.flink_job_id.slice(0, 14) }}...</code>
              <el-button link size="small" @click="copyText(row.flink_job_id)">复制</el-button>
            </div>
            <span v-else class="muted">未提交</span>
          </template>
        </el-table-column>

        <el-table-column label="运行时长" width="130">
          <template #default="{ row }">
            <span v-if="row.duration_ms != null">{{ formatDuration(row.duration_ms) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>

        <el-table-column label="并发 / Checkpoint" width="160">
          <template #default="{ row }">
            <div>并行度 {{ row.channel?.parallelism || 1 }}</div>
            <div class="muted">间隔 {{ Math.round((row.channel?.checkpoint_interval_ms || 10000) / 1000) }}s</div>
          </template>
        </el-table-column>

        <el-table-column label="最近断点 (Checkpoint)" min-width="175">
          <template #default="{ row }">
            <el-tooltip v-if="row.last_checkpoint" :content="row.last_checkpoint" placement="top">
              <el-tag size="small" type="success" effect="plain" class="ckpt-tag">
                {{ shortCkpt(row.last_checkpoint) }}
              </el-tag>
            </el-tooltip>
            <span v-else class="muted">尚无检查点</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.job_status !== 'running'"
              link
              type="success"
              @click="openLaunchDialog(row)"
            >
              {{ row.last_checkpoint ? '续跑 / 启动' : '启动' }}
            </el-button>
            <el-button
              v-else
              link
              type="danger"
              @click="onStop(row)"
            >
              停止
            </el-button>
            <el-button link type="primary" @click="openDetail(row)">运维详情</el-button>
            <el-button link @click="router.push(`/realtime/tasks/${row.id}`)">配置</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 启动 / 断点续跑方式选择弹窗（对齐 Taier 启动方式弹窗） -->
    <el-dialog v-model="launchDialog.visible" title="启动实时同步作业" width="540px">
      <div v-if="launchDialog.task" class="launch-body">
        <div class="launch-task-title">
          <strong>{{ launchDialog.task.name }}</strong>
          <el-tag size="small" :type="launchDialog.task.mode === 'script' ? 'warning' : 'primary'">
            {{ launchDialog.task.mode === 'script' ? '脚本模式' : '向导模式' }}
          </el-tag>
        </div>

        <el-alert
          v-if="overview.connected && overview.slots_available === 0"
          type="warning"
          show-icon
          :closable="false"
          title="当前 Flink 集群可用槽位为 0，直接提交可能无法调度，请先停止其他运行中作业或扩容 TaskManager 槽位。"
          style="margin-bottom: 14px"
        />

        <el-radio-group v-model="launchDialog.mode" class="launch-radios">
          <el-radio
            value="resume_latest"
            :disabled="!launchDialog.task.last_checkpoint"
            border
          >
            <div class="radio-title">从最近检查点续跑（推荐）</div>
            <div class="radio-desc">
              {{ launchDialog.task.last_checkpoint || '当前任务尚无已保存的检查点，首次运行请选择全新启动' }}
            </div>
          </el-radio>

          <el-radio value="fresh" border>
            <div class="radio-title">全新启动（忽略已有状态）</div>
            <div class="radio-desc">
              按任务配置的启动位点（{{ launchDialog.task.channel?.startup_mode || 'initial' }}）重新开始同步
            </div>
          </el-radio>

          <el-radio value="custom_ckpt" border>
            <div class="radio-title">指定检查点路径恢复</div>
            <div class="radio-desc">从指定的 Checkpoint / Savepoint 路径恢复 Binlog 位点与状态</div>
          </el-radio>
        </el-radio-group>

        <el-input
          v-if="launchDialog.mode === 'custom_ckpt'"
          v-model="launchDialog.checkpointPath"
          placeholder="例如：file:/opt/flink/state/checkpoints/<jobId>/chk-89"
          style="margin-top: 10px"
        />
      </div>
      <template #footer>
        <el-button @click="launchDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="launchDialog.submitting" @click="confirmLaunch">确认提交</el-button>
      </template>
    </el-dialog>

    <!-- 运维详情抽屉（对齐 Taier 实时任务运维详情 4 Tab） -->
    <el-drawer
      v-model="drawer.visible"
      size="72%"
      :destroy-on-close="false"
      class="ops-drawer"
    >
      <template #header>
        <div class="drawer-head" v-if="drawerTask">
          <div class="drawer-title">
            <h3>{{ drawerTask.name }}</h3>
            <el-tag :type="drawerTask.mode === 'script' ? 'warning' : 'primary'" size="small">
              {{ drawerTask.mode === 'script' ? '脚本模式' : '向导模式' }}
            </el-tag>
            <span class="status-pill" :class="drawerTask.job_status || 'draft'">
              <i class="dot" />
              {{ statusLabel(drawerTask.job_status) }}
            </span>
          </div>
          <div class="drawer-ops">
            <el-button size="small" @click="refreshDrawer" :loading="drawer.loading">刷新详情</el-button>
            <el-button
              v-if="drawerTask.job_status !== 'running'"
              size="small"
              type="success"
              @click="openLaunchDialog(drawerTask)"
            >
              启动 / 续跑
            </el-button>
            <el-button v-else size="small" type="danger" plain @click="onStop(drawerTask)">停止作业</el-button>
            <el-button size="small" @click="router.push(`/realtime/tasks/${drawerTask.id}`)">编辑配置</el-button>
          </div>
        </div>
      </template>

      <div v-loading="drawer.loading" class="drawer-body" v-if="drawerTask">
        <el-alert
          v-if="drawer.runtime?.error"
          type="warning"
          show-icon
          :closable="false"
          :title="drawer.runtime.error"
          style="margin-bottom: 12px"
        />

        <el-tabs v-model="drawer.tab">
          <!-- Tab 1: 运行拓扑与流量 -->
          <el-tab-pane label="运行概览与算子流量" name="overview">
            <div class="kpi-grid">
              <div class="kpi-box">
                <div class="kpi-k">Flink Job ID</div>
                <div class="kpi-v mono">
                  {{ drawerTask.flink_job_id || '未提交' }}
                  <el-button v-if="drawerTask.flink_job_id" link size="small" @click="copyText(drawerTask.flink_job_id)">复制</el-button>
                </div>
              </div>
              <div class="kpi-box">
                <div class="kpi-k">启动时间 / 运行时长</div>
                <div class="kpi-v">
                  {{ formatTs(drawer.runtime?.job?.start_time) }}
                  <span class="muted" v-if="drawer.runtime?.job?.duration_ms != null">
                    （{{ formatDuration(drawer.runtime.job.duration_ms) }}）
                  </span>
                </div>
              </div>
              <div class="kpi-box">
                <div class="kpi-k">Checkpoint 统计</div>
                <div class="kpi-v">
                  成功 <strong>{{ drawer.runtime?.checkpoints?.counts?.completed ?? 0 }}</strong>
                  · 失败 <strong class="danger-txt">{{ drawer.runtime?.checkpoints?.counts?.failed ?? 0 }}</strong>
                  · 已恢复 <strong>{{ drawer.runtime?.checkpoints?.counts?.restored ?? 0 }}</strong>
                </div>
              </div>
              <div class="kpi-box">
                <div class="kpi-k">最近检查点状态大小</div>
                <div class="kpi-v">
                  {{ formatBytes(drawer.runtime?.checkpoints?.latest_completed?.state_size) }}
                  <span class="muted" v-if="drawer.runtime?.checkpoints?.latest_completed?.end_to_end_duration != null">
                    （耗时 {{ drawer.runtime.checkpoints.latest_completed.end_to_end_duration }} ms）
                  </span>
                </div>
              </div>
            </div>

            <div class="sec-title">算子执行链路（Flink Vertices）</div>
            <el-table :data="drawer.runtime?.vertices || []" size="small" border empty-text="作业尚未运行或无算子数据">
              <el-table-column prop="name" label="算子名称" min-width="260" show-overflow-tooltip />
              <el-table-column prop="parallelism" label="并行度" width="75" align="center" />
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.status === 'RUNNING' ? 'success' : 'info'">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="接收 / 发送记录数" width="150" align="right">
                <template #default="{ row }">{{ row.read_records }} / {{ row.write_records }}</template>
              </el-table-column>
              <el-table-column label="接收 / 发送字节" width="160" align="right">
                <template #default="{ row }">{{ formatBytes(row.read_bytes) }} / {{ formatBytes(row.write_bytes) }}</template>
              </el-table-column>
              <el-table-column label="繁忙 / 背压耗时" width="150" align="right">
                <template #default="{ row }">
                  {{ Math.round(row.busy_ms || 0) }}ms /
                  <span :class="{ 'danger-txt': (row.backpressured_ms || 0) > 1000 }">
                    {{ Math.round(row.backpressured_ms || 0) }}ms
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- Tab 2: Checkpoint 历史与断点恢复 -->
          <el-tab-pane label="Checkpoint 历史" name="checkpoints">
            <div class="ckpt-summary">
              <span>总计：<strong>{{ drawer.runtime?.checkpoints?.counts?.total ?? 0 }}</strong></span>
              <span>已完成：<strong class="ok-txt">{{ drawer.runtime?.checkpoints?.counts?.completed ?? 0 }}</strong></span>
              <span>失败：<strong class="danger-txt">{{ drawer.runtime?.checkpoints?.counts?.failed ?? 0 }}</strong></span>
              <span>进行中：<strong>{{ drawer.runtime?.checkpoints?.counts?.in_progress ?? 0 }}</strong></span>
              <span class="muted">（Flink 默认保留最新未清理的检查点，仅“可恢复”状态的检查点支持直接回滚启动）</span>
            </div>

            <el-table :data="drawer.runtime?.checkpoints?.history || []" size="small" border empty-text="暂无 Checkpoint 记录">
              <el-table-column prop="id" label="ID" width="70" align="center" />
              <el-table-column label="状态" width="105" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.status === 'COMPLETED' ? 'success' : (row.status === 'FAILED' ? 'danger' : 'warning')">
                    {{ row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="触发时间" width="165">
                <template #default="{ row }">{{ formatTs(row.trigger_timestamp) }}</template>
              </el-table-column>
              <el-table-column label="耗时" width="85" align="right">
                <template #default="{ row }">{{ row.duration_ms != null ? `${row.duration_ms} ms` : '-' }}</template>
              </el-table-column>
              <el-table-column label="状态大小" width="95" align="right">
                <template #default="{ row }">{{ formatBytes(row.state_size) }}</template>
              </el-table-column>
              <el-table-column label="存储路径" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <code v-if="row.external_path">{{ row.external_path }}</code>
                  <span v-else class="muted">-</span>
                </template>
              </el-table-column>
              <el-table-column label="留存" width="85" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.recoverable ? 'success' : 'info'" effect="plain">
                    {{ row.recoverable ? '可恢复' : '已清理' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="110" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button
                    v-if="row.recoverable"
                    link
                    type="primary"
                    size="small"
                    @click="recoverFromCheckpoint(row)"
                  >
                    从此恢复
                  </el-button>
                  <span v-else class="muted">-</span>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- Tab 3: 异常与日志 -->
          <el-tab-pane label="异常与运行日志" name="exceptions">
            <el-alert
              v-if="drawerTask.last_error"
              type="error"
              show-icon
              :closable="false"
              title="平台最近记录的错误信息"
              :description="drawerTask.last_error"
              style="margin-bottom: 14px"
            />

            <div class="sec-title">
              Flink Root Exception
              <span class="muted" v-if="drawer.runtime?.exceptions?.timestamp">
                （发生于 {{ formatTs(drawer.runtime.exceptions.timestamp) }}）
              </span>
            </div>
            <pre v-if="drawer.runtime?.exceptions?.root_exception" class="code-box error-log">{{ drawer.runtime.exceptions.root_exception }}</pre>
            <el-empty v-else description="当前作业暂无 Flink 运行期异常" :image-size="68" />

            <template v-if="(drawer.runtime?.exceptions?.history || []).length">
              <div class="sec-title" style="margin-top: 16px">历史异常记录（Failover History）</div>
              <el-collapse>
                <el-collapse-item
                  v-for="(ex, idx) in drawer.runtime.exceptions.history"
                  :key="idx"
                  :title="`${formatTs(ex.timestamp)} · ${ex.exception_name || 'Exception'} ${ex.task_name ? '(' + ex.task_name + ')' : ''}`"
                >
                  <pre class="code-box error-log">{{ ex.stacktrace }}</pre>
                </el-collapse-item>
              </el-collapse>
            </template>
          </el-tab-pane>

          <!-- Tab 4: 执行 SQL 与通道配置 -->
          <el-tab-pane label="执行 SQL 与配置" name="sql">
            <el-descriptions :column="3" border size="small" style="margin-bottom: 14px">
              <el-descriptions-item label="开发模式">{{ drawerTask.mode === 'script' ? '脚本模式' : '向导模式' }}</el-descriptions-item>
              <el-descriptions-item label="来源库">{{ drawerTask.database_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="并行度">{{ drawerTask.channel?.parallelism || 1 }}</el-descriptions-item>
              <el-descriptions-item label="Checkpoint 间隔">{{ drawerTask.channel?.checkpoint_interval_ms || 10000 }} ms</el-descriptions-item>
              <el-descriptions-item label="启动位点">{{ drawerTask.channel?.startup_mode || 'initial' }}</el-descriptions-item>
              <el-descriptions-item label="Kafka 副本 / 保留">
                {{ drawerTask.channel?.topic_replication_factor || 1 }} 副本 · {{ drawerTask.channel?.topic_retention_days || 7 }} 天
              </el-descriptions-item>
              <el-descriptions-item label="目标 Kafka 主题" :span="3">
                <el-tag
                  v-for="t in (drawerTask.tables || [])"
                  :key="t.topic || t.table"
                  size="small"
                  style="margin-right: 6px"
                >
                  {{ t.table }} → {{ t.topic }}
                </el-tag>
                <span v-if="!(drawerTask.tables || []).length" class="muted">脚本自定义</span>
              </el-descriptions-item>
            </el-descriptions>

            <div class="sql-bar">
              <span class="sec-title" style="margin: 0">Flink SQL（密码已脱敏）</span>
              <el-button size="small" @click="copyText(drawerSql)">复制 SQL</el-button>
            </div>
            <pre class="code-box">{{ drawerSql || '暂无 SQL' }}</pre>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getRealtimeTaskRuntime,
  listRealtimeOpsTasks,
  stopRealtimeTask,
  submitRealtimeTask
} from '@/api'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const syncing = ref(false)
const autoRefresh = ref(true)
const overview = ref({})
const stats = ref({ total: 0, running: 0, stopped: 0, failed: 0, draft: 0 })
const tasks = ref([])
const lastRefreshedAt = ref('')

const keyword = ref('')
const modeFilter = ref('all')
const statusFilter = ref('all')

let pollTimer = null

const launchDialog = reactive({
  visible: false,
  task: null,
  mode: 'resume_latest',
  checkpointPath: '',
  submitting: false
})

const drawer = reactive({
  visible: false,
  loading: false,
  tab: 'overview',
  taskId: null,
  task: null,
  runtime: null
})

const drawerTask = computed(() => drawer.task)
const drawerSql = computed(() => {
  if (!drawer.task) return ''
  return drawer.task.mode === 'script'
    ? (drawer.task.script_sql || drawer.task.generated_sql || '')
    : (drawer.task.generated_sql || '')
})

const statCards = computed(() => [
  { key: 'all', label: '全部任务', value: stats.value.total || 0, tone: 'neutral' },
  { key: 'running', label: '运行中', value: stats.value.running || 0, tone: 'ok' },
  { key: 'stopped', label: '已停止', value: stats.value.stopped || 0, tone: 'warn' },
  { key: 'failed', label: '异常 / 失败', value: stats.value.failed || 0, tone: 'danger' },
  { key: 'draft', label: '待提交', value: stats.value.draft || 0, tone: 'muted' }
])

const slotsUsed = computed(() => {
  const total = Number(overview.value.slots_total || 0)
  const avail = Number(overview.value.slots_available || 0)
  return Math.max(0, total - avail)
})

const slotUsagePercent = computed(() => {
  const total = Number(overview.value.slots_total || 0)
  if (!total) return 0
  return Math.min(100, Math.round((slotsUsed.value / total) * 100))
})

const filteredTasks = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return tasks.value.filter((t) => {
    if (statusFilter.value !== 'all' && (t.job_status || 'draft') !== statusFilter.value) return false
    if (modeFilter.value !== 'all' && (t.mode || 'wizard') !== modeFilter.value) return false
    if (kw) {
      const hay = `${t.name || ''} ${t.flink_job_id || ''} ${t.database_name || ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

const statusLabel = (s) => ({
  draft: '待提交',
  running: '运行中',
  stopped: '已停止',
  failed: '失败'
}[s] || s || '待提交')

function shortCkpt(path) {
  if (!path) return ''
  const parts = String(path).split('/')
  return parts[parts.length - 1] || path
}

function formatDuration(ms) {
  if (ms == null || ms < 0) return '-'
  const sec = Math.floor(ms / 1000)
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (d > 0) return `${d}天 ${h}时 ${m}分`
  if (h > 0) return `${h}时 ${m}分 ${s}秒`
  if (m > 0) return `${m}分 ${s}秒`
  return `${s}秒`
}

function formatTs(ts) {
  if (!ts) return '-'
  const d = new Date(Number(ts))
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(b) {
  if (b == null) return '-'
  const n = Number(b)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(String(text || ''))
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

async function loadOps(syncCluster = false, silent = false) {
  if (syncCluster) syncing.value = true
  else if (!silent) loading.value = true
  try {
    const res = await listRealtimeOpsTasks(syncCluster)
    const d = res.data || {}
    overview.value = d.overview || {}
    stats.value = d.stats || { total: 0, running: 0, stopped: 0, failed: 0, draft: 0 }
    tasks.value = d.tasks || []
    lastRefreshedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    if (syncCluster) ElMessage.success('已与 Flink 集群同步状态')
  } catch (e) {
    if (!silent) ElMessage.error(e?.message || '加载运维列表失败')
  } finally {
    loading.value = false
    syncing.value = false
  }
}

async function openDetail(row) {
  drawer.taskId = row.id
  drawer.task = row
  drawer.tab = 'overview'
  drawer.visible = true
  await refreshDrawer()
}

async function refreshDrawer() {
  if (!drawer.taskId) return
  drawer.loading = true
  try {
    const res = await getRealtimeTaskRuntime(drawer.taskId)
    drawer.task = res.data?.task || drawer.task
    drawer.runtime = res.data?.runtime || null
  } catch (e) {
    ElMessage.error(e?.message || '获取作业运行详情失败')
  } finally {
    drawer.loading = false
  }
}

function openLaunchDialog(row) {
  launchDialog.task = row
  launchDialog.mode = row.last_checkpoint ? 'resume_latest' : 'fresh'
  launchDialog.checkpointPath = row.last_checkpoint || ''
  launchDialog.visible = true
}

async function confirmLaunch() {
  const t = launchDialog.task
  if (!t) return
  let resume = true
  let ckptPath = ''
  if (launchDialog.mode === 'fresh') {
    resume = false
  } else if (launchDialog.mode === 'custom_ckpt') {
    ckptPath = (launchDialog.checkpointPath || '').trim()
    if (!ckptPath) {
      ElMessage.warning('请输入要恢复的检查点路径')
      return
    }
  }
  launchDialog.submitting = true
  try {
    await submitRealtimeTask(t.id, resume, ckptPath)
    ElMessage.success(resume ? '已提交并从检查点恢复' : '已全新提交运行')
    launchDialog.visible = false
    await loadOps(true)
    if (drawer.visible && drawer.taskId === t.id) await refreshDrawer()
  } catch (e) {
    ElMessage.error(e?.message || '提交作业失败')
  } finally {
    launchDialog.submitting = false
  }
}

async function onStop(row) {
  try {
    await ElMessageBox.confirm(
      `确定停止「${row.name}」吗？系统会在停止前记录最近一次已完成的 Checkpoint，后续可随时从断点续跑。`,
      '停止实时作业',
      { type: 'warning', confirmButtonText: '确认停止', cancelButtonText: '取消' }
    )
    await stopRealtimeTask(row.id)
    ElMessage.success('作业已停止，已保留最新检查点')
    await loadOps(true)
    if (drawer.visible && drawer.taskId === row.id) await refreshDrawer()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '停止失败')
  }
}

async function recoverFromCheckpoint(ckptRow) {
  if (!drawerTask.value) return
  const task = drawerTask.value
  const hint = task.job_status === 'running'
    ? `当前作业正在运行，确定先停止当前作业并从 chk-${ckptRow.id}（${ckptRow.external_path}）恢复启动吗？`
    : `确定从检查点 chk-${ckptRow.id}（${ckptRow.external_path}）恢复启动「${task.name}」吗？`
  try {
    await ElMessageBox.confirm(hint, '从历史检查点恢复', {
      type: 'warning',
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消'
    })
    if (task.job_status === 'running') {
      await stopRealtimeTask(task.id)
    }
    await submitRealtimeTask(task.id, true, ckptRow.external_path)
    ElMessage.success(`已从检查点 #${ckptRow.id} 恢复启动`)
    await loadOps(true)
    await refreshDrawer()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '恢复启动失败')
  }
}

function setupPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  if (autoRefresh.value) {
    pollTimer = setInterval(() => {
      loadOps(false, true)
    }, 10000)
  }
}

watch(autoRefresh, setupPolling)

onMounted(async () => {
  await loadOps(false)
  setupPolling()
  const qid = Number(route.query.taskId || 0)
  if (qid) {
    const found = tasks.value.find((t) => Number(t.id) === qid)
    if (found) openDetail(found)
  }
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.ops-page { display: flex; flex-direction: column; gap: 14px; }
.ops-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.ops-head h2 { margin: 0 0 4px; font-size: 20px; color: #0f172a; }
.sub { margin: 0; font-size: 13px; color: #64748b; }
.ops-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.auto-refresh { display: flex; align-items: center; gap: 6px; padding: 4px 10px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.ar-label { font-size: 12px; color: #475569; }

.stat-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.stat-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.stat-card:hover { border-color: #93c5fd; transform: translateY(-1px); }
.stat-card.active { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12); }
.stat-label { font-size: 12px; color: #64748b; margin-bottom: 6px; }
.stat-val { font-size: 24px; font-weight: 700; color: #0f172a; line-height: 1.1; }
.stat-card.ok .stat-val { color: #16a34a; }
.stat-card.warn .stat-val { color: #d97706; }
.stat-card.danger .stat-val { color: #dc2626; }
.stat-card.muted .stat-val { color: #64748b; }

.cluster-card, .table-card { border-radius: 10px; }
.cluster-row { display: grid; grid-template-columns: 1.1fr 0.7fr 1.6fr 1.6fr; gap: 18px; align-items: center; }
.c-cell { display: flex; flex-direction: column; gap: 5px; }
.c-k { font-size: 12px; color: #64748b; }
.slot-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.slot-text { font-size: 12px; color: #334155; font-weight: 500; }
.kafka-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.filter-bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.filter-left { display: flex; gap: 8px; flex-wrap: wrap; }
.task-name-cell { display: flex; align-items: center; gap: 6px; }
.jid-cell { display: flex; align-items: center; gap: 6px; }
.ckpt-tag { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 999px;
}
.status-pill .dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.status-pill.running { background: #ecfdf5; color: #15803d; }
.status-pill.running .dot { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.25); }
.status-pill.stopped { background: #fffbeb; color: #b45309; }
.status-pill.stopped .dot { background: #f59e0b; }
.status-pill.failed { background: #fef2f2; color: #b91c1c; }
.status-pill.failed .dot { background: #ef4444; }
.status-pill.draft { background: #f1f5f9; color: #475569; }
.status-pill.draft .dot { background: #94a3b8; }

.launch-task-title { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; font-size: 15px; }
.launch-radios { display: flex; flex-direction: column; gap: 10px; width: 100%; }
.launch-radios :deep(.el-radio) { width: 100%; height: auto; padding: 10px 14px; margin-right: 0; align-items: flex-start; }
.radio-title { font-weight: 600; color: #0f172a; margin-bottom: 2px; }
.radio-desc { font-size: 12px; color: #64748b; white-space: normal; word-break: break-all; }

.drawer-head { display: flex; justify-content: space-between; align-items: center; width: 100%; gap: 12px; flex-wrap: wrap; }
.drawer-title { display: flex; align-items: center; gap: 8px; }
.drawer-title h3 { margin: 0; font-size: 17px; color: #0f172a; }
.drawer-ops { display: flex; gap: 6px; flex-wrap: wrap; }

.kpi-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
.kpi-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; }
.kpi-k { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.kpi-v { font-size: 13.5px; color: #0f172a; }
.kpi-v.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; word-break: break-all; }

.sec-title { font-size: 13.5px; font-weight: 600; color: #0f172a; margin: 4px 0 10px; }
.ckpt-summary { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; padding: 10px 12px; background: #f8fafc; border-radius: 8px; font-size: 13px; }
.ok-txt { color: #16a34a; }
.danger-txt { color: #dc2626; }

.sql-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.code-box {
  background: #0f172a;
  color: #e2e8f0;
  padding: 14px;
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  overflow: auto;
  max-height: 440px;
  margin: 0;
  white-space: pre;
}
.code-box.error-log { color: #fecaca; white-space: pre-wrap; word-break: break-word; }
.muted { font-size: 12px; color: #94a3b8; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #334155; }

@media (max-width: 1024px) {
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .cluster-row { grid-template-columns: 1fr; }
}
</style>
