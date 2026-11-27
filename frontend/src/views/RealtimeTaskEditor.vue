<template>
  <div class="ed-page" v-loading="loading">
    <div class="ed-top">
      <div class="ed-title">
        <el-button link @click="router.push('/realtime/tasks')">← 返回列表</el-button>
        <h2>{{ taskId ? (form.name || '同步任务配置') : '新建实时同步任务' }}</h2>
        <el-tag :type="form.mode === 'script' ? 'warning' : 'primary'" size="small">
          {{ form.mode === 'script' ? '脚本模式' : '向导模式' }}
        </el-tag>
        <el-tag v-if="taskId" :type="statusType(form.job_status)" size="small">
          {{ statusLabel(form.job_status) }}
        </el-tag>
      </div>
      <div class="ed-ops">
        <el-button
          v-if="taskId && form.mode === 'wizard'"
          type="warning"
          plain
          @click="onConvertScript"
        >
          转为脚本模式
        </el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
        <el-button
          v-if="taskId && form.job_status !== 'running'"
          type="success"
          :loading="submitting"
          @click="onSubmit"
        >
          {{ form.last_checkpoint ? '从断点续跑' : '提交运行' }}
        </el-button>
        <el-button v-if="taskId && form.job_status === 'running'" type="danger" plain @click="onStop">
          停止作业
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="form.last_checkpoint || form.flink_job_id || form.last_error"
      :type="form.last_error ? 'error' : 'info'"
      :closable="false"
      class="meta-alert"
    >
      <template #title>
        <span v-if="form.flink_job_id">Job ID：<code>{{ form.flink_job_id }}</code></span>
        <span v-if="form.last_checkpoint" style="margin-left: 16px">最近检查点：<code>{{ form.last_checkpoint }}</code></span>
        <div v-if="form.last_error" style="margin-top: 4px">最近错误：{{ form.last_error }}</div>
      </template>
    </el-alert>

    <!-- 脚本模式（对齐 Taier Flink SQL 脚本模式） -->
    <el-card v-if="form.mode === 'script'" shadow="never" class="panel">
      <div class="script-head">
        <div>
          <strong>Flink SQL 脚本编辑器</strong>
          <span class="muted">（已转为脚本模式，修改后不再被向导覆盖；支持多表 EXECUTE STATEMENT SET）</span>
        </div>
        <div class="basic-inline">
          <el-input v-model="form.name" placeholder="任务名称" style="width: 220px" />
          <el-input v-model="form.description" placeholder="任务描述" style="width: 260px" />
        </div>
      </div>
      <div class="sql-editor-wrap">
        <el-input
          v-model="form.script_sql"
          type="textarea"
          :rows="22"
          placeholder="在此编写 Flink SQL（CREATE TABLE ... WITH ('connector'='mysql-cdc') / INSERT INTO ...）"
        />
      </div>
    </el-card>

    <!-- 向导模式（对齐 Taier 实时采集 4 步向导 + DataWorks 多表同步） -->
    <template v-else>
      <el-card shadow="never" class="panel">
        <el-steps :active="step" finish-status="success" align-center>
          <el-step title="1. 数据来源" description="选择 MySQL 并勾选多张表" />
          <el-step title="2. 目标主题" description="按规则生成 Kafka 主题" />
          <el-step title="3. 通道控制" description="并行度、启动位点与断点" />
          <el-step title="4. 预览保存" description="查看生成的 Flink SQL" />
        </el-steps>
      </el-card>

      <!-- Step 1: 数据来源 -->
      <el-card v-if="step === 0" shadow="never" class="panel">
        <el-form label-width="124px" class="w-form">
          <el-form-item label="任务名称" required>
            <el-input v-model="form.name" placeholder="例如：电商订单多表实时同步" style="max-width: 420px" />
          </el-form-item>
          <el-form-item label="任务描述">
            <el-input v-model="form.description" placeholder="可选，说明同步范围与用途" style="max-width: 420px" />
          </el-form-item>
          <el-form-item label="MySQL 数据源" required>
            <el-select v-model="form.source_id" placeholder="选择已配置的 MySQL 数据源" style="width: 320px" @change="onSourceChange">
              <el-option v-for="s in sources" :key="s.id" :label="`${s.name} (${s.host}:${s.port})`" :value="s.id" />
            </el-select>
            <el-button link type="primary" style="margin-left: 10px" @click="router.push('/datasource')">去配置数据源</el-button>
          </el-form-item>
          <el-form-item label="来源数据库" required>
            <el-select v-model="form.database_name" placeholder="选择数据库" style="width: 320px" :loading="loadingDbs" @change="onDatabaseChange">
              <el-option v-for="db in databases" :key="db" :label="db" :value="db" />
            </el-select>
          </el-form-item>
          <el-form-item label="勾选同步表" required>
            <div class="table-picker" v-loading="loadingTables">
              <div v-if="!availableTables.length" class="muted">请先选择数据源和数据库</div>
              <el-checkbox-group v-else v-model="selectedTableNames">
                <el-checkbox v-for="t in availableTables" :key="t.table" :label="t.table">
                  {{ t.table }}
                  <span class="muted" v-if="t.rows != null">（约 {{ t.rows }} 行）</span>
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </el-form-item>
        </el-form>
        <div class="step-foot">
          <el-button type="primary" :loading="loadingSchema" @click="goStep1">下一步：配置目标主题</el-button>
        </div>
      </el-card>

      <!-- Step 2: 目标 Kafka 主题 -->
      <el-card v-if="step === 1" shadow="never" class="panel">
        <div class="rule-bar">
          <span>主题命名规则：</span>
          <el-input v-model="form.topic_prefix" style="width: 140px" size="small" />
          <span class="muted">_库名_表名（只使用下划线，避免点号冲突）</span>
          <el-button size="small" @click="applyTopicRule">按规则重算全部</el-button>
        </div>

        <el-table :data="form.tables" style="margin-top: 12px">
          <el-table-column prop="table" label="MySQL 来源表" min-width="160" />
          <el-table-column label="主键" width="150">
            <template #default="{ row }">
              <code>{{ (row.primary_keys || []).join(', ') || '自动取首列' }}</code>
            </template>
          </el-table-column>
          <el-table-column label="字段数" width="90">
            <template #default="{ row }">{{ (row.columns || []).length }}</template>
          </el-table-column>
          <el-table-column label="目标 Kafka 主题" min-width="260">
            <template #default="{ row }">
              <el-input v-model="row.topic" size="small" placeholder="cdc_db_table" />
            </template>
          </el-table-column>
          <el-table-column label="分区数" width="110">
            <template #default="{ row }">
              <el-input-number v-model="row.partitions" :min="1" :max="16" size="small" />
            </template>
          </el-table-column>
        </el-table>

        <div class="step-foot">
          <el-button @click="step = 0">上一步</el-button>
          <el-button type="primary" @click="step = 2">下一步：通道控制</el-button>
        </div>
      </el-card>

      <!-- Step 3: 通道控制 -->
      <el-card v-if="step === 2" shadow="never" class="panel">
        <el-form label-width="140px" class="w-form">
          <el-form-item label="并行度">
            <el-input-number v-model="form.channel.parallelism" :min="1" :max="16" />
            <span class="hint">单槽位测试环境保持 1</span>
          </el-form-item>
          <el-form-item label="启动位点">
            <el-radio-group v-model="form.channel.startup_mode">
              <el-radio label="initial">全量快照 + 增量 Binlog（推荐）</el-radio>
              <el-radio label="latest-offset">仅从最新 Binlog 开始</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="Checkpoint 间隔">
            <el-input-number v-model="form.channel.checkpoint_interval_ms" :min="3000" :step="1000" />
            <span class="hint">毫秒，重启后自动从最近检查点续跑</span>
          </el-form-item>
          <el-form-item label="主题副本数">
            <el-input-number v-model="form.channel.topic_replication_factor" :min="1" :max="3" />
            <span class="hint">单节点 Kafka 只能填 1</span>
          </el-form-item>
          <el-form-item label="主题保留天数">
            <el-input-number v-model="form.channel.topic_retention_days" :min="1" :max="90" />
            <span class="hint">提交时写入 Kafka 的 retention.ms</span>
          </el-form-item>
          <el-form-item label="Kafka 地址">
            <el-input v-model="form.channel.kafka_bootstrap" style="max-width: 360px" />
            <span class="hint">Flink 容器内地址，默认 kafka:9092</span>
          </el-form-item>
          <el-form-item label="Server ID 区间">
            <el-input v-model="form.channel.server_id_range" style="max-width: 220px" />
            <span class="hint">每条同步任务使用独立区间，避免 Binlog 冲突</span>
          </el-form-item>
          <el-form-item label="容器内 MySQL 主机">
            <el-input v-model="form.channel.mysql_host_override" placeholder="留空则使用数据源主机名（如容器内填 mysql）" style="max-width: 360px" />
          </el-form-item>
        </el-form>
        <div class="step-foot">
          <el-button @click="step = 1">上一步</el-button>
          <el-button type="primary" :loading="previewing" @click="goStep3">下一步：预览 Flink SQL</el-button>
        </div>
      </el-card>

      <!-- Step 4: 预览保存 -->
      <el-card v-if="step === 3" shadow="never" class="panel">
        <div class="preview-head">
          <div>
            <strong>生成的 Flink SQL（只读预览）</strong>
            <span class="muted">多张表自动合并为一条 EXECUTE STATEMENT SET 作业，共用检查点。</span>
          </div>
          <el-button size="small" @click="refreshPreview" :loading="previewing">重新生成</el-button>
        </div>
        <pre class="sql-preview">{{ form.generated_sql }}</pre>
        <div class="step-foot">
          <el-button @click="step = 2">上一步</el-button>
          <el-button type="primary" :loading="saving" @click="onSave">保存任务</el-button>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  convertRealtimeScript,
  fetchRealtimeSourceSchema,
  getRealtimeTask,
  listDataSources,
  listSourceDatabases,
  listSourceTables,
  previewRealtimeSql,
  saveRealtimeTask,
  stopRealtimeTask,
  submitRealtimeTask
} from '@/api'

