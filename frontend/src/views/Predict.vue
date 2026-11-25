<template>
  <div>
    <div class="page-head">
      <div>
        <h2>数据预测</h2>
        <p>可手填、Excel 导入，或从数据表 / 逻辑数据集 / 数据源库表抽若干行自动填充特征。类别列填训练时的原始值（如中文站点名），数值填业务原值，系统会套用训练保存的 LabelEncoder / Scaler。可选 LLM + RAG 对结果做业务解读，每次预测都会记录到「模型预测记录」。</p>
      </div>
      <el-button @click="$router.push('/predict/records')">模型预测记录</el-button>
    </div>

    <el-card shadow="never">
      <el-form label-width="120px">
        <el-form-item label="训练模型">
          <el-select v-model="form.train_job_id" filterable style="width: 420px" @change="loadCols">
            <el-option v-for="j in jobs" :key="j.id" :label="`${j.name} · ${j.model_type}`" :value="j.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="输入方式">
          <el-radio-group v-model="mode">
            <el-radio-button label="form">在线填写</el-radio-button>
            <el-radio-button label="excel">Excel 导入</el-radio-button>
            <el-radio-button label="dataset">数据集导入</el-radio-button>
            <el-radio-button label="source">数据源导入</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="mode !== 'excel'">
          <div v-if="mode === 'dataset' || mode === 'source'" class="import-bar">
            <el-button type="primary" plain @click="openImport">{{ importBtnText }}</el-button>
            <span v-if="importHint" class="muted">{{ importHint }}</span>
          </div>
          <el-table
            v-if="columns.length"
            :data="pagedRows"
            size="small"
            border
            class="feat-table"
            :empty-text="emptyFeatText"
          >
            <el-table-column type="index" label="#" width="58" :index="rowIndex" />
            <el-table-column
              v-for="col in columns"
              :key="col"
              :label="colLabel(col)"
              min-width="140"
            >
              <template #default="{ row }">
                <el-input v-model="row[col]" size="small" :placeholder="col" />
              </template>
            </el-table-column>
            <el-table-column label="" width="72" fixed="right">
              <template #default="{ $index }">
                <el-button link type="danger" @click="removeRow($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="row-ops">
            <el-button size="small" @click="addRow">新增一行</el-button>
            <ListPager
              v-if="form.rows.length > rowPageSize"
              v-model:page="rowPage"
              v-model:pageSize="rowPageSize"
              :total="form.rows.length"
              :page-sizes="[10, 20, 50, 100]"
              @change="onRowPager"
            />
          </div>
        </template>
        <template v-else>
          <el-button @click="downloadTpl">下载填写模板</el-button>
          <el-upload :show-file-list="true" :auto-upload="false" accept=".xlsx,.xls,.csv" :on-change="f => excel = f.raw">
            <el-button>选择填好的文件</el-button>
          </el-upload>
        </template>
        <el-form-item label="LLM 解读" style="margin-top: 16px">
          <el-switch v-model="form.use_llm" />
        </el-form-item>
        <template v-if="form.use_llm">
          <el-form-item label="LLM 配置">
            <el-select v-model="form.llm_config_id" style="width: 280px">
              <el-option v-for="c in llms" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="提示词">
            <el-select v-model="form.prompt_id" style="width: 280px">
              <el-option v-for="p in prompts" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="用户短问题">
            <el-input
              v-model="form.question"
              type="textarea"
              :rows="3"
              style="width: 620px"
              placeholder="可留空。填写时作为补充要求，并用于知识库召回；召回为空也会照常给出解读。"
            />
          </el-form-item>
          <el-form-item label="启用 RAG"><el-switch v-model="form.use_rag" /></el-form-item>
        </template>
        <el-button type="primary" :loading="loading" @click="run">开始预测</el-button>
      </el-form>
    </el-card>

    <el-card v-if="result" shadow="never" style="margin-top: 16px">
      <template #header>
        <div class="result-head">
          <span>预测结果</span>
          <el-button link type="primary" @click="$router.push('/predict/records')">查看模型预测记录</el-button>
        </div>
      </template>
      <el-table :data="result.result || []" size="small" max-height="360">
        <el-table-column
          v-for="col in resultCols"
          :key="col"
          :prop="col"
          :label="resultColLabel(col)"
          min-width="140"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ formatResultCell(col, row[col]) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="result.llm_analysis" class="markdown-body" v-html="md(result.llm_analysis)"></div>
    </el-card>

    <el-dialog
      v-model="importDlg.visible"
      title="导入特征数据"
      width="92%"
      top="4vh"
      destroy-on-close
      @opened="loadPreview"
    >
      <div class="import-toolbar">
        <el-radio-group v-model="importDlg.kind" @change="onKindChange">
          <el-radio-button label="dataset">数据表</el-radio-button>
          <el-radio-button label="bundle">逻辑数据集</el-radio-button>
          <el-radio-button label="source">数据源库表</el-radio-button>
        </el-radio-group>
        <el-select
          v-if="importDlg.kind !== 'source'"
          v-model="importDlg.id"
          filterable
          placeholder="请选择"
          style="width: 280px"
          @change="onSourceChange"
        >
          <el-option
            v-for="s in importSources"
            :key="s.id"
            :label="`${s.name}（${s.n_rows || 0} 行）`"
            :value="s.id"
          />
        </el-select>
        <template v-else>
          <el-select v-model="importDlg.sourceId" filterable placeholder="数据源" style="width: 200px" @change="onPredictSourceChange">
            <el-option
              v-for="s in sourcePicker.sources"
              :key="s.id"
              :label="s.name"
              :value="s.id"
            />
          </el-select>
          <el-select
            v-model="importDlg.database"
            filterable
            placeholder="库"
            style="width: 160px"
            :loading="sourcePicker.loadingDbs"
            :disabled="!importDlg.sourceId"
            @change="onPredictDbChange"
          >
            <el-option v-for="d in sourcePicker.dbs" :key="d.name" :label="d.name" :value="d.name" />
          </el-select>
          <el-select
            v-model="importDlg.table"
            filterable
            placeholder="表"
            style="width: 200px"
            :loading="sourcePicker.loadingTables"
            :disabled="!importDlg.database"
            @change="onSourceChange"
          >
            <el-option
              v-for="t in sourcePicker.tables"
              :key="t.table"
              :label="`${t.table}（约 ${t.rows || 0} 行）`"
              :value="t.table"
            />
          </el-select>
        </template>
        <span class="muted">
          {{ preview.filtered ? `筛选后 ${preview.total} 行` : `共 ${preview.total || selectedSource?.n_rows || 0} 行` }}
          · 已勾选 {{ pickedCount }} 条，最多 2000
        </span>
      </div>
      <div class="filter-box">
        <div class="filter-head">按字段筛选（可多条件，同时满足）</div>
        <div v-for="(f, i) in filters" :key="i" class="filter-row">
          <el-select v-model="f.col" filterable clearable placeholder="选择字段" style="width: 200px" :teleported="false">
            <el-option
              v-for="col in preview.columns"
              :key="col"
              :label="previewColLabel(col)"
              :value="col"
            />
          </el-select>
          <el-select v-model="f.op" style="width: 120px" :teleported="false">
            <el-option v-for="op in FILTER_OPS" :key="op.value" :label="op.label" :value="op.value" />
          </el-select>
          <el-input v-model="f.value" :placeholder="f.op === 'between' ? '起始值' : '条件值'" style="width: 160px" />
          <el-input v-if="f.op === 'between'" v-model="f.value2" placeholder="结束值" style="width: 160px" />
          <el-button link type="danger" @click="removeFilter(i)">删除</el-button>
        </div>
        <div class="filter-ops">
          <el-button size="small" @click="addFilter">加条件</el-button>
          <el-button size="small" type="primary" plain @click="applyFilters">应用筛选</el-button>
          <el-button size="small" @click="clearFilters">清除筛选</el-button>
        </div>
      </div>
      <div class="range-box">
        <span>按行号区间导入</span>
        <span>从第</span>
        <el-input-number v-model="range.start" :min="1" :max="rangeMax" :step="1" controls-position="right" />
        <span>条到第</span>
        <el-input-number v-model="range.end" :min="1" :max="rangeMax" :step="1" controls-position="right" />
        <span>条</span>
        <el-button size="small" type="primary" plain :loading="importDlg.loading" @click="importRange">导入该区间</el-button>
        <span class="muted">按原始行号，不勾选也可以直接导入</span>
      </div>
      <el-table
        ref="previewTableRef"
        v-loading="preview.loading"
        :data="preview.records"
        row-key="_rowKey"
        size="small"
        border
        stripe
        max-height="460"
        :empty-text="importDlg.kind === 'source' ? '请选择数据源、库和表后查看数据' : '请选择数据集后查看具体数据，可用上方条件筛选或按行号区间导入'"
        @selection-change="onPreviewSelect"
      >
        <el-table-column type="selection" width="46" />
        <el-table-column type="index" label="#" width="64" :index="previewRowIndex" />
        <el-table-column
          v-for="col in preview.columns"
          :key="col"
          :prop="col"
          :label="previewColLabel(col)"
          min-width="128"
          show-overflow-tooltip
        />
      </el-table>
      <ListPager
        v-if="preview.total"
        v-model:page="preview.page"
        v-model:pageSize="preview.pageSize"
        :total="preview.total"
        :page-sizes="[20, 50, 100, 200]"
        @change="onPreviewPager"
      />
      <template #footer>
        <el-button @click="clearPicked">清空已选</el-button>
        <el-button @click="importDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="importDlg.loading" :disabled="!pickedCount" @click="confirmImport">
          导入已勾选 {{ pickedCount }} 条
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import Cookies from 'js-cookie'
import {
  listJobs, predictColumns, runPredict, runPredictExcel, listLLM, listPrompts,
  listDatasets, listBundles, previewDataset, previewBundle,
  listDataSources, listSourceDatabases, listSourceTables, previewSourceTable
} from '@/api'
import ListPager from '@/components/ListPager.vue'
import { unwrapList, slicePage } from '@/utils/paging'
import { defaultZh, headerLabel, parseJoinCol } from '@/utils/fieldLabels'

