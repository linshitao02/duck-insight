<template>
  <div>
    <div class="page-head">
      <div>
        <h2>DAG 编排</h2>
        <p>以列表管理编排。新建后拖入数据集、清洗规则、模型训练等组件，连线后可手动运行或开启定时。</p>
      </div>
      <el-button type="primary" @click="$router.push('/dag/new')">新建编排</el-button>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>编排列表</span>
          <div class="head-right">
            <el-input
              v-model="keyword"
              clearable
              placeholder="名称 / 说明 / 场景"
              style="width: 240px"
              @keyup.enter="search"
            />
            <el-button size="small" type="primary" @click="search">查询</el-button>
            <el-button size="small" @click="loadList">刷新</el-button>
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
        :data="graphs"
        row-key="id"
        stripe
        highlight-current-row
        empty-text="还没有编排，点击右上角新建"
        @selection-change="onSelectionChange"
        @row-click="onRowClick"
      >
        <el-table-column type="selection" width="42" reserve-selection />
        <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="场景" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ sceneText(row.scenario_code) }}</template>
        </el-table-column>
        <el-table-column label="节点" width="72">
          <template #default="{ row }">{{ nodeCount(row) }}</template>
        </el-table-column>
        <el-table-column label="最近运行" min-width="180">
          <template #default="{ row }">
            <div v-if="row.last_run" class="last-run">
              <el-tag :type="runType(row.last_run.status)" size="small">{{ runText(row.last_run.status) }}</el-tag>
              <span>{{ fmtTime(row.last_run.create_time) }}</span>
            </div>
            <span v-else class="muted">尚未执行</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="168">
          <template #default="{ row }">{{ fmtTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="368" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openGraph(row)">编辑</el-button>
            <el-button link type="primary" @click.stop="openClone(row)">复制</el-button>
            <el-button link type="success" :loading="runningId === row.id" @click.stop="runOne(row)">运行</el-button>
            <el-button link type="primary" @click.stop="openLogs(row)">日志</el-button>
            <el-button link type="primary" @click.stop="openSchedule(row)">
              定时{{ row.schedule_enabled ? '·开' : '' }}
            </el-button>
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

    <el-dialog v-model="cloneDlg.visible" title="复制编排" width="480px" destroy-on-close>
      <el-form label-width="72px" @submit.prevent="submitClone">
        <el-form-item label="名称" required>
          <el-input v-model="cloneDlg.name" maxlength="128" show-word-limit placeholder="新编排名称" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="cloneDlg.description" type="textarea" :rows="3" maxlength="512" show-word-limit placeholder="用途说明，可留空" />
        </el-form-item>
        <el-form-item label="场景">
          <el-select
            v-model="cloneDlg.scenario"
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="下拉选择，或输入新场景后回车"
            style="width: 100%"
          >
            <el-option v-for="s in scenarios" :key="s.code" :label="s.name" :value="s.code" />
          </el-select>
          <p class="muted scene-hint">可选择已有场景，也可直接输入新名称；保存后下次下拉会出现。</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cloneDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="cloneDlg.saving" @click="submitClone">复制</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sched.visible" title="定时配置" width="420px" destroy-on-close>
      <p class="sched-name">{{ sched.name }}</p>
      <el-form label-width="88px">
        <el-form-item label="执行频率">
          <el-select v-model="sched.kind" style="width: 100%">
            <el-option v-for="opt in kindOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用定时">
          <el-switch v-model="sched.enabled" inline-prompt active-text="开" inactive-text="关" />
        </el-form-item>
      </el-form>
      <p class="muted">
        {{ sched.enabled && sched.kind !== 'none'
          ? `保存后按「${kindLabel(sched.kind)}」自动运行`
          : '关闭后仅能手动运行' }}
      </p>
      <template #footer>
        <el-button @click="sched.visible = false">取消</el-button>
        <el-button type="primary" :loading="sched.saving" @click="saveSchedule">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="logs.visible" :title="`运行日志 · ${logs.name}`" width="820px" destroy-on-close>
      <el-table
        class="run-table"
        :data="logs.runs"
        stripe
        highlight-current-row
        row-key="id"
        :current-row-key="logs.detail?.id"
        max-height="240"
        empty-text="还没有运行记录"
        @row-click="pickRun"
      >
        <el-table-column prop="id" label="#" width="70" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="runType(row.status)" size="small">{{ runText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发" width="90">
          <template #default="{ row }">{{ row.trigger_source || '-' }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">{{ row.duration_sec != null ? `${row.duration_sec}s` : '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ fmtTime(row.create_time) }}</template>
        </el-table-column>
      </el-table>
      <ListPager
        v-model:page="logs.page"
        v-model:pageSize="logs.pageSize"
        :total="logs.total"
        :page-sizes="[10, 20, 50]"
        @change="loadRuns"
      />
      <transition name="log-pop">
        <div v-if="logs.detail" class="log-detail">
          <p class="log-head">
            运行 #{{ logs.detail.id }}
            <el-tag :type="runType(logs.detail.status)" size="small">{{ runText(logs.detail.status) }}</el-tag>
          </p>
          <p v-if="logs.detail.error_message" class="log-err">{{ logs.detail.error_message }}</p>
          <el-table v-if="logs.detail.nodes?.length" :data="logs.detail.nodes" size="small" class="node-log">
            <el-table-column prop="node_id" label="节点" width="110" />
            <el-table-column prop="node_type" label="类型" min-width="140" />
            <el-table-column prop="status" label="状态" width="80" />
            <el-table-column prop="duration_sec" label="秒" width="70" />
            <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip />
          </el-table>
          <pre>{{ logs.detail.log_text || '无文本日志' }}</pre>
          <pre v-if="logs.detail.result?.llm_report" class="llm-pre">{{ logs.detail.result.llm_report }}</pre>
        </div>
      </transition>
      <p v-if="!logs.detail" class="muted">点击上方某条运行记录，下方会展开节点日志与大模型输出。</p>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cloneGraph, deleteGraph, deleteGraphs, getGraphRun, listGraphs, listGraphRuns, patchGraphSchedule, runGraph } from '@/api'
import { getScenarios } from '@/api/user'
import ListPager from '@/components/ListPager.vue'
import { useUserStore } from '@/stores/user'
import { unwrapPage } from '@/utils/paging'

const router = useRouter()
const userStore = useUserStore()
const tableRef = ref()
const graphs = ref([])
const picked = ref([])
const removing = ref(false)
const scenarios = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const keyword = ref('')
const runningId = ref(null)
const sched = reactive({
  visible: false,
  saving: false,
  id: null,
  name: '',
  kind: 'none',
  enabled: false
})
const logs = reactive({
  visible: false,
  name: '',
  graphId: null,
  runs: [],
  detail: null,
  page: 1,
  pageSize: 10,
  total: 0
})
const cloneDlg = reactive({
  visible: false,
  saving: false,
  sourceId: null,
  name: '',
  description: '',
  scenario: ''
})

const kindOptions = [
  { value: 'none', label: '不定时' },
  { value: 'hourly', label: '每小时' },
  { value: 'every_6h', label: '每 6 小时' },
  { value: 'daily', label: '每天 8:00' }
]

const nodeCount = (row) => Number(row?.node_count ?? (row?.graph?.nodes || []).length)
const sceneFallback = {
  store_sales: '商店销售',
  power_trading: '电力交易分析',
  generic: '通用表格分析'
}
const sceneText = (code) => {
  const hit = scenarios.value.find(s => s.code === code)
  return hit?.name || sceneFallback[code] || code || '-'
}

const loadScenarios = async () => {
  const res = await getScenarios()
  scenarios.value = res.data || []
  userStore.setScenarios(scenarios.value)
}

const runText = (s) => ({ success: '成功', failed: '失败', running: '运行中', pending: '排队' }[s] || s || '-')
const runType = (s) => ({ success: 'success', failed: 'danger', running: 'warning', pending: 'info' }[s] || 'info')

const fmtTime = (v) => {
  if (!v) return '-'
  const s = String(v).replace('T', ' ')
  return s.slice(0, 16)
}

const kindLabel = (kind) => kindOptions.find(o => o.value === (kind || 'none'))?.label || '不定时'

const loadList = async () => {
  const packed = unwrapPage(await listGraphs({
    page: page.value,
    page_size: pageSize.value,
    keyword: keyword.value.trim() || undefined
  }))
  graphs.value = packed.items
  total.value = packed.total
  if (!graphs.value.length && total.value > 0 && page.value > 1) {
    page.value -= 1
    return loadList()
  }
}

const search = () => {
  page.value = 1
  loadList()
}

const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  loadList()
}