const route = useRoute()
const router = useRouter()
const taskId = computed(() => (route.params.id ? Number(route.params.id) : null))

const loading = ref(false)
const saving = ref(false)
const submitting = ref(false)
const previewing = ref(false)
const loadingDbs = ref(false)
const loadingTables = ref(false)
const loadingSchema = ref(false)
const step = ref(0)

const sources = ref([])
const databases = ref([])
const availableTables = ref([])
const selectedTableNames = ref([])

const form = reactive({
  name: '',
  description: '',
  mode: 'wizard',
  source_id: null,
  database_name: '',
  topic_prefix: 'cdc',
  tables: [],
  channel: {
    parallelism: 1,
    checkpoint_interval_ms: 10000,
    startup_mode: 'initial',
    server_id_range: '5410-5414',
    kafka_bootstrap: 'kafka:9092',
    mysql_host_override: '',
    kafka_format: 'debezium-json',
    topic_replication_factor: 1,
    topic_retention_days: 7
  },
  generated_sql: '',
  script_sql: '',
  flink_job_id: '',
  job_status: 'draft',
  last_checkpoint: '',
  last_error: ''
})

const statusLabel = (s) => ({ draft: '草稿', running: '运行中', stopped: '已停止', failed: '失败' }[s] || '草稿')
const statusType = (s) => ({ draft: 'info', running: 'success', stopped: 'warning', failed: 'danger' }[s] || 'info')