const route = useRoute()
const jobs = ref([])
const columns = ref([])
const llms = ref([])
const prompts = ref([])
const datasets = ref([])
const bundles = ref([])
const mode = ref('form')
const excel = ref(null)
const loading = ref(false)
const result = ref(null)
const importHint = ref('')
const rowPage = ref(1)
const rowPageSize = ref(10)
const form = reactive({
  train_job_id: null, rows: [{}], use_llm: false, use_rag: true, llm_config_id: null, prompt_id: null, question: ''
})
const FILTER_OPS = [
  { value: 'contains', label: '包含' },
  { value: 'eq', label: '等于' },
  { value: 'ne', label: '不等于' },
  { value: 'gt', label: '大于' },
  { value: 'gte', label: '大于等于' },
  { value: 'lt', label: '小于' },
  { value: 'lte', label: '小于等于' },
  { value: 'between', label: '介于' },
  { value: 'not_contains', label: '不包含' }
]
const emptyFilter = () => ({ col: '', op: 'contains', value: '', value2: '' })
const filters = ref([emptyFilter()])
const range = reactive({ start: 1, end: 50 })
const importDlg = reactive({
  visible: false,
  loading: false,
  kind: 'dataset',
  id: null,
  sourceId: null,
  database: '',
  table: ''
})
const sourcePicker = reactive({
  sources: [],
  dbs: [],
  tables: [],
  loadingDbs: false,
  loadingTables: false
})
const previewTableRef = ref()
const preview = reactive({
  loading: false,
  columns: [],
  labels: {},
  records: [],
  total: 0,
  page: 1,
  pageSize: 50,
  filtered: false,
  restoring: false
})
const picked = ref({})