const onSelectionChange = (rows) => {
  picked.value = rows || []
}

const openGraph = (row) => {
  if (!row?.id) return
  router.push(`/dag/${row.id}`)
}

const onRowClick = (row, column) => {
  if (column?.type === 'selection') return
  openGraph(row)
}

const clearPicked = () => {
  picked.value = []
  tableRef.value?.clearSelection?.()
}

const openClone = async (row) => {
  if (!row?.id) return
  await loadScenarios()
  cloneDlg.sourceId = row.id
  cloneDlg.name = `${row.name || '未命名编排'} 副本`
  cloneDlg.description = row.description || ''
  cloneDlg.scenario = row.scenario_code || 'generic'
  cloneDlg.visible = true
}

const submitClone = async () => {
  const name = (cloneDlg.name || '').trim()
  if (!name) return ElMessage.warning('请填写名称')
  if (!cloneDlg.sourceId) return
  const scene = (cloneDlg.scenario || '').trim()
  if (!scene) return ElMessage.warning('请选择或输入场景')
  cloneDlg.saving = true
  try {
    await cloneGraph(cloneDlg.sourceId, {
      name,
      description: cloneDlg.description || '',
      scenario_code: scene
    })
    ElMessage.success('已复制编排')
    cloneDlg.visible = false
    page.value = 1
    await Promise.all([loadScenarios(), loadList()])
  } finally {
    cloneDlg.saving = false
  }
}