const buildTopic = (tbl) => {
  const clean = (v) => String(v || '').trim().replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')
  return `${clean(form.topic_prefix) || 'cdc'}_${clean(form.database_name) || 'db'}_${clean(tbl)}`
}

async function loadSources() {
  const res = await listDataSources({ page: 1, page_size: 100 })
  sources.value = res.data?.items || res.data || []
}

async function onSourceChange(sid) {
  databases.value = []
  availableTables.value = []
  selectedTableNames.value = []
  form.database_name = ''
  if (!sid) return
  loadingDbs.value = true
  try {
    const res = await listSourceDatabases(sid)
    const raw = res.data
    const list = Array.isArray(raw) ? raw : (raw?.items || [])
    databases.value = list.map((d) => (typeof d === 'string' ? d : d.name)).filter(Boolean)
  } catch (e) {
    ElMessage.error(e?.message || '读取数据库失败')
  } finally {
    loadingDbs.value = false
  }
}

async function onDatabaseChange(db) {
  availableTables.value = []
  if (!form.source_id || !db) return
  loadingTables.value = true
  try {
    const res = await listSourceTables(form.source_id, [db])
    const raw = res.data
    const list = Array.isArray(raw) ? raw : (raw?.items || [])
    availableTables.value = list.map((t) => ({
      table: t.table || t.table_name,
      rows: t.rows ?? t.table_rows ?? null
    }))
  } catch (e) {
    ElMessage.error(e?.message || '读取表列表失败')
  } finally {
    loadingTables.value = false
  }
}

async function goStep1() {
  if (!form.name.trim()) return ElMessage.warning('请填写任务名称')
  if (!form.source_id || !form.database_name) return ElMessage.warning('请选择数据源和数据库')
  if (!selectedTableNames.value.length) return ElMessage.warning('请至少勾选一张表')

  loadingSchema.value = true
  try {
    const res = await fetchRealtimeSourceSchema(form.source_id, {
      database_name: form.database_name,
      tables: selectedTableNames.value
    })
    const existingMap = Object.fromEntries((form.tables || []).map((t) => [t.table, t]))
    form.tables = (res.data || []).map((item) => {
      const old = existingMap[item.table] || {}
      return {
        table: item.table,
        primary_keys: item.primary_keys || [],
        columns: item.columns || [],
        topic: old.topic || buildTopic(item.table),
        partitions: old.partitions || 1
      }
    })
    step.value = 1
  } catch (e) {
    ElMessage.error(e?.message || '读取表结构失败')
  } finally {
    loadingSchema.value = false
  }
}

function applyTopicRule() {
  form.tables = form.tables.map((t) => ({ ...t, topic: buildTopic(t.table) }))
}