const md = (t) => marked.parse(t || '')
const formatResultCell = (col, v) => {
  if (v == null || v === '') return ''
  if (col !== 'prediction') return v
  const n = Number(v)
  if (!Number.isFinite(n)) return v
  return Math.abs(n) >= 100 ? n.toFixed(1) : n.toFixed(3)
}
const resultCols = computed(() => Object.keys((result.value?.result || [])[0] || { prediction: 1 }))
const pagedRows = computed(() => slicePage(form.rows, rowPage.value, rowPageSize.value))
const importBtnText = computed(() => mode.value === 'source' ? '选择库表导入' : '选择数据导入')
const emptyFeatText = computed(() => (
  mode.value === 'source'
    ? '还没有特征行，请新增或从数据源库表导入'
    : '还没有特征行，请新增或从数据集导入'
))
const isLiveDataset = (d) => !!(d && (d.origin_type === 'mysql_live' || d.is_live))
const importSources = computed(() => importDlg.kind === 'bundle' ? bundles.value : datasets.value)
const selectedJob = computed(() => jobs.value.find(j => Number(j.id) === Number(form.train_job_id)) || null)
const selectedSource = computed(() => {
  if (importDlg.kind === 'source') {
    const t = sourcePicker.tables.find(x => x.table === importDlg.table && x.database === importDlg.database)
    const name = importDlg.database && importDlg.table ? `${importDlg.database}.${importDlg.table}` : ''
    return { name, n_rows: t?.rows || preview.total || 0 }
  }
  return importSources.value.find(s => s.id === importDlg.id) || null
})
const pickedCount = computed(() => Object.keys(picked.value).length)
const rangeMax = computed(() => Math.max(1, Number(selectedSource.value?.n_rows || preview.total || 1)))
const colLabel = (col) => headerLabel(col, '')
const previewColLabel = (col) => {
  const supplied = String(preview.labels[col] || '').trim()
  return supplied && supplied !== String(col) ? supplied : headerLabel(col, '')
}
const resultColLabel = (col) => {
  if (col !== 'prediction') return headerLabel(col, '')
  const target = selectedJob.value?.target_col
  const targetZh = defaultZh(target)
  return targetZh ? `prediction（${targetZh}预测值）` : 'prediction（预测值）'
}
const rowIndex = (i) => (rowPage.value - 1) * rowPageSize.value + i + 1
const previewRowIndex = (i) => {
  const row = preview.records[i]
  return row?._rowNo || ((preview.page - 1) * preview.pageSize + i + 1)
}

