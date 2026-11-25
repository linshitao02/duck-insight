<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <el-button link type="primary" @click="backWorkspace">← 返回任务工作区</el-button>
        <h2>{{ isNew ? '新建数据表' : (form.name || '数据表配置') }}</h2>
        <p>
          {{ isNew
            ? '可上传文件、导入快照，或挂接 MySQL 活表（每天进新数据后无需重新上传）。'
            : '自动推断字段类型与角色，可手动调整；配置会用于后续清洗绑定与模型训练。' }}
        </p>
      </div>
      <div class="head-actions" v-if="!isNew && hasData">
        <el-button @click="reInfer" :loading="inferring">重新自动推断</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
      </div>
    </div>

    <!-- 新建 / 尚未上传：上传区 -->
    <el-card v-if="isNew || !hasData" shadow="never" class="mb">
      <template #header>① 任务信息与接入方式</template>
      <el-form label-width="96px" style="max-width: 720px">
        <el-form-item label="任务名称" :required="sourceMode === 'file'">
          <el-input v-model="form.name" :placeholder="sourceMode === 'file' ? '例如：门店日销量' : '可选；多表导入时默认用表名'" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="可选，说明数据来源或用途" />
        </el-form-item>
        <el-form-item label="接入方式">
          <el-radio-group v-model="sourceMode">
            <el-radio-button label="file">上传文件</el-radio-button>
            <el-radio-button label="source">导入快照</el-radio-button>
            <el-radio-button label="live">挂接实时表</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <el-upload
        v-if="sourceMode === 'file'"
        class="upload-box"
        drag
        :show-file-list="false"
        accept=".csv,.txt,.xls,.xlsx"
        :http-request="doUpload"
        :disabled="uploading"
      >
        <div class="upload-inner">
          <el-icon :size="40" color="var(--accent)"><UploadFilled /></el-icon>
          <p class="upload-title">{{ uploading ? '正在上传并解析…' : '拖拽文件到此处，或点击上传' }}</p>
          <p class="upload-sub">支持 csv / txt / xls / xlsx。上传后自动画像并进入字段配置。</p>
        </div>
      </el-upload>

      <div v-else class="source-import">
        <el-form label-width="96px">
          <el-form-item label="数据源" required>
            <div class="source-row">
              <el-select
                v-model="importer.sourceId"
                filterable
                placeholder="选择已配置的 MySQL"
                style="flex: 1"
                :loading="importer.loadingSources"
                @change="onSourceChange"
              >
                <el-option
                  v-for="s in importer.sources"
                  :key="s.id"
                  :label="`${s.name}（${s.host}:${s.port}）`"
                  :value="s.id"
                />
              </el-select>
              <el-button @click="$router.push('/datasource')">去配置数据源</el-button>
            </div>
          </el-form-item>
          <el-form-item label="数据库" required>
            <el-select
              v-model="importer.dbs"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="可多选库"
              style="width: 100%"
              :disabled="!importer.sourceId"
              :loading="importer.loadingDbs"
              @change="loadSourceTables"
            >
              <el-option v-for="d in importer.dbOptions" :key="d.name" :label="d.name" :value="d.name" />
            </el-select>
          </el-form-item>
        </el-form>
        <el-table
          ref="tableRef"
          :data="pagedSourceTables"
          v-loading="importer.loadingTables"
          max-height="360"
          size="small"
          highlight-current-row
          @selection-change="onTableSelect"
          @current-change="onLiveTablePick"
        >
          <el-table-column v-if="sourceMode === 'source'" type="selection" width="42" />
          <el-table-column prop="database" label="库" width="160" />
          <el-table-column prop="table" label="表" min-width="180" />
          <el-table-column prop="rows" label="约行数" width="100" />
          <el-table-column prop="comment" label="注释" min-width="160" show-overflow-tooltip />
        </el-table>
        <ListPager
          v-model:page="tablePage"
          v-model:pageSize="tablePageSize"
          :total="filteredSourceTables.length"
          @change="onTablePager"
        />
        <div class="import-bar">
          <el-input v-model="importer.keyword" clearable placeholder="筛选表名" style="width: 220px" />
          <span class="muted">
            {{ sourceMode === 'live'
              ? (importer.liveTable ? `将挂接 ${importer.liveTable.database}.${importer.liveTable.table}，每次读当前表` : '点选一张表挂接，后续进数会直接反映')
              : `已选 ${importer.picked.length} 张表，单表最多导入 20 万行快照` }}
          </span>
          <el-button
            v-if="sourceMode === 'live'"
            type="primary"
            :loading="importer.loading"
            :disabled="!importer.liveTable"
            @click="doAttachLive"
          >
            挂接为实时表
          </el-button>
          <el-button v-else type="primary" :loading="importer.loading" :disabled="!importer.picked.length" @click="doImport">
            导入选中表
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 已有数据：配置区 -->
    <template v-if="hasData">
      <el-row :gutter="16">
        <el-col :lg="16">
          <el-card shadow="never" class="mb">
            <template #header>
              <div class="card-head">
                <span>② 字段配置</span>
                <div class="tip-tags">
                  <el-tag size="small" type="info">推断类型 / 角色 / 缺失策略可下拉修改</el-tag>
                  <el-tag v-if="leakageCount" size="small" type="danger">{{ leakageCount }} 个泄漏风险字段</el-tag>
                </div>
              </div>
            </template>

            <el-table :data="columns" size="default" max-height="520">
              <el-table-column prop="name" label="字段" min-width="120" fixed />
              <el-table-column label="中文释义" min-width="140">
                <template #default="{ row }">
                  <el-input v-model="row.label_zh" size="small" placeholder="可手工填写" maxlength="32" />
                </template>
              </el-table-column>
              <el-table-column label="推断类型" width="140">
                <template #default="{ row }">
                  <el-select v-model="row.inferred" size="small" style="width: 120px">
                    <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="角色" width="140">
                <template #default="{ row }">
                  <el-select v-model="row.role" size="small" style="width: 120px" @change="onRoleChange(row)">
                    <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="缺失处理" width="150">
                <template #default="{ row }">
                  <el-select v-model="row.null_strategy" size="small" style="width: 130px">
                    <el-option v-for="n in nullOptions" :key="n.value" :label="n.label" :value="n.value" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="缺失率" width="90">
                <template #default="{ row }">
                  <span :class="{ warn: row.null_ratio > 0.2 }">{{ pct(row.null_ratio) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="参与建模" width="90" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.included" :disabled="row.role === 'leakage'" />
                </template>
              </el-table-column>
              <el-table-column label="样例" min-width="180">
                <template #default="{ row }">
                  <span class="sample">{{ (row.sample || []).slice(0, 3).join(' · ') || '—' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <el-card shadow="never">
            <template #header>数据预览（前 40 行）</template>
            <el-table :data="records" size="small" max-height="360">
              <el-table-column
                v-for="col in previewCols"
                :key="col"
                :prop="col"
                :label="headerLabel(col, zhOf(col))"
                min-width="130"
                show-overflow-tooltip
              />
            </el-table>
          </el-card>
        </el-col>

        <el-col :lg="8">
          <el-card shadow="never" class="mb">
            <template #header>任务信息</template>
            <el-form label-width="88px">
              <el-form-item label="任务名称">
                <el-input v-model="form.name" />
              </el-form-item>
              <el-form-item label="备注">
                <el-input v-model="form.remark" type="textarea" :rows="2" />
              </el-form-item>
              <el-form-item :label="isLive ? '实时库表' : '源文件'">
                <span class="muted">
                  <el-tag v-if="isLive" size="small" type="success" style="margin-right: 8px">实时</el-tag>
                  {{ isLive ? `${dataset.source_db}.${dataset.source_table}` : dataset.filename }}
                </span>
              </el-form-item>
              <el-form-item label="规模">
                <span>{{ dataset.n_rows }} 行 × {{ dataset.n_cols }} 列</span>
              </el-form-item>
              <el-form-item v-if="isLive" label="刷新画像">
                <el-button size="small" :loading="importer.loading" @click="refreshLive">按当前表重读行数</el-button>
              </el-form-item>
              <el-form-item v-else label="更换文件">
                <el-upload :show-file-list="false" accept=".csv,.txt,.xls,.xlsx" :http-request="doUpload">
                  <el-button size="small">重新上传</el-button>
                </el-upload>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card shadow="never" class="mb">
            <template #header>配置摘要</template>
            <div class="stat-grid">
              <div><b>{{ roleCount('feature') }}</b><span>特征</span></div>
              <div><b>{{ roleCount('target') }}</b><span>目标</span></div>
              <div><b>{{ roleCount('key') }}</b><span>关联键</span></div>
              <div><b>{{ roleCount('time') }}</b><span>时间</span></div>
              <div><b>{{ roleCount('leakage') }}</b><span>泄漏</span></div>
              <div><b>{{ includedCount }}</b><span>参与建模</span></div>
            </div>
            <el-alert
              v-if="leakageCount"
              type="warning"
              :closable="false"
              show-icon
              style="margin-top: 12px"
              title="检测到可能的标签泄漏字段（如 Customers），默认不参与建模，可在角色中调整。"
            />
          </el-card>

          <el-card shadow="never">
            <template #header>下一步</template>
            <div class="next-steps">
              <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
              <el-button @click="$router.push('/clean')">去绑定清洗规则</el-button>
              <el-button type="primary" plain @click="$router.push('/train')">去训练模型</el-button>
              <el-button plain @click="backWorkspace">返回多表关联</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import {
  getDataset, previewDataset, updateDatasetSchema, updateDatasetMeta, uploadDatasets,
  listDataSources, listSourceDatabases, listSourceTables, importSourceTables, attachLiveTable
} from '@/api'
import { inferClientSide } from '@/utils/fieldInfer'
import { defaultZh, headerLabel } from '@/utils/fieldLabels'
import ListPager from '@/components/ListPager.vue'
import { slicePage, unwrapList } from '@/utils/paging'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const uploading = ref(false)
const saving = ref(false)
const inferring = ref(false)
const dataset = ref({})
const columns = ref([])
const records = ref([])
const previewCols = ref([])
const form = reactive({ name: '', remark: '' })
const meta = reactive({ target_col: '' })
const sourceMode = ref('file')
const tableRef = ref(null)
const tablePage = ref(1)
const tablePageSize = ref(10)
const syncingTables = ref(false)
const importer = reactive({
  sourceId: null,
  sources: [],
  dbOptions: [],
  dbs: [],
  tables: [],
  picked: [],
  liveTable: null,
  keyword: '',
  loadingSources: false,
  loadingDbs: false,
  loadingTables: false,
  loading: false
})

const isNew = computed(() => route.name === 'DatasetTaskNew' || route.params.id === 'new')
const projectId = computed(() => Number(route.params.projectId))
const isLive = computed(() => dataset.value?.origin_type === 'mysql_live' || dataset.value?.is_live)
const hasData = computed(() => !!dataset.value?.id && (!!dataset.value?.file_path || isLive.value))
const filteredSourceTables = computed(() => {
  const kw = (importer.keyword || '').trim().toLowerCase()
  if (!kw) return importer.tables
  return importer.tables.filter(t =>
    String(t.table || '').toLowerCase().includes(kw) || String(t.database || '').toLowerCase().includes(kw)
  )
})
const tableKey = (t) => `${t.database}::${t.table}`
const pagedSourceTables = computed(() => slicePage(filteredSourceTables.value, tablePage.value, tablePageSize.value))

watch(() => importer.keyword, () => { tablePage.value = 1 })

const workspacePath = computed(() =>
  projectId.value ? `/dataset/workspace/${projectId.value}` : '/dataset'
)
const backWorkspace = () => router.push(workspacePath.value)

const typeOptions = [
  { value: 'numeric', label: '数值 numeric' },
  { value: 'categorical', label: '类别 categorical' },
  { value: 'datetime', label: '日期 datetime' },
  { value: 'id', label: '标识 id' },
  { value: 'text', label: '文本 text' },
  { value: 'unknown', label: '未知 unknown' },
]
const roleOptions = [
  { value: 'feature', label: '特征 feature' },
  { value: 'target', label: '目标 target' },
  { value: 'key', label: '关联键 key' },
  { value: 'time', label: '时间 time' },
  { value: 'leakage', label: '泄漏 leakage' },
  { value: 'ignore', label: '忽略 ignore' },
]
const nullOptions = [
  { value: 'keep', label: '保留空值' },
  { value: 'auto', label: '自动填充' },
  { value: 'mean', label: '均值填充' },
  { value: 'median', label: '中位数填充' },
  { value: 'mode', label: '众数填充' },
  { value: 'zero', label: '填 0' },
  { value: 'drop', label: '删除空行' },
]

const pct = (v) => `${((Number(v) || 0) * 100).toFixed(1)}%`
const roleCount = (role) => columns.value.filter(c => c.role === role).length
const leakageCount = computed(() => roleCount('leakage'))
const includedCount = computed(() => columns.value.filter(c => c.included).length)

const onRoleChange = (row) => {
  if (row.role === 'leakage') row.included = false
  if (row.role === 'target') {
    columns.value.forEach(c => {
      if (c.name !== row.name && c.role === 'target') c.role = 'feature'
    })
    meta.target_col = row.name
  }
}

const zhOf = (name) => {
  const col = columns.value.find(c => c.name === name)
  return (col?.label_zh || defaultZh(name) || '').trim()
}

const normalizeCols = (cols) => (cols || []).map(c => ({
  ...c,
  inferred: c.inferred || 'unknown',
  role: c.role || 'feature',
  null_strategy: c.null_strategy || (c.null_ratio > 0 ? 'auto' : 'keep'),
  included: c.included !== false && c.role !== 'leakage',
  sample: c.sample || [],
  label_zh: (c.label_zh || defaultZh(c.name) || '').trim()
}))

const applyDetail = async (id) => {
  const [detail, prev] = await Promise.all([getDataset(id), previewDataset(id)])
  if (!detail.data) {
    ElMessage.error('数据集不存在')
    return backWorkspace()
  }
  if (projectId.value && detail.data.project_id && Number(detail.data.project_id) !== projectId.value) {
    ElMessage.warning('该表不属于当前数据集配置')
    return backWorkspace()
  }
  dataset.value = detail.data
  form.name = detail.data.name
  form.remark = detail.data.remark || ''
  columns.value = normalizeCols(detail.data.profile?.columns || [])
  meta.target_col = detail.data.profile?.meta?.target_col
    || columns.value.find(c => c.role === 'target')?.name
    || ''
  records.value = prev.data?.records || []
  previewCols.value = prev.data?.columns || []
}

const loadSources = async () => {
  importer.loadingSources = true
  try {
    const res = await listDataSources()
    importer.sources = unwrapList(res)
    if (!importer.sourceId && importer.sources.length === 1) {
      importer.sourceId = importer.sources[0].id
      await onSourceChange()
    }
  } finally {
    importer.loadingSources = false
  }
}

const onSourceChange = async () => {
  importer.dbs = []
  importer.tables = []
  importer.picked = []
  importer.liveTable = null
  tablePage.value = 1
  if (!importer.sourceId) return
  importer.loadingDbs = true
  try {
    const res = await listSourceDatabases(importer.sourceId)
    importer.dbOptions = res.data?.items || []
    const def = res.data?.default
    if (def && importer.dbOptions.some(d => d.name === def)) {
      importer.dbs = [def]
      await loadSourceTables()
    }
  } finally {
    importer.loadingDbs = false
  }
}

const loadSourceTables = async () => {
  importer.tables = []
  importer.picked = []
  importer.liveTable = null
  tablePage.value = 1
  if (!importer.sourceId || !importer.dbs.length) return
  importer.loadingTables = true
  try {
    const res = await listSourceTables(importer.sourceId, importer.dbs)
    importer.tables = res.data?.items || []
  } finally {
    importer.loadingTables = false
  }
}

const onTablePager = ({ page: p, pageSize: s }) => {
  tablePage.value = p
  tablePageSize.value = s
  restoreTableSelection()
}

const restoreTableSelection = async () => {
  await nextTick()
  const table = tableRef.value
  if (!table) return
  syncingTables.value = true
  table.clearSelection()
  const keys = new Set((importer.picked || []).map(tableKey))
  pagedSourceTables.value.forEach((row) => {
    if (keys.has(tableKey(row))) table.toggleRowSelection(row, true)
  })
  await nextTick()
  syncingTables.value = false
}

const onTableSelect = (rows) => {
  if (syncingTables.value) return
  const pageKeys = new Set(pagedSourceTables.value.map(tableKey))
  const kept = (importer.picked || []).filter(t => !pageKeys.has(tableKey(t)))
  importer.picked = [...kept, ...(rows || [])]
}

const onLiveTablePick = (row) => {
  if (sourceMode.value !== 'live') return
  importer.liveTable = row || null
}

watch(pagedSourceTables, () => { restoreTableSelection() })

const doImport = async () => {
  if (!importer.sourceId) return ElMessage.warning('请选择数据源')
  if (!importer.picked.length) return ElMessage.warning('请至少勾选一张表')
  if (!projectId.value) return ElMessage.warning('缺少数据集配置，请从工作区进入')
  importer.loading = true
  try {
    const res = await importSourceTables(importer.sourceId, {
      project_id: projectId.value,
      tables: importer.picked.map(t => ({ database: t.database, table: t.table })),
      name: form.name.trim() || undefined,
      remark: form.remark || '',
      scenario: userStore.scenario || 'generic'
    })
    const created = res.data?.created || []
    const errors = res.data?.errors || []
    if (!created.length) {
      ElMessage.error(errors[0]?.message || '导入失败')
      return
    }
    ElMessage.success(`已导入 ${created.length} 张表${errors.length ? `，${errors.length} 张跳过或失败` : ''}`)
    if (created.length === 1) {
      await router.replace(`/dataset/workspace/${projectId.value}/table/${created[0].id}`)
      await applyDetail(created[0].id)
    } else {
      backWorkspace()
    }
  } finally {
    importer.loading = false
  }
}

const attachPayload = (table) => ({
  project_id: projectId.value,
  tables: undefined,
  database: table.database,
  table: table.table,
  name: form.name.trim() || undefined,
  remark: form.remark || '',
  scenario: userStore.scenario || 'generic'
})

const doAttachLive = async () => {
  if (!importer.sourceId) return ElMessage.warning('请选择数据源')
  if (!importer.liveTable) return ElMessage.warning('请点选一张要挂接的表')
  if (!projectId.value) return ElMessage.warning('缺少数据集配置，请从工作区进入')
  importer.loading = true
  try {
    const res = await attachLiveTable(importer.sourceId, attachPayload(importer.liveTable))
    const created = res.data
    if (!created?.id) return ElMessage.error('挂接失败')
    ElMessage.success('已挂接实时表，预览和训练都会读当前库表')
    await router.replace(`/dataset/workspace/${projectId.value}/table/${created.id}`)
    await applyDetail(created.id)
  } finally {
    importer.loading = false
  }
}

const refreshLive = async () => {
  if (!dataset.value?.source_id) return
  importer.loading = true
  try {
    const res = await attachLiveTable(dataset.value.source_id, {
      project_id: dataset.value.project_id || projectId.value,
      database: dataset.value.source_db,
      table: dataset.value.source_table,
      name: form.name.trim() || dataset.value.name,
      remark: form.remark || dataset.value.remark || '',
      scenario: userStore.scenario || dataset.value.scenario_code || 'generic'
    })
    if (res.data?.id) {
      ElMessage.success(`已按当前表刷新，约 ${res.data.n_rows || 0} 行`)
      await applyDetail(res.data.id)
    }
  } finally {
    importer.loading = false
  }
}

const load = async () => {
  if (isNew.value) {
    dataset.value = {}
    columns.value = []
    records.value = []
    previewCols.value = []
    if (!form.name) form.name = ''
    await loadSources()
    return
  }
  loading.value = true
  try {
    await applyDetail(route.params.id)
  } finally {
    loading.value = false
  }
}

const doUpload = async ({ file }) => {
  if (!form.name.trim()) {
    ElMessage.warning('请先填写任务名称')
    return
  }
  if (!dataset.value?.id && !projectId.value) {
    ElMessage.warning('缺少数据集配置，请从工作区进入')
    return backWorkspace()
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('files', file)
    fd.append('name', form.name.trim())
    fd.append('remark', form.remark || '')
    fd.append('scenario', userStore.scenario || 'store_sales')
    if (dataset.value?.id) {
      fd.append('dataset_id', String(dataset.value.id))
    } else {
      fd.append('project_id', String(projectId.value))
    }
    const res = await uploadDatasets(fd)
    const created = (res.data || [])[0]
    if (!created?.id) {
      ElMessage.error('上传失败')
      return
    }
    if (dataset.value?.id) {
      ElMessage.success('文件已替换，字段已重新推断')
      await applyDetail(dataset.value.id)
    } else {
      ElMessage.success('上传成功，已自动推断字段，请继续配置')
      if ((res.data || []).length > 1) {
        ElMessage.info(`检测到 ${(res.data || []).length} 个工作表，已分别创建任务，当前进入第一个`)
      }
      await router.replace(`/dataset/workspace/${projectId.value}/table/${created.id}`)
      await applyDetail(created.id)
    }
  } catch (e) {
    // 失败原因已由响应拦截器统一提示，这里兜底避免未捕获的 Promise 异常
  } finally {
    uploading.value = false
  }
}

const reInfer = async () => {
  inferring.value = true
  try {
    columns.value = columns.value.map(c => {
      const guessed = inferClientSide(c)
      return {
        ...c,
        inferred: guessed.inferred,
        role: guessed.role,
        null_strategy: c.null_ratio > 0 ? (c.null_strategy || 'auto') : 'keep',
        included: guessed.role === 'leakage' ? false : c.included
      }
    })
    if (!meta.target_col) {
      const t = columns.value.find(c => c.role === 'target')
      if (t) meta.target_col = t.name
    }
    ElMessage.success('已按字段名与样例重新推断，请确认后保存')
  } finally {
    inferring.value = false
  }
}

const save = async () => {
  if (!dataset.value?.id) return ElMessage.warning('请先上传数据')
  saving.value = true
  try {
    const id = dataset.value.id
    await updateDatasetMeta(id, { name: form.name, remark: form.remark })
    await updateDatasetSchema(id, {
      columns: columns.value.map(c => ({
        name: c.name,
        inferred: c.inferred,
        role: c.role,
        null_strategy: c.null_strategy,
        included: c.included,
        fill_value: c.fill_value,
        label_zh: (c.label_zh || '').trim()
      })),
      meta: { target_col: meta.target_col || null }
    })
    ElMessage.success('任务配置已保存')
    await applyDetail(id)
  } finally {
    saving.value = false
  }
}

watch(() => route.fullPath, load)
onMounted(load)
</script>

<style scoped>
.head-actions { display: flex; gap: 8px; }
.mb { margin-bottom: 16px; }
.tip-tags { display: flex; gap: 8px; flex-wrap: wrap; }
.sample { color: var(--muted); font-size: 12px; }
.warn { color: var(--warn); font-weight: 600; }
.muted { color: var(--muted); font-size: 13px; }
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.stat-grid div {
  background: var(--panel-soft);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
}
.stat-grid b { display: block; font-size: 20px; color: var(--accent); }
.stat-grid span { font-size: 12px; color: var(--muted); }
.next-steps { display: flex; flex-direction: column; gap: 8px; }

.upload-box { width: 100%; }
.upload-box :deep(.el-upload) { width: 100%; }
.upload-box :deep(.el-upload-dragger) {
  width: 100%;
  padding: 36px 20px;
  border-radius: 12px;
  border-color: var(--line);
  background: var(--panel-soft);
}
.upload-inner { text-align: center; }
.upload-title { margin-top: 12px; font-size: 15px; font-weight: 600; color: var(--text); }
.upload-sub { margin-top: 6px; font-size: 13px; color: var(--muted); }
.source-import { margin-top: 8px; }
.source-row { display: flex; gap: 8px; width: 100%; }
.import-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.import-bar .el-button { margin-left: auto; }
</style>
