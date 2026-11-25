<template>
  <div>
    <div class="page-head">
      <div>
        <h2>模型预测记录</h2>
        <p>这里汇总所有预测结果：数据预测页提交的、DAG 流程里「模型预测」节点产出的都会进列表。支持按名称 / 模型查询、查看明细与删除；如果这条记录做过 LLM 分析，点「查看」就能直接看到分析正文。</p>
      </div>
      <el-button @click="$router.push('/predict')">去数据预测</el-button>
    </div>

    <el-card shadow="never" class="filter-card">
      <div class="card-head">
        <span>预测记录</span>
        <div class="head-right">
          <el-input
            v-model="keyword"
            clearable
            placeholder="记录名称 / 训练任务名"
            style="width: 240px"
            @keyup.enter="search"
          />
          <el-select v-model="trainJobId" filterable clearable placeholder="训练模型" style="width: 240px" @change="search">
            <el-option v-for="j in jobs" :key="j.id" :label="`${j.name} · ${j.model_type}`" :value="j.id" />
          </el-select>
          <el-checkbox v-model="llmOnly" @change="search">只看有 LLM 分析</el-checkbox>
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

    <el-card shadow="never">
      <el-table
        v-loading="loading"
        :data="list"
        size="small"
        border
        @selection-change="onSelect"
      >
        <el-table-column type="selection" width="46" />
        <el-table-column prop="id" label="#" width="70" />
        <el-table-column prop="name" label="记录名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="训练模型" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.train_name || `训练 #${row.train_job_id}` }}
            <el-tag v-if="row.target_col" size="small" effect="plain" type="info">{{ targetZh(row.target_col) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="输入方式" width="110">
          <template #default="{ row }">{{ inputTypeText(row.input_type) }}</template>
        </el-table-column>
        <el-table-column prop="n_rows" label="结果行数" width="96" />
        <el-table-column label="LLM 分析" width="150">
          <template #default="{ row }">
            <el-tag v-if="row.has_llm" size="small" type="success" effect="plain">已生成</el-tag>
            <el-tag v-else-if="row.use_llm" size="small" type="warning" effect="plain">未生成</el-tag>
            <span v-else class="muted">未启用</span>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="创建人" width="100" />
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button link type="danger" :loading="removingId === row.id" @click="removeOne(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="emptyText" />
        </template>
      </el-table>
      <ListPager
        v-if="total > pageSize"
        v-model:page="page"
        v-model:pageSize="pageSize"
        :total="total"
        @change="onPager"
      />
    </el-card>

    <el-drawer v-model="detail.visible" :title="detail.row?.name || '预测记录'" size="72%">
      <div v-if="detail.row" v-loading="detail.loading">
        <el-descriptions :column="3" size="small" border>
          <el-descriptions-item label="记录 ID">{{ detail.row.id }}</el-descriptions-item>
          <el-descriptions-item label="训练模型">{{ detail.row.train_name || `#${detail.row.train_job_id}` }}</el-descriptions-item>
          <el-descriptions-item label="目标列">{{ targetZh(detail.row.target_col) || '—' }}</el-descriptions-item>
          <el-descriptions-item label="输入方式">{{ inputTypeText(detail.row.input_type) }}</el-descriptions-item>
          <el-descriptions-item label="结果行数">{{ detail.row.n_rows }}</el-descriptions-item>
          <el-descriptions-item label="LLM 模型">{{ detail.row.llm_config_name || '平台默认' }}</el-descriptions-item>
          <el-descriptions-item label="创建人">{{ detail.row.username || '—' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ fmtTime(detail.row.create_time) }}</el-descriptions-item>
          <el-descriptions-item label="用户短问题">{{ detail.row.llm_question || '（留空）' }}</el-descriptions-item>
        </el-descriptions>

        <el-tabs v-model="detail.tab" class="detail-tabs">
          <el-tab-pane label="预测结果" name="result">
            <el-table :data="detail.row.result || []" size="small" border max-height="460">
              <el-table-column
                v-for="col in resultCols"
                :key="col"
                :prop="col"
                :label="resultColLabel(col)"
                min-width="140"
                show-overflow-tooltip
              >
                <template #default="{ row }">{{ formatCell(col, row[col]) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="输入数据" name="input">
            <el-table :data="detail.row.input || []" size="small" border max-height="460">
              <el-table-column
                v-for="col in inputCols"
                :key="col"
                :prop="col"
                :label="headerLabel(col, '')"
                min-width="140"
                show-overflow-tooltip
              />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="LLM 分析" name="llm">
            <div class="llm-bar">
              <el-button size="small" type="primary" :loading="analyzing" @click="openAnalyze">
                {{ detail.row.has_llm ? '重新生成 LLM 分析' : '生成 LLM 分析' }}
              </el-button>
              <span class="muted">可选模型 / 提示词，短问题可留空；无召回也会照常输出。</span>
            </div>
            <div v-if="detail.row.llm_analysis" class="markdown-body" v-html="md(detail.row.llm_analysis)"></div>
            <el-empty v-else description="这条记录还没有 LLM 分析，点上方按钮生成" />
            <div v-if="(detail.row.rag || []).length" class="rag-box">
              <div class="rag-head">知识库召回片段（{{ detail.row.rag.length }}）</div>
              <div v-for="(s, i) in detail.row.rag.slice(0, 6)" :key="i" class="rag-item">
                <b>[{{ s.source }}#{{ s.idx ?? i }}]</b> {{ s.text }}
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <el-dialog v-model="analyzeDlg.visible" title="LLM 分析配置" width="620px" append-to-body>
      <el-form label-width="110px">
        <el-form-item label="LLM 模型">
          <el-select v-model="analyzeDlg.form.llm_config_id" filterable clearable placeholder="不选则用平台默认模型" style="width: 100%">
            <el-option v-for="m in llms" :key="m.id" :label="`${m.name}（${m.model_name}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="提示词">
          <el-select v-model="analyzeDlg.form.prompt_id" filterable clearable placeholder="不选则用 predict 场景默认模板" style="width: 100%">
            <el-option v-for="p in prompts" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用户短问题">
          <el-input v-model="analyzeDlg.form.question" type="textarea" :rows="3" placeholder="可留空" />
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-input
            v-model="analyzeDlg.form.system_prompt"
            type="textarea"
            :rows="5"
            placeholder="可留空，留空时用「提示词」模板或场景默认文风"
          />
        </el-form-item>
        <el-form-item label="启用 RAG"><el-switch v-model="analyzeDlg.form.use_rag" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="analyzeDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="analyzing" @click="runAnalyze">开始分析</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import {
  analyzePredict, deletePredict, deletePredicts, getPredict,
  listJobs, listLLM, listPredicts, listPrompts
} from '@/api'
import ListPager from '@/components/ListPager.vue'
import { unwrapList, unwrapPage } from '@/utils/paging'
import { defaultZh, headerLabel } from '@/utils/fieldLabels'

const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const keyword = ref('')
const trainJobId = ref(null)
const llmOnly = ref(false)
const jobs = ref([])
const llms = ref([])
const prompts = ref([])
const picked = ref([])
const removing = ref(false)
const removingId = ref(null)
const analyzing = ref(false)

const detail = reactive({ visible: false, loading: false, row: null, tab: 'result' })
const analyzeDlg = reactive({
  visible: false,
  form: { llm_config_id: null, prompt_id: null, question: '', system_prompt: '', use_rag: true }
})

const INPUT_TYPE_TEXT = {
  form: '在线填写',
  excel: 'Excel 导入',
  dag: 'DAG 流程',
  dataset: '数据集导入',
  source: '数据源导入'
}
const inputTypeText = (t) => INPUT_TYPE_TEXT[t] || t || '—'
const targetZh = (c) => defaultZh(c) || c || ''
const fmtTime = (t) => {
  if (!t) return ''
  const s = String(t).replace('T', ' ')
  return s.length > 16 ? s.slice(0, 16) : s
}
const md = (t) => marked.parse(t || '')
const formatCell = (col, v) => {
  if (v == null || v === '') return ''
  if (col !== 'prediction') return v
  const n = Number(v)
  if (!Number.isFinite(n)) return v
  return Math.abs(n) >= 100 ? n.toFixed(1) : n.toFixed(3)
}
const resultCols = computed(() => Object.keys((detail.row?.result || [])[0] || { prediction: 1 }))
const inputCols = computed(() => Object.keys((detail.row?.input || [])[0] || {}))
const resultColLabel = (col) => {
  if (col !== 'prediction') return headerLabel(col, '')
  const zh = defaultZh(detail.row?.target_col)
  return zh ? `prediction（${zh}预测值）` : 'prediction（预测值）'
}
const filtering = computed(() => !!(keyword.value.trim() || trainJobId.value || llmOnly.value))
const emptyText = computed(() =>
  filtering.value ? '没有符合条件的预测记录' : '还没有预测记录。在「数据预测」提交一次预测，或让 DAG 跑过「模型预测」节点即可。'
)

const queryParams = () => ({
  page: page.value,
  page_size: pageSize.value,
  keyword: keyword.value.trim() || undefined,
  train_job_id: trainJobId.value || undefined,
  llm_only: llmOnly.value ? 1 : undefined
})

const load = async () => {
  loading.value = true
  try {
    const packed = unwrapPage(await listPredicts(queryParams()))
    list.value = packed.items
    total.value = packed.total
    const ids = new Set(list.value.map(r => r.id))
    picked.value = picked.value.filter(r => ids.has(r.id))
  } finally {
    loading.value = false
  }
}

const search = () => {
  page.value = 1
  load()
}
const reset = () => {
  keyword.value = ''
  trainJobId.value = null
  llmOnly.value = false
  page.value = 1
  load()
}
const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  load()
}
const onSelect = (rows) => {
  picked.value = rows || []
}

const openDetail = async (row) => {
  detail.visible = true
  detail.tab = row.has_llm ? 'llm' : 'result'
  detail.loading = true
  try {
    const res = await getPredict(row.id)
    detail.row = res.data
  } finally {
    detail.loading = false
  }
}

const openAnalyze = () => {
  const row = detail.row || {}
  analyzeDlg.form.llm_config_id = row.llm_config_id || llms.value.find(x => x.is_default)?.id || null
  analyzeDlg.form.prompt_id = row.prompt_id || null
  analyzeDlg.form.question = row.llm_question || ''
  analyzeDlg.form.system_prompt = ''
  analyzeDlg.form.use_rag = row.use_rag !== 0
  analyzeDlg.visible = true
}

const runAnalyze = async () => {
  if (!detail.row?.id) return
  analyzing.value = true
  try {
    const payload = {
      use_rag: analyzeDlg.form.use_rag,
      question: (analyzeDlg.form.question || '').trim(),
      system_prompt: (analyzeDlg.form.system_prompt || '').trim() || undefined
    }
    if (analyzeDlg.form.llm_config_id) payload.llm_config_id = analyzeDlg.form.llm_config_id
    if (analyzeDlg.form.prompt_id) payload.prompt_id = analyzeDlg.form.prompt_id
    const res = await analyzePredict(detail.row.id, payload)
    detail.row = res.data
    detail.tab = 'llm'
    analyzeDlg.visible = false
    ElMessage.success('LLM 分析完成')
    await load()
  } finally {
    analyzing.value = false
  }
}

const removeOne = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除预测记录「${row.name || row.id}」？删除后不可恢复。`, '删除预测记录', { type: 'warning' })
  } catch {
    return
  }
  removingId.value = row.id
  try {
    await deletePredict(row.id)
    ElMessage.success('已删除')
    if (detail.row?.id === row.id) detail.visible = false
    await load()
  } finally {
    removingId.value = null
  }
}

const removePicked = async () => {
  const rows = picked.value.filter(r => r?.id)
  if (!rows.length) return ElMessage.warning('请先勾选要删除的记录')
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${rows.length} 条预测记录？删除后不可恢复。`, '批量删除', { type: 'warning' })
  } catch {
    return
  }
  removing.value = true
  try {
    const res = await deletePredicts(rows.map(r => r.id))
    ElMessage.success(res.message || `已删除 ${res.data?.deleted || rows.length} 条`)
    await load()
  } finally {
    removing.value = false
  }
}

onMounted(async () => {
  const [j, l, p] = await Promise.all([
    listJobs({ status: 'success' }),
    listLLM({ page_size: 200 }),
    listPrompts({ page_size: 200, scene: 'predict' })
  ])
  jobs.value = unwrapList(j)
  llms.value = unwrapList(l)
  prompts.value = unwrapList(p)
  await load()
})
</script>

<style scoped>
.filter-card { margin-bottom: 16px; }
.card-head { display: flex; flex-direction: column; align-items: stretch; gap: 12px; }
.head-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.muted { color: var(--muted); font-size: 12px; }
.detail-tabs { margin-top: 16px; }
.llm-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.markdown-body { line-height: 1.75; }
.rag-box {
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--panel-soft, #f8fafc);
}
.rag-head { font-size: 13px; margin-bottom: 6px; }
.rag-item { font-size: 12.5px; color: var(--muted); line-height: 1.7; margin-bottom: 4px; }
</style>
