<template>
  <div>
    <div class="page-head">
      <div>
        <h2>洞察报告</h2>
        <p>训练完成后由本地 LLM 结合指标、特征重要性与知识库生成，DAG 跑过「LLM 模型洞察」节点也会自动写入。点击卡片进入全文，可导出 Markdown 或 Word。</p>
      </div>
    </div>

    <el-card shadow="never" class="filter-card">
      <div class="card-head">
        <span>报告列表</span>
        <div class="head-right">
          <el-input
            v-model="keyword"
            clearable
            placeholder="标题 / 任务名 / 目标列 / 算法"
            style="width: 260px"
            @keyup.enter="search"
          />
          <el-select v-model="targetCol" clearable placeholder="目标列" style="width: 150px" @change="search">
            <el-option
              v-for="opt in targetOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <el-select v-model="modelType" clearable placeholder="算法" style="width: 140px" @change="search">
            <el-option
              v-for="m in modelOptions"
              :key="m.key"
              :label="m.name"
              :value="m.key"
            />
          </el-select>
          <el-button size="small" type="primary" @click="search">查询</el-button>
          <el-button size="small" @click="reset">重置</el-button>
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
    </el-card>

    <div v-if="list.length" class="insight-grid">
      <article
        v-for="row in list"
        :key="row.id"
        class="insight-card"
        :class="{ 'is-picked': isPicked(row.id) }"
        @click="$router.push(`/insight/${row.id}`)"
      >
        <div class="cover" :style="{ background: coverOf(row.id) }">
          <div class="cover-top" @click.stop>
            <el-checkbox :model-value="isPicked(row.id)" @change="togglePick(row)" />
            <span class="badge">洞察</span>
          </div>
          <b>{{ targetText(row) }}</b>
        </div>
        <div class="body">
          <h3>{{ row.title || '未命名报告' }}</h3>
          <p>{{ excerpt(row.content) }}</p>
          <div class="meta">
            <el-tag v-if="row.train_name" size="small" type="info" effect="plain">{{ row.train_name }}</el-tag>
            <el-tag v-else-if="row.train_job_id" size="small" type="info" effect="plain">训练 #{{ row.train_job_id }}</el-tag>
            <span>{{ fmtTime(row.create_time) }}</span>
          </div>
          <div class="ops" @click.stop>
            <el-button link type="primary" @click="$router.push(`/insight/${row.id}`)">查看详情</el-button>
            <el-button link type="primary" @click="download(row, 'md')">Markdown</el-button>
            <el-button link type="primary" @click="download(row, 'docx')">Word</el-button>
            <el-button link type="danger" :loading="removingId === row.id" @click="removeOne(row)">删除</el-button>
          </div>
        </div>
      </article>
    </div>
    <el-card v-else shadow="never">
      <el-empty :description="emptyText" />
    </el-card>
    <ListPager
      v-if="total > pageSize"
      v-model:page="page"
      v-model:pageSize="pageSize"
      :total="total"
      @change="onPager"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteInsight, deleteInsights, exportInsightById, getZoo, listInsights } from '@/api'
import { insightExportFilename } from '@/utils/exportFilename'
import ListPager from '@/components/ListPager.vue'
import { unwrapPage } from '@/utils/paging'
import { defaultZh } from '@/utils/fieldLabels'

const COVERS = ['#1d6fd8', '#0f766e', '#7c3aed', '#c2410c']
const TARGET_KEYS = ['price_da', 'load_mw', 'solar_mw', 'wind_mw', 'renewable_mw', 'Sales']
const list = ref([])
const page = ref(1)
const pageSize = ref(12)
const total = ref(0)
const keyword = ref('')
const targetCol = ref('')
const modelType = ref('')
const picked = ref([])
const removing = ref(false)
const removingId = ref(null)
const modelOptions = ref([])

const targetOptions = TARGET_KEYS.map(value => ({
  value,
  label: defaultZh(value) || value
}))

const filtering = computed(() => !!(keyword.value.trim() || targetCol.value || modelType.value))
const emptyText = computed(() =>
    filtering.value ? '没有符合条件的洞察报告' : '还没有洞察报告。在训练任务成功后点「LLM 洞察」，或让 DAG 跑过「LLM 模型洞察」节点即可生成。'
)

