<template>
  <div class="doris-page">
    <!-- 顶部标题栏 -->
    <div class="page-head">
      <div>
        <h2>Doris 实时入库与数仓</h2>
        <p class="sub">
          承接 Kafka 实时流并经 Routine Load 写入 Apache Doris Unique Key 明细表，提供入库运维、实时数据预览与 Doris SQL 控制台。
        </p>
      </div>
      <div class="head-ops">
        <div class="auto-box">
          <span>自动刷新(10s)</span>
          <el-switch v-model="autoRefresh" size="small" />
        </div>
        <el-button @click="loadAll" :loading="loading">刷新</el-button>
        <el-button type="primary" :disabled="!dorisOverview.connected" @click="openCreateDialog">
          新建 Routine Load
        </el-button>
      </div>
    </div>

    <!-- 端到端实时链路可视化拓扑条 -->
    <div class="pipeline-strip">
      <div class="pipe-node" @click="router.push('/datasource')">
        <div class="pn-top">
          <span class="pn-badge mysql">1. MySQL 业务库</span>
          <span class="pn-dot ok" />
        </div>
        <div class="pn-val">Binlog ROW</div>
        <div class="pn-desc">订单 / 退款 / 物流源表</div>
      </div>
      <div class="pipe-arrow">→</div>
      <div class="pipe-node" @click="router.push('/realtime/ops')">
        <div class="pn-top">
          <span class="pn-badge flink">2. Flink CDC</span>
          <span class="pn-dot" :class="rtOverview.connected ? 'ok' : 'off'" />
        </div>
        <div class="pn-val">{{ rtOverview.connected ? `${rtOverview.jobs_running || 0} 个运行中` : '未连接' }}</div>
        <div class="pn-desc">槽位 {{ rtOverview.slots_available ?? '-' }} / {{ rtOverview.slots_total ?? '-' }}</div>
      </div>
      <div class="pipe-arrow">→</div>
      <div class="pipe-node" @click="router.push('/realtime/topics')">
        <div class="pn-top">
          <span class="pn-badge kafka">3. Kafka 主题</span>
          <span class="pn-dot" :class="rtOverview.kafka_connected ? 'ok' : 'off'" />
        </div>
        <div class="pn-val">{{ kafkaTopics.length }} 个主题</div>
        <div class="pn-desc">Debezium JSON 实时流</div>
      </div>
      <div class="pipe-arrow">→</div>
      <div class="pipe-node active">
        <div class="pn-top">
          <span class="pn-badge doris">4. Apache Doris</span>
          <span class="pn-dot" :class="dorisOverview.connected ? 'ok' : 'err'" />
        </div>
        <div class="pn-val">
          {{ dorisOverview.connected ? `${formatNum(dorisOverview.routine_load_summary?.total_loaded_rows || 0)} 行已入库` : '未连接' }}
        </div>
        <div class="pn-desc">
          库 {{ dorisOverview.database }} · {{ dorisOverview.table_count || 0 }} 张表 · {{ dorisOverview.routine_load_summary?.running || 0 }} 个运行中入库
        </div>
      </div>
    </div>

    <!-- Doris 集群健康栏 -->
    <el-alert
      v-if="dorisOverview.error"
      type="warning"
      show-icon
      :closable="false"
      :title="dorisOverview.error"
    />
    <el-card v-else shadow="never" class="cluster-bar">
      <div class="cluster-grid">
        <div class="c-item">
          <span class="c-k">Frontend (FE)</span>
          <div class="c-v">
            <el-tag
              v-for="fe in dorisOverview.frontends"
              :key="fe.name"
              :type="fe.alive ? 'success' : 'danger'"
              size="small"
              style="margin-right: 6px"
            >
              {{ fe.host }} {{ fe.is_master ? '(Master)' : '' }}
            </el-tag>
            <span v-if="!dorisOverview.frontends?.length" class="muted">-</span>
          </div>
        </div>
        <div class="c-item">
          <span class="c-k">Backend (BE)</span>
          <div class="c-v">
            <el-tag
              v-for="be in dorisOverview.backends"
              :key="be.id"
              :type="be.alive ? 'success' : 'danger'"
              size="small"
              style="margin-right: 6px"
            >
              {{ be.host }} · {{ be.tablet_num }} tablets · 磁盘 {{ be.used_pct || '-' }}
            </el-tag>
            <span v-if="!dorisOverview.backends?.length" class="muted">暂无 BE</span>
          </div>
        </div>
        <div class="c-item">
          <span class="c-k">Routine Load 作业</span>
          <div class="c-v">
            运行 <strong class="ok-txt">{{ dorisOverview.routine_load_summary?.running || 0 }}</strong>
            · 暂停 <strong class="warn-txt">{{ dorisOverview.routine_load_summary?.paused || 0 }}</strong>
            · 异常行 <strong :class="{ 'err-txt': (dorisOverview.routine_load_summary?.total_error_rows || 0) > 0 }">
              {{ dorisOverview.routine_load_summary?.total_error_rows || 0 }}
            </strong>
          </div>
        </div>
        <div class="c-item">
          <span class="c-k">目标库 / 连接</span>
          <div class="c-v">
            <code>{{ dorisOverview.host }}:{{ dorisOverview.port }}/{{ dorisOverview.database }}</code>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 主功能 Tabs -->
    <el-card shadow="never" class="main-card">
      <el-tabs v-model="activeTab">
        <!-- Tab 1: Routine Load 入库任务 -->
        <el-tab-pane :label="`Routine Load 入库 (${routineLoads.length})`" name="loads">
          <el-table :data="routineLoads" v-loading="loading" empty-text="还没有 Routine Load 入库作业，点击右上角「新建 Routine Load」">
            <el-table-column prop="name" label="入库作业名" min-width="180">
              <template #default="{ row }">
                <strong>{{ row.name }}</strong>
                <div class="muted">{{ row.create_time || '-' }}</div>
              </template>
            </el-table-column>

            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <span class="state-pill" :class="(row.state || '').toLowerCase()">
                  <i class="dot" />
                  {{ row.state }}
                </span>
              </template>
            </el-table-column>

            <el-table-column label="数据流向（Kafka → Doris）" min-width="290">
              <template #default="{ row }">
                <div class="flow-cell">
                  <el-tag size="small" type="info" effect="plain">{{ row.topic || '-' }}</el-tag>
                  <span class="arrow">→</span>
                  <el-tag size="small" type="primary" effect="plain" class="clickable" @click="jumpToTable(row.table_name)">
                    {{ row.table_name }}
                  </el-tag>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="已入库 / 错误行" width="150" align="right">
              <template #default="{ row }">
                <div><strong>{{ formatNum(row.loaded_rows) }}</strong> 行</div>
                <div class="muted" :class="{ 'err-txt': row.error_rows > 0 }">错误 {{ row.error_rows }} 行</div>
              </template>
            </el-table-column>

            <el-table-column label="Kafka 消费位点" min-width="150">
              <template #default="{ row }">
                <code>{{ formatProgress(row.progress) }}</code>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.state === 'RUNNING'"
                  link
                  type="warning"
                  @click="onControlLoad(row, 'pause')"
                >
                  暂停
                </el-button>
                <el-button
                  v-if="row.state === 'PAUSED'"
                  link
                  type="success"
                  @click="onControlLoad(row, 'resume')"
                >
                  恢复
                </el-button>
                <el-button
                  v-if="row.state !== 'STOPPED' && row.state !== 'CANCELLED'"
                  link
                  type="danger"
                  @click="onControlLoad(row, 'stop')"
                >
                  停止
                </el-button>
                <el-button link type="primary" @click="openLoadDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- Tab 2: 实时明细表预览 -->
        <el-tab-pane :label="`实时明细表 (${tables.length})`" name="tables">
          <div class="table-explorer">
            <div class="te-sidebar">
              <div class="te-side-head">
                <strong>{{ dorisOverview.database }} 表目录</strong>
                <el-button link size="small" @click="loadTables">刷新</el-button>
              </div>
              <div
                v-for="t in tables"
                :key="t.name"
                class="te-item"
                :class="{ active: selectedTable === t.name }"
                @click="selectTable(t.name)"
              >
                <div class="te-name">{{ t.name }}</div>
                <div class="te-meta">
                  <span>{{ t.table_type === 'VIEW' ? '视图' : '明细表' }}</span>
                  <el-tag size="small" type="info" effect="plain">{{ formatNum(t.rows ?? 0) }} 行</el-tag>
                </div>
              </div>
              <el-empty v-if="!tables.length" description="暂无 Doris 表" :image-size="56" />
            </div>

            <div class="te-main" v-loading="previewLoading">
              <template v-if="tablePreview">
                <div class="te-main-head">
                  <div>
                    <strong class="te-title">{{ tablePreview.table }}</strong>
                    <el-tag size="small" type="success" style="margin-left: 8px">
                      实时总行数：{{ formatNum(tablePreview.total_rows) }}
                    </el-tag>
                  </div>
                  <div class="te-main-ops">
                    <el-radio-group v-model="tableViewMode" size="small">
                      <el-radio-button value="data">数据预览（前 20 条）</el-radio-button>
                      <el-radio-button value="schema">表结构 ({{ tablePreview.schema.length }} 列)</el-radio-button>
                    </el-radio-group>
                    <el-button size="small" @click="selectTable(selectedTable)">刷新数据</el-button>
                    <el-button size="small" type="primary" plain @click="openInConsole(tablePreview.table)">
                      在 SQL 控制台查询
                    </el-button>
                  </div>
                </div>

                <el-table
                  v-if="tableViewMode === 'data'"
                  :data="tablePreview.rows"
                  size="small"
                  border
                  max-height="440"
                  empty-text="表中暂无数据"
                >
                  <el-table-column
                    v-for="col in tablePreview.columns"
                    :key="col"
                    :prop="col"
                    :label="col"
                    min-width="130"
                    show-overflow-tooltip
                  />
                </el-table>

                <el-table
                  v-else
                  :data="tablePreview.schema"
                  size="small"
                  border
                  max-height="440"
                >
                  <el-table-column prop="field" label="字段名" min-width="150" />
                  <el-table-column prop="type" label="Doris 类型" min-width="150" />
                  <el-table-column prop="key" label="主键" width="90" align="center">
                    <template #default="{ row }">
                      <el-tag v-if="row.key === 'true'" size="small" type="warning">KEY</el-tag>
                      <span v-else class="muted">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="nullable" label="可空" width="80" align="center" />
                  <el-table-column prop="default" label="默认值" min-width="110" />
                </el-table>
              </template>
              <el-empty v-else description="点击左侧表名查看实时数据与结构" :image-size="72" />
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 3: Doris SQL 控制台（对齐 Taier SQL 编辑器 + SQLBot 结果展示） -->
        <el-tab-pane label="Doris SQL 控制台" name="console">
          <div class="sql-presets">
            <span class="muted">快捷查询：</span>
            <el-button
              v-for="p in sqlPresets"
              :key="p.label"
              size="small"
              plain
              @click="applyPreset(p.sql)"
            >
              {{ p.label }}
            </el-button>
          </div>

          <div class="sql-editor-wrap">
            <el-input
              v-model="sqlInput"
              type="textarea"
              :rows="7"
              placeholder="输入 Doris SQL，按 Ctrl + Enter 执行（非管理员仅限 SELECT / SHOW / DESC）"
              @keydown.ctrl.enter.prevent="runSql"
            />
          </div>

          <div class="sql-bar">
            <div class="muted">
              当前库：<code>{{ dorisOverview.database }}</code> · 未带 LIMIT 的 SELECT 自动限 500 行
            </div>
            <el-button type="primary" :loading="sqlRunning" @click="runSql">执行 SQL (Ctrl+Enter)</el-button>
          </div>

          <el-alert v-if="sqlError" type="error" show-icon :closable="false" :title="sqlError" style="margin-top: 12px" />

          <div v-if="sqlResult" class="sql-result">
            <div class="sr-head">
              <span>返回 <strong>{{ sqlResult.row_count }}</strong> 行 · 耗时 <strong>{{ sqlResult.elapsed_ms }} ms</strong></span>
              <code class="muted">{{ sqlResult.executed_sql }}</code>
            </div>
            <el-table :data="sqlResult.rows" size="small" border max-height="380" empty-text="查询返回 0 行">
              <el-table-column
                v-for="col in sqlResult.columns"
                :key="col"
                :prop="col"
                :label="col"
                min-width="130"
                show-overflow-tooltip
              />
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 新建 Routine Load 弹窗 -->
    <el-dialog v-model="createDialog.visible" title="新建 Doris Routine Load 实时入库作业" width="560px">
      <el-form label-width="115px">
        <el-form-item label="入库作业名" required>
          <el-input v-model="createDialog.form.job_name" placeholder="例如 rl_oms_shipment" />
        </el-form-item>
        <el-form-item label="来源 Kafka 主题" required>
          <el-select v-model="createDialog.form.topic" filterable allow-create placeholder="选择或输入 Kafka 主题" style="width: 100%">
            <el-option v-for="t in kafkaTopics" :key="t.name" :label="t.name" :value="t.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标 Doris 表" required>
          <el-select v-model="createDialog.form.table_name" filterable placeholder="选择目标表" style="width: 100%">
            <el-option v-for="t in tables" :key="t.name" :label="`${t.name} (${t.rows ?? 0} 行)`" :value="t.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="消息格式">
          <el-radio-group v-model="createDialog.form.format">
            <el-radio value="debezium-json">Debezium JSON（Flink CDC 默认，自动处理删改）</el-radio>
            <el-radio value="json">普通扁平 JSON</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="起始消费位点">
          <el-radio-group v-model="createDialog.form.offset">
            <el-radio value="OFFSET_BEGINNING">从最早消息开始（含全量快照）</el-radio>
            <el-radio value="OFFSET_END">仅消费最新增量</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="并发 / 容错上限">
          <div class="inline-nums">
            <el-input-number v-model="createDialog.form.desired_concurrent_number" :min="1" :max="8" />
            <span class="muted">并发度</span>
            <el-input-number v-model="createDialog.form.max_error_number" :min="0" :max="100000" :step="10" />
            <span class="muted">最大错误行</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="createDialog.submitting" @click="submitCreateLoad">创建并启动入库</el-button>
      </template>
    </el-dialog>

    <!-- Routine Load 详情弹窗 -->
    <el-dialog v-model="detailDialog.visible" :title="`Routine Load 详情 · ${detailDialog.row?.name || ''}`" width="640px">
      <template v-if="detailDialog.row">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="作业 ID">{{ detailDialog.row.id }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">{{ detailDialog.row.state }}</el-descriptions-item>
          <el-descriptions-item label="来源主题">{{ detailDialog.row.topic }}</el-descriptions-item>
          <el-descriptions-item label="目标表">{{ detailDialog.row.table_name }}</el-descriptions-item>
          <el-descriptions-item label="已导入行数">{{ formatNum(detailDialog.row.loaded_rows) }}</el-descriptions-item>
          <el-descriptions-item label="错误行数">{{ detailDialog.row.error_rows }}</el-descriptions-item>
          <el-descriptions-item label="接收字节">{{ formatBytes(detailDialog.row.received_bytes) }}</el-descriptions-item>
          <el-descriptions-item label="已提交批次">{{ detailDialog.row.committed_tasks }}</el-descriptions-item>
          <el-descriptions-item label="消费位点" :span="2">
            <code>{{ JSON.stringify(detailDialog.row.progress || {}) }}</code>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailDialog.row.reason" label="状态变更原因" :span="2">
            <span class="err-txt">{{ detailDialog.row.reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  controlDorisRoutineLoad,
  createDorisRoutineLoad,
  executeDorisSql,
  getDorisOverview,
  getRealtimeOverview,
  listDorisRoutineLoads,
  listDorisTables,
  listKafkaTopics,
  previewDorisTable
} from '@/api'

const router = useRouter()

const loading = ref(false)
const autoRefresh = ref(true)
const activeTab = ref('loads')
const dorisOverview = ref({})
const rtOverview = ref({})
const kafkaTopics = ref([])
const routineLoads = ref([])
const tables = ref([])

const selectedTable = ref('')
const tablePreview = ref(null)
const previewLoading = ref(false)
const tableViewMode = ref('data')

const sqlInput = ref('SELECT channel, COUNT(DISTINCT order_id) AS orders, SUM(pay_amount) AS gmv_pay, SUM(refund_amount) AS refund_amt\nFROM dwd_order_item_rt\nGROUP BY channel\nORDER BY gmv_pay DESC')
const sqlRunning = ref(false)
const sqlError = ref('')
const sqlResult = ref(null)

const sqlPresets = [
  {
    label: '各渠道实时 GMV 与退款',
    sql: 'SELECT channel, COUNT(DISTINCT order_id) AS order_cnt, SUM(pay_amount) AS gmv_pay, SUM(refund_amount) AS refund_amt, SUM(pay_amount) - SUM(refund_amount) AS gmv_net\nFROM dwd_order_item_rt\nWHERE status IN (\'paid\', \'refunded\')\nGROUP BY channel\nORDER BY gmv_net DESC'
  },
  {
    label: '最新 20 条订单明细',
    sql: 'SELECT * FROM dwd_order_item_rt ORDER BY order_time DESC LIMIT 20'
  },
  {
    label: '最新退款记录',
    sql: 'SELECT * FROM dwd_refund_record_rt ORDER BY refund_time DESC LIMIT 20'
  },
  {
    label: '最新物流发货状态',
    sql: 'SELECT * FROM dwd_shipment_rt ORDER BY id DESC LIMIT 20'
  }
]

const createDialog = reactive({
  visible: false,
  submitting: false,
  form: {
    job_name: '',
    topic: '',
    table_name: '',
    format: 'debezium-json',
    offset: 'OFFSET_BEGINNING',
    desired_concurrent_number: 1,
    max_error_number: 100
  }
})

const detailDialog = reactive({
  visible: false,
  row: null
})

let timer = null

function formatNum(n) {
  return Number(n || 0).toLocaleString('zh-CN')
}

function formatBytes(b) {
  const n = Number(b || 0)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

function formatProgress(prog) {
  if (!prog || !Object.keys(prog).length) return '-'
  return Object.entries(prog).map(([p, off]) => `P${p}:${off}`).join(' ')
}

async function loadTables() {
  try {
    const res = await listDorisTables()
    tables.value = res.data || []
    if (!selectedTable.value && tables.value.length) {
      selectTable(tables.value[0].name)
    }
  } catch {
    tables.value = []
  }
}

async function loadAll(silent = false) {
  if (!silent) loading.value = true
  try {
    const [dOv, rOv, topicsRes] = await Promise.all([
      getDorisOverview(),
      getRealtimeOverview(),
      listKafkaTopics().catch(() => ({ data: [] }))
    ])
    dorisOverview.value = dOv.data || {}
    rtOverview.value = rOv.data || {}
    kafkaTopics.value = topicsRes.data || []

    if (dorisOverview.value.connected) {
      const [rlRes, tblRes] = await Promise.all([
        listDorisRoutineLoads().catch(() => ({ data: [] })),
        listDorisTables().catch(() => ({ data: [] }))
      ])
      routineLoads.value = rlRes.data || []
      tables.value = tblRes.data || []
      if (!selectedTable.value && tables.value.length) {
        selectTable(tables.value[0].name)
      }
    }
  } catch (e) {
    if (!silent) ElMessage.error(e?.message || '加载 Doris 状态失败')
  } finally {
    loading.value = false
  }
}

async function selectTable(name) {
  if (!name) return
  selectedTable.value = name
  previewLoading.value = true
  try {
    const res = await previewDorisTable(name, 20)
    tablePreview.value = res.data || null
  } catch (e) {
    ElMessage.error(e?.message || '加载表预览失败')
  } finally {
    previewLoading.value = false
  }
}

function jumpToTable(tableName) {
  activeTab.value = 'tables'
  selectTable(tableName)
}

function openInConsole(tableName) {
  sqlInput.value = `SELECT * FROM ${tableName} LIMIT 20`
  activeTab.value = 'console'
  runSql()
}

function openCreateDialog() {
  createDialog.form = {
    job_name: '',
    topic: kafkaTopics.value[0]?.name || '',
    table_name: tables.value[0]?.name || '',
    format: 'debezium-json',
    offset: 'OFFSET_BEGINNING',
    desired_concurrent_number: 1,
    max_error_number: 100
  }
  createDialog.visible = true
}

async function submitCreateLoad() {
  const f = createDialog.form
  if (!f.job_name || !f.topic || !f.table_name) {
    ElMessage.warning('请填写作业名、Kafka 主题与目标 Doris 表')
    return
  }
  createDialog.submitting = true
  try {
    await createDorisRoutineLoad(f)
    ElMessage.success('Routine Load 作业已创建并启动')
    createDialog.visible = false
    await loadAll()
  } catch (e) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    createDialog.submitting = false
  }
}

async function onControlLoad(row, action) {
  const labels = { pause: '暂停', resume: '恢复', stop: '永久停止' }
  try {
    await ElMessageBox.confirm(
      `确定要${labels[action]}入库作业「${row.name}」吗？${action === 'stop' ? '停止后无法恢复，只能重建。' : ''}`,
      '确认操作',
      { type: action === 'stop' ? 'warning' : 'info' }
    )
    await controlDorisRoutineLoad(row.name, action)
    ElMessage.success(`作业已${labels[action]}`)
    await loadAll()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e?.message || '操作失败')
  }
}

function openLoadDetail(row) {
  detailDialog.row = row
  detailDialog.visible = true
}

function applyPreset(sql) {
  sqlInput.value = sql
  runSql()
}

async function runSql() {
  sqlError.value = ''
  sqlRunning.value = true
  try {
    const res = await executeDorisSql(sqlInput.value)
    sqlResult.value = res.data || null
  } catch (e) {
    sqlError.value = e?.message || 'SQL 执行失败'
    sqlResult.value = null
  } finally {
    sqlRunning.value = false
  }
}

function setupTimer() {
  if (timer) clearInterval(timer)
  timer = null
  if (autoRefresh.value) {
    timer = setInterval(() => loadAll(true), 10000)
  }
}

watch(autoRefresh, setupTimer)

onMounted(async () => {
  await loadAll()
  setupTimer()
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.doris-page { display: flex; flex-direction: column; gap: 14px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; color: #0f172a; }
.sub { margin: 0; font-size: 13px; color: #64748b; }
.head-ops { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.auto-box { display: flex; align-items: center; gap: 6px; padding: 4px 10px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 12px; color: #475569; }

.pipeline-strip { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr auto 1.25fr; align-items: center; gap: 10px; }
.pipe-node {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.pipe-node:hover { border-color: #93c5fd; transform: translateY(-1px); }
.pipe-node.active { border-color: #2563eb; background: #f8fbff; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1); }
.pn-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.pn-badge { font-size: 11.5px; font-weight: 600; padding: 2px 7px; border-radius: 6px; }
.pn-badge.mysql { background: #eff6ff; color: #1d4ed8; }
.pn-badge.flink { background: #fef3c7; color: #b45309; }
.pn-badge.kafka { background: #f3e8ff; color: #7e22ce; }
.pn-badge.doris { background: #ecfdf5; color: #047857; }
.pn-dot { width: 8px; height: 8px; border-radius: 50%; }
.pn-dot.ok { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.22); }
.pn-dot.off { background: #94a3b8; }
.pn-dot.err { background: #ef4444; }
.pn-val { font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 2px; }
.pn-desc { font-size: 12px; color: #64748b; }
.pipe-arrow { font-size: 18px; color: #94a3b8; font-weight: 700; text-align: center; }

.cluster-bar, .main-card { border-radius: 10px; }
.cluster-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.c-item { display: flex; flex-direction: column; gap: 5px; }
.c-k { font-size: 12px; color: #64748b; }
.c-v { font-size: 13px; color: #0f172a; }
.ok-txt { color: #16a34a; }
.warn-txt { color: #d97706; }
.err-txt { color: #dc2626; }

.flow-cell { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.flow-cell .arrow { color: #94a3b8; font-weight: 700; }
.clickable { cursor: pointer; }

.state-pill { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.state-pill .dot { width: 7px; height: 7px; border-radius: 50%; }
.state-pill.running { background: #ecfdf5; color: #15803d; }
.state-pill.running .dot { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.24); }
.state-pill.paused { background: #fffbeb; color: #b45309; }
.state-pill.paused .dot { background: #f59e0b; }
.state-pill.stopped, .state-pill.cancelled { background: #f1f5f9; color: #475569; }
.state-pill.stopped .dot, .state-pill.cancelled .dot { background: #94a3b8; }

.table-explorer { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 14px; min-height: 440px; }
.te-sidebar { border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; background: #f8fafc; }
.te-side-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-size: 13px; color: #0f172a; }
.te-item { padding: 9px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; border: 1px solid transparent; transition: all 0.12s; }
.te-item:hover { background: #fff; border-color: #cbd5e1; }
.te-item.active { background: #eff6ff; border-color: #93c5fd; }
.te-name { font-size: 13px; font-weight: 600; color: #0f172a; margin-bottom: 4px; word-break: break-all; }
.te-meta { display: flex; justify-content: space-between; align-items: center; font-size: 11.5px; color: #64748b; }

.te-main { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; background: #fff; }
.te-main-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 10px; flex-wrap: wrap; }
.te-title { font-size: 15px; color: #0f172a; }
.te-main-ops { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.sql-presets { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.sql-editor-wrap :deep(.el-textarea__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
  font-size: 13.5px !important;
  line-height: 1.6 !important;
  background: #0f172a !important;
  color: #e2e8f0 !important;
  border-color: #1e293b !important;
  caret-color: #e2e8f0;
}
.sql-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; gap: 10px; flex-wrap: wrap; }
.sql-result { margin-top: 14px; }
.sr-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; gap: 10px; flex-wrap: wrap; }

.inline-nums { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.muted { font-size: 12px; color: #94a3b8; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: #334155; }

@media (max-width: 1100px) {
  .pipeline-strip { grid-template-columns: 1fr; }
  .pipe-arrow { display: none; }
  .cluster-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .table-explorer { grid-template-columns: 1fr; }
}
</style>