const openSchedule = (row) => {
  sched.id = row.id
  sched.name = row.name
  sched.kind = row.schedule_kind || 'none'
  sched.enabled = !!row.schedule_enabled
  sched.visible = true
}

const loadRuns = async () => {
  if (!logs.graphId) return
  const packed = unwrapPage(await listGraphRuns({
    graph_id: logs.graphId,
    page: logs.page,
    page_size: logs.pageSize
  }))
  logs.runs = packed.items
  logs.total = packed.total
  if (!logs.runs.length && logs.total > 0 && logs.page > 1) {
    logs.page -= 1
    return loadRuns()
  }
  if (logs.detail && !logs.runs.some(r => r.id === logs.detail.id)) {
    logs.detail = null
  }
}

const openLogs = async (row) => {
  logs.name = row.name
  logs.graphId = row.id
  logs.detail = null
  logs.page = 1
  logs.visible = true
  await loadRuns()
}

const pickRun = async (row) => {
  if (!row?.id) return
  const res = await getGraphRun(row.id)
  logs.detail = res.data || row
}

const saveSchedule = async () => {
  let kind = sched.kind || 'none'
  let enabled = !!sched.enabled
  if (enabled && kind === 'none') kind = 'daily'
  if (kind === 'none') enabled = false
  sched.saving = true
  try {
    await patchGraphSchedule(sched.id, { schedule_kind: kind, schedule_enabled: enabled })
    ElMessage.success('定时已更新')
    sched.visible = false
    await loadList()
  } finally {
    sched.saving = false
  }
}

const runOne = async (row) => {
  runningId.value = row.id
  try {
    const res = await runGraph(row.id)
    ElMessage.success(res.data?.status === 'success' ? '编排执行完成' : '已返回运行结果')
    await loadList()
  } finally {
    runningId.value = null
  }
}

const removeOne = async (row) => {
  try {
    await ElMessageBox.confirm(`删除编排「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteGraph(row.id)
  ElMessage.success('已删除')
  clearPicked()
  await loadList()
}

const removePicked = async () => {
  const rows = picked.value.filter(r => r?.id)
  if (!rows.length) return ElMessage.warning('请先勾选要删除的编排')
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${rows.length} 条编排？定时也会一并关闭。`,
      '批量删除',
      { type: 'warning' }
    )
  } catch {
    return
  }
  removing.value = true
  try {
    const res = await deleteGraphs(rows.map(r => r.id))
    ElMessage.success(res.message || `已删除 ${res.data?.deleted || rows.length} 条`)
    clearPicked()
    await loadList()
  } finally {
    removing.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadList(), loadScenarios()])
})
</script>

<style scoped>
.last-run { display: flex; align-items: center; gap: 8px; }
.head-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.muted { color: var(--muted); font-size: 12px; }
.scene-hint { margin: 6px 0 0; }
.sched-name { font-weight: 600; margin: 0 0 14px; }
.log-detail { margin-top: 14px; display: grid; gap: 8px; }
.log-head { display: flex; align-items: center; gap: 8px; margin: 0; font-weight: 600; }
.log-err { color: #b42318; font-size: 13px; margin: 0; }
.node-log { margin: 4px 0; }
.log-detail pre {
  white-space: pre-wrap;
  font-size: 12px;
  background: var(--panel-soft);
  padding: 10px;
  border-radius: 8px;
  max-height: 240px;
  overflow: auto;
  margin: 0;
}
.llm-pre { max-height: 280px; }
.run-table { cursor: pointer; }
.log-pop-enter-active,
.log-pop-leave-active { transition: opacity .18s ease, transform .18s ease; }
.log-pop-enter-from,
.log-pop-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