const coverOf = (id) => COVERS[(Number(id) || 0) % COVERS.length]
const targetText = (row) => defaultZh(row.target_col) || row.model_type || '训练洞察'
const fmtTime = (t) => {
  if (!t) return ''
  const s = String(t).replace('T', ' ')
  return s.length > 16 ? s.slice(0, 16) : s
}
const excerpt = (text) => {
  const raw = String(text || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim()
  const lines = raw.split('\n').map(s => s.trim()).filter(Boolean)
  const body = lines.filter(l => !/^(首先|用户要求|你是|关键点|提供的材料|完成三个|#+\s*$)/.test(l))
  const pick = (body.find(l => l.length > 12 && !l.startsWith('#')) || body[0] || '点击查看完整报告')
    .replace(/^#+\s*/, '')
  return pick.length > 88 ? `${pick.slice(0, 88)}…` : pick
}

const isPicked = (id) => picked.value.some(r => r.id === id)
const togglePick = (row) => {
  if (isPicked(row.id)) picked.value = picked.value.filter(r => r.id !== row.id)
  else picked.value = [...picked.value, row]
}
const prunePicked = () => {
  const ids = new Set(list.value.map(r => r.id))
  picked.value = picked.value.filter(r => ids.has(r.id))
}

const queryParams = () => ({
  page: page.value,
  page_size: pageSize.value,
  keyword: keyword.value.trim() || undefined,
  target_col: targetCol.value || undefined,
  model_type: modelType.value || undefined
})

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const download = async (row, fmt) => {
  if (!row?.id) return
  const res = await exportInsightById(row.id, fmt)
  saveBlob(res.data, insightExportFilename(row, fmt))
  ElMessage.success(fmt === 'docx' ? '已导出 Word' : '已导出 Markdown')
}

const load = async () => {
  const packed = unwrapPage(await listInsights(queryParams()))
  list.value = packed.items
  total.value = packed.total
  prunePicked()
}

const search = () => {
  page.value = 1
  load()
}

const reset = () => {
  keyword.value = ''
  targetCol.value = ''
  modelType.value = ''
  page.value = 1
  load()
}

const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  load()
}

const removeOne = async (row) => {
  if (!row?.id) return
  try {
    await ElMessageBox.confirm(`确定删除「${row.title || '未命名报告'}」？删除后不可恢复。`, '删除洞察报告', { type: 'warning' })
  } catch {
    return
  }
  removingId.value = row.id
  try {
    await deleteInsight(row.id)
    ElMessage.success('已删除')
    picked.value = picked.value.filter(r => r.id !== row.id)
    await load()
  } finally {
    removingId.value = null
  }
}

const removePicked = async () => {
  const rows = picked.value.filter(r => r?.id)
  if (!rows.length) return ElMessage.warning('请先勾选要删除的洞察报告')
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${rows.length} 条洞察报告？删除后不可恢复。`, '批量删除', { type: 'warning' })
  } catch {
    return
  }
  removing.value = true
  try {
    const res = await deleteInsights(rows.map(r => r.id))
    ElMessage.success(res.message || `已删除 ${res.data?.deleted || rows.length} 条`)
    picked.value = []
    await load()
  } finally {
    removing.value = false
  }
}

onMounted(async () => {
  try {
    const res = await getZoo()
    const zoo = Array.isArray(res.data) ? res.data : (res.data?.items || [])
    modelOptions.value = zoo.map(m => ({ key: m.key, name: m.name || m.key })).filter(m => m.key)
  } catch {
    modelOptions.value = [
      { key: 'xgboost', name: 'XGBoost' },
      { key: 'lightgbm', name: 'LightGBM' },
      { key: 'catboost', name: 'CatBoost' },
      { key: 'random_forest', name: '随机森林' },
      { key: 'gbdt', name: 'GBDT' }
    ]
  }
  await load()
})
</script>

<style scoped>
.filter-card { margin-bottom: 16px; }
.card-head {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
}
.head-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.insight-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.insight-card {
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  background: var(--panel);
  box-shadow: var(--shadow);
  transition: transform .15s ease, border-color .15s ease;
}
.insight-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
}
.insight-card.is-picked { border-color: var(--accent); }
.cover {
  height: 92px;
  color: #fff;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.cover-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.cover-top :deep(.el-checkbox__inner) {
  background: rgba(255,255,255,.22);
  border-color: rgba(255,255,255,.7);
}
.cover-top :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background: #fff;
  border-color: #fff;
}
.cover-top :deep(.el-checkbox__input.is-checked .el-checkbox__inner::after) {
  border-color: #0f766e;
}
.cover .badge {
  font-size: 11px;
  letter-spacing: 0.08em;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255,255,255,.18);
}
.cover b { font-size: 16px; font-weight: 600; }
.body { padding: 14px 16px 10px; }
.body h3 {
  font-size: 15px;
  line-height: 1.4;
  min-height: 42px;
}
.body p {
  margin-top: 6px;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.6;
  min-height: 40px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
  padding-top: 4px;
  border-top: 1px solid var(--line);
}
</style>