async function refreshPreview() {
  previewing.value = true
  try {
    const res = await previewRealtimeSql({
      id: taskId.value,
      name: form.name,
      source_id: form.source_id,
      database_name: form.database_name,
      tables: form.tables,
      channel: form.channel
    })
    form.generated_sql = res.data?.sql || ''
  } catch (e) {
    ElMessage.error(e?.message || '生成 SQL 失败')
  } finally {
    previewing.value = false
  }
}

async function goStep3() {
  await refreshPreview()
  step.value = 3
}

async function onSave() {
  if (!form.name.trim()) return ElMessage.warning('请填写任务名称')
  saving.value = true
  try {
    const res = await saveRealtimeTask({ ...form }, taskId.value)
    ElMessage.success('同步任务已保存')
    const saved = res.data
    if (!taskId.value && saved?.id) {
      router.replace(`/realtime/tasks/${saved.id}`)
    } else if (saved) {
      Object.assign(form, saved)
    }
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onConvertScript() {
  try {
    await ElMessageBox.confirm(
      '转为脚本模式后，你可以直接编辑 Flink SQL；此后向导配置将不再覆盖脚本。是否继续？',
      '转为脚本模式',
      { type: 'warning' }
    )
    const res = await convertRealtimeScript(taskId.value)
    Object.assign(form, res.data || {})
    ElMessage.success('已转为脚本模式')
  } catch {}
}

async function onSubmit() {
  submitting.value = true
  try {
    const res = await submitRealtimeTask(taskId.value, true)
    Object.assign(form, res.data || {})
    ElMessage.success('作业已提交')
  } catch (e) {
    ElMessage.error(e?.message || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function onStop() {
  try {
    const res = await stopRealtimeTask(taskId.value)
    Object.assign(form, res.data || {})
    ElMessage.success('作业已停止')
  } catch (e) {
    ElMessage.error(e?.message || '停止失败')
  }
}

async function loadDetail() {
  if (!taskId.value) return
  loading.value = true
  try {
    const res = await getRealtimeTask(taskId.value)
    const data = res.data || {}
    Object.assign(form, data)
    selectedTableNames.value = (data.tables || []).map((t) => t.table)
    if (data.source_id) {
      const dbs = await listSourceDatabases(data.source_id)
      const rawDbs = dbs.data
      const dbList = Array.isArray(rawDbs) ? rawDbs : (rawDbs?.items || [])
      databases.value = dbList.map((d) => (typeof d === 'string' ? d : d.name)).filter(Boolean)
      if (data.database_name) {
        const tbls = await listSourceTables(data.source_id, [data.database_name])
        const rawTbls = tbls.data
        const list = Array.isArray(rawTbls) ? rawTbls : (rawTbls?.items || [])
        availableTables.value = list.map((t) => ({
          table: t.table || t.table_name,
          rows: t.rows ?? t.table_rows ?? null
        }))
      }
    }
    if (data.generated_sql && data.mode === 'wizard') {
      step.value = 3
    }
  } catch (e) {
    ElMessage.error(e?.message || '加载任务失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadSources()
  await loadDetail()
})
</script>

<style scoped>
.ed-page { display: flex; flex-direction: column; gap: 14px; }
.ed-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.ed-title { display: flex; align-items: center; gap: 10px; }
.ed-title h2 { margin: 0; font-size: 18px; color: #0f172a; }
.ed-ops { display: flex; gap: 8px; }
.meta-alert { border-radius: 10px; }
.panel { border-radius: 10px; }
.w-form { max-width: 760px; }
.table-picker { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; max-height: 260px; overflow: auto; width: 100%; }
.table-picker :deep(.el-checkbox) { display: block; margin-bottom: 6px; }
.rule-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.step-foot { margin-top: 18px; display: flex; justify-content: flex-end; gap: 8px; }
.hint { margin-left: 10px; font-size: 12px; color: #64748b; }
.muted { font-size: 12px; color: #94a3b8; }
.preview-head, .script-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 12px; flex-wrap: wrap; }
.basic-inline { display: flex; gap: 8px; flex-wrap: wrap; }
.sql-preview { background: #0f172a; color: #e2e8f0; padding: 14px; border-radius: 8px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; line-height: 1.55; overflow: auto; max-height: 480px; margin: 0; }
.sql-editor-wrap { width: 100%; }
.sql-editor-wrap :deep(.el-textarea__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
  font-size: 13.5px !important;
  line-height: 1.6 !important;
  background: #0f172a !important;
  color: #e2e8f0 !important;
  border-color: #1e293b !important;
  caret-color: #e2e8f0;
  white-space: pre;
  overflow: auto;
  tab-size: 2;
}
.sql-editor-wrap :deep(.el-textarea__inner::placeholder) { color: #64748b !important; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
</style>