const emptyRow = () => Object.fromEntries(columns.value.map(c => [c, '']))

const addRow = () => {
  form.rows.push(emptyRow())
  rowPage.value = Math.max(1, Math.ceil(form.rows.length / rowPageSize.value))
}

const removeRow = (pageIndex) => {
  const idx = (rowPage.value - 1) * rowPageSize.value + pageIndex
  form.rows.splice(idx, 1)
  if (!form.rows.length) form.rows = [emptyRow()]
  const maxPage = Math.max(1, Math.ceil(form.rows.length / rowPageSize.value))
  if (rowPage.value > maxPage) rowPage.value = maxPage
}

const onRowPager = ({ page, pageSize }) => {
  rowPage.value = page
  rowPageSize.value = pageSize
}

const loadCols = async () => {
  if (!form.train_job_id) return
  const res = await predictColumns(form.train_job_id)
  columns.value = res.data.columns || []
  form.rows = [emptyRow()]
  importHint.value = ''
  rowPage.value = 1
}

const applyJobId = async (id) => {
  const num = Number(id)
  if (!num) return
  const hit = jobs.value.find(j => j.id === num)
  if (!hit) {
    ElMessage.warning('该训练任务还不能预测，请确认已训练成功')
    return
  }
  if (form.train_job_id === num && columns.value.length) return
  form.train_job_id = num
  await loadCols()
}

const downloadTpl = () => {
  const token = Cookies.get('token')
  window.open(`/api/predict/template/${form.train_job_id}?token=${token}`)
}

const cellText = (v) => {
  if (v == null || v === '') return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

const norm = (s) => String(s || '').trim().toLowerCase()

const matchSourceCol = (featureCol, sourceCols, labels = {}) => {
  const feat = String(featureCol || '')
  const featBase = parseJoinCol(feat).name
  const featZh = defaultZh(feat) || defaultZh(featBase)
  const items = (sourceCols || []).map((src) => {
    const base = parseJoinCol(src).name
    const label = String(labels[src] || '')
    const zhFromLabel = (label.match(/（([^）]+)）/) || [])[1] || ''
    const zh = defaultZh(src) || defaultZh(base) || zhFromLabel
    return { src, base, label, zh }
  })
  const exact = items.find(c => c.src === feat || c.base === feat || c.src === featBase || c.base === featBase)
  if (exact) return exact.src
  const ci = items.find(c => norm(c.src) === norm(feat) || norm(c.base) === norm(featBase))
  if (ci) return ci.src
  if (featZh) {
    const byZh = items.find(c => c.zh === featZh || c.label.includes(featZh))
    if (byZh) return byZh.src
  }
  const byLabel = items.find(c => norm(c.label) === norm(feat) || (featZh && norm(c.label) === norm(featZh)))
  return byLabel?.src || null
}

const loadPredictSources = async () => {
  const res = await listDataSources()
  sourcePicker.sources = unwrapList(res)
}

const onPredictSourceChange = async () => {
  importDlg.database = ''
  importDlg.table = ''
  sourcePicker.tables = []
  preview.records = []
  if (!importDlg.sourceId) return
  sourcePicker.loadingDbs = true
  try {
    const res = await listSourceDatabases(importDlg.sourceId)
    sourcePicker.dbs = res.data?.items || []
    const def = res.data?.default
    if (def && sourcePicker.dbs.some(d => d.name === def)) {
      importDlg.database = def
      await onPredictDbChange()
    }
  } finally {
    sourcePicker.loadingDbs = false
  }
}

const onPredictDbChange = async () => {
  importDlg.table = ''
  sourcePicker.tables = []
  if (!importDlg.sourceId || !importDlg.database) return
  sourcePicker.loadingTables = true
  try {
    const res = await listSourceTables(importDlg.sourceId, [importDlg.database])
    sourcePicker.tables = res.data?.items || []
  } finally {
    sourcePicker.loadingTables = false
  }
}

const sourceReady = () => importDlg.kind !== 'source' || (importDlg.sourceId && importDlg.database && importDlg.table)

const liveDatasetOfJob = (job) => {
  if (!job) return null
  return datasets.value.find(d => Number(d.id) === Number(job.target_id) && isLiveDataset(d)) || null
}

const fillSourceFromDataset = async (ds) => {
  if (!ds?.source_id) return
  importDlg.sourceId = ds.source_id
  sourcePicker.loadingDbs = true
  try {
    const res = await listSourceDatabases(importDlg.sourceId)
    sourcePicker.dbs = res.data?.items || []
    importDlg.database = ds.source_db || res.data?.default || ''
    if (!importDlg.database) return
    sourcePicker.loadingTables = true
    try {
      const tr = await listSourceTables(importDlg.sourceId, [importDlg.database])
      sourcePicker.tables = tr.data?.items || []
      importDlg.table = ds.source_table || importDlg.table || ''
    } finally {
      sourcePicker.loadingTables = false
    }
  } finally {
    sourcePicker.loadingDbs = false
  }
}

const openImport = async () => {
  if (!form.train_job_id) return ElMessage.warning('请先选择训练模型')
  if (!columns.value.length) await loadCols()
  const [d, b] = await Promise.all([listDatasets(), listBundles(), loadPredictSources()])
  datasets.value = unwrapList(d)
  bundles.value = unwrapList(b)
  const job = jobs.value.find(j => j.id === form.train_job_id)
  const liveDs = liveDatasetOfJob(job)
  if (mode.value === 'source' || liveDs) {
    importDlg.kind = 'source'
    if (liveDs) await fillSourceFromDataset(liveDs)
    else if (!importDlg.sourceId && sourcePicker.sources[0]) {
      importDlg.sourceId = sourcePicker.sources[0].id
      await onPredictSourceChange()
    }
  } else if (!importDlg.id) {
    if (job?.target_type === 'bundle' && bundles.value.some(x => x.id === job.target_id)) {
      importDlg.kind = 'bundle'
      importDlg.id = job.target_id
    } else if (job?.target_type === 'dataset' && datasets.value.some(x => x.id === job.target_id)) {
      importDlg.kind = 'dataset'
      importDlg.id = job.target_id
    } else if (datasets.value[0]) {
      importDlg.id = datasets.value[0].id
    } else if (bundles.value[0]) {
      importDlg.kind = 'bundle'
      importDlg.id = bundles.value[0].id
    }
  }
  preview.page = 1
  preview.filtered = false
  filters.value = [emptyFilter()]
  const total = Number(selectedSource.value?.n_rows || 50)
  range.start = 1
  range.end = Math.min(50, Math.max(1, total))
  picked.value = {}
  preview.records = []
  importDlg.visible = true
}

const restorePreviewSelection = async () => {
  preview.restoring = true
  await nextTick()
  const table = previewTableRef.value
  if (table) {
    table.clearSelection()
    for (const row of preview.records) {
      if (picked.value[row._rowKey]) table.toggleRowSelection(row, true)
    }
  }
  await nextTick()
  preview.restoring = false
}

const activeFilters = () => filters.value.filter((f) => {
  if (!f.col) return false
  if (f.op === 'between') return f.value !== '' || f.value2 !== ''
  if (f.op === 'eq' || f.op === 'ne') return true
  return f.value !== '' && f.value != null
})

const addFilter = () => filters.value.push(emptyFilter())
const removeFilter = (i) => {
  filters.value.splice(i, 1)
  if (!filters.value.length) filters.value = [emptyFilter()]
}
const applyFilters = () => {
  preview.page = 1
  picked.value = {}
  loadPreview()
}
const clearFilters = () => {
  filters.value = [emptyFilter()]
  preview.page = 1
  picked.value = {}
  loadPreview()
}

const loadPreview = async () => {
  if (importDlg.kind !== 'source' && !importDlg.id) {
    preview.records = []
    preview.columns = []
    preview.total = 0
    preview.filtered = false
    return
  }
  if (importDlg.kind === 'source' && !sourceReady()) {
    preview.records = []
    preview.columns = []
    preview.total = 0
    preview.filtered = false
    return
  }
  preview.loading = true
  try {
    const skip = (preview.page - 1) * preview.pageSize
    const conds = activeFilters()
    let res
    if (importDlg.kind === 'source') {
      const body = {
        database: importDlg.database,
        table: importDlg.table,
        n: preview.pageSize,
        skip
      }
      if (conds.length) body.filters = conds
      res = await previewSourceTable(importDlg.sourceId, body)
    } else {
      const api = importDlg.kind === 'bundle' ? previewBundle : previewDataset
      const params = { n: preview.pageSize, skip }
      if (conds.length) params.filters = JSON.stringify(conds)
      res = await api(importDlg.id, params)
    }
    const records = res.data?.records || []
    const rowNos = res.data?.row_nos || []
    preview.columns = res.data?.columns || []
    preview.labels = res.data?.column_labels || {}
    preview.filtered = !!res.data?.filtered
    preview.total = Number(res.data?.n_rows || selectedSource.value?.n_rows || records.length)
    preview.records = records.map((rec, i) => {
      const rowNo = Number(rowNos[i] || skip + i + 1)
      return { ...rec, _rowNo: rowNo, _rowKey: String(rowNo) }
    })
    await restorePreviewSelection()
  } finally {
    preview.loading = false
  }
}

const onPreviewPager = ({ page, pageSize }) => {
  preview.page = page
  preview.pageSize = pageSize
  loadPreview()
}

const onPreviewSelect = (rows) => {
  if (preview.restoring) return
  const visibleKeys = new Set(preview.records.map(r => r._rowKey))
  const next = { ...picked.value }
  for (const k of visibleKeys) delete next[k]
  for (const row of rows || []) next[row._rowKey] = row
  picked.value = next
}

const clearPicked = async () => {
  picked.value = {}
  preview.restoring = true
  previewTableRef.value?.clearSelection()
  await nextTick()
  preview.restoring = false
}

const onSourceChange = () => {
  preview.page = 1
  preview.filtered = false
  filters.value = [emptyFilter()]
  const total = Number(selectedSource.value?.n_rows || 50)
  range.start = 1
  range.end = Math.min(50, Math.max(1, total))
  picked.value = {}
  loadPreview()
}

const fillFromRecords = (records, hint) => {
  const sourceCols = preview.columns.length
    ? preview.columns
    : Object.keys(records[0] || {}).filter(c => c !== '_rowKey' && c !== '_rowNo')
  const labels = preview.labels || {}
  const mapping = {}
  const matched = []
  const missed = []
  for (const col of columns.value) {
    const src = matchSourceCol(col, sourceCols, labels)
    mapping[col] = src
    if (src) matched.push(col)
    else missed.push(col)
  }
  form.rows = records.map((rec) => {
    const row = emptyRow()
    for (const col of columns.value) {
      const src = mapping[col]
      row[col] = src ? cellText(rec[src]) : ''
    }
    return row
  })
  rowPage.value = 1
  const srcName = selectedSource.value?.name || '数据集'
  importHint.value = `已从「${srcName}」${hint} ${form.rows.length} 条，自动填充 ${matched.length}/${columns.value.length} 个特征`
  if (missed.length) {
    importHint.value += `；未匹配：${missed.slice(0, 6).join('、')}${missed.length > 6 ? '…' : ''}`
  }
  ElMessage.success(importHint.value)
  importDlg.visible = false
}

const confirmImport = async () => {
  if (importDlg.kind === 'source' ? !sourceReady() : !importDlg.id) return ElMessage.warning('请选择数据')
  if (!columns.value.length) return ElMessage.warning('请先选择已训练成功的模型')
  const keys = Object.keys(picked.value).sort((a, b) => Number(a) - Number(b))
  if (!keys.length) return ElMessage.warning('请先勾选要导入的数据行')
  if (keys.length > 2000) return ElMessage.warning('一次最多导入 2000 条，请减少勾选')
  fillFromRecords(keys.map(k => picked.value[k]), '勾选导入')
}

const importRange = async () => {
  if (importDlg.kind === 'source' ? !sourceReady() : !importDlg.id) return ElMessage.warning('请选择数据')
  if (!columns.value.length) return ElMessage.warning('请先选择已训练成功的模型')
  let start = Math.max(1, Number(range.start) || 1)
  let end = Math.max(1, Number(range.end) || start)
  if (end < start) [start, end] = [end, start]
  const count = end - start + 1
  if (count > 2000) return ElMessage.warning('一次最多导入 2000 条，请缩小区间')
  importDlg.loading = true
  try {
    let res
    if (importDlg.kind === 'source') {
      res = await previewSourceTable(importDlg.sourceId, {
        database: importDlg.database,
        table: importDlg.table,
        n: count,
        skip: start - 1
      })
    } else {
      const api = importDlg.kind === 'bundle' ? previewBundle : previewDataset
      res = await api(importDlg.id, { n: count, skip: start - 1 })
    }
    const records = res.data?.records || []
    if (!records.length) return ElMessage.warning('该区间没有读到数据')
    if (res.data?.columns?.length) preview.columns = res.data.columns
    if (res.data?.column_labels) preview.labels = res.data.column_labels
    fillFromRecords(records, `第 ${start}–${end} 条导入`)
  } finally {
    importDlg.loading = false
  }
}

const run = async () => {
  if (!form.train_job_id) return ElMessage.warning('请选择训练模型')
  loading.value = true
  try {
    let res
    if (mode.value === 'excel') {
      if (!excel.value) return ElMessage.warning('请选择文件')
      const fd = new FormData()
      fd.append('file', excel.value)
      fd.append('train_job_id', form.train_job_id)
      fd.append('use_llm', form.use_llm)
      fd.append('use_rag', form.use_rag)
      if (form.llm_config_id) fd.append('llm_config_id', form.llm_config_id)
      if (form.prompt_id) fd.append('prompt_id', form.prompt_id)
      if (form.question) fd.append('question', form.question)
      res = await runPredictExcel(fd)
      result.value = res.data
    } else {
      res = await runPredict({ ...form })
      result.value = res.data
    }
    if (res.data?.llm_error) {
      ElMessage.warning('预测结果已保存到「模型预测记录」，但 LLM 解读失败：' + res.data.llm_error)
    } else {
      ElMessage.success('预测完成，已记入「模型预测记录」')
    }
  } finally {
    loading.value = false
  }
}

const onKindChange = () => {
  if (importDlg.kind === 'source') {
    importDlg.id = null
    if (!sourcePicker.sources.length) loadPredictSources()
    if (importDlg.sourceId && importDlg.database && importDlg.table) onSourceChange()
    else {
      preview.records = []
      preview.columns = []
      preview.total = 0
    }
    return
  }
  importDlg.id = importSources.value[0]?.id || null
  onSourceChange()
}

watch(mode, (m) => {
  if (m === 'source') importDlg.kind = 'source'
})

watch(() => route.query.job_id, (id) => {
  if (id && jobs.value.length) applyJobId(id)
})

onMounted(async () => {
  const [j, l, p] = await Promise.all([listJobs(), listLLM(), listPrompts({ scene: 'predict' })])
  jobs.value = unwrapList(j).filter(x => x.status === 'success')
  llms.value = unwrapList(l)
  prompts.value = unwrapList(p)
  form.llm_config_id = llms.value.find(x => x.is_default)?.id || llms.value[0]?.id
  form.prompt_id = prompts.value[0]?.id
  const qid = route.query.job_id
  if (qid) {
    await applyJobId(qid)
  } else if (jobs.value[0]) {
    form.train_job_id = jobs.value[0].id
    await loadCols()
  }
})
</script>

<style scoped>
.import-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 0 0 12px 120px; }
.import-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.filter-box, .range-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: var(--panel-soft, #f8fafc);
}
.filter-head { font-size: 13px; margin-bottom: 8px; }
.filter-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; position: relative; }
.filter-ops { display: flex; gap: 8px; flex-wrap: wrap; }
.range-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
.filter-box :deep(.el-select-dropdown),
.filter-box :deep(.el-popper) { z-index: 3010 !important; }
.muted { color: var(--muted); font-size: 12px; }
.feat-table { margin: 0 0 10px 0; width: 100%; }
.row-ops { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.result-head { display: flex; align-items: center; justify-content: space-between; }
.markdown-body { margin-top: 16px; }
</style>
