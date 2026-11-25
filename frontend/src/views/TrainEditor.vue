<template>
  <div v-loading="booting">
    <div class="page-head">
      <div>
        <el-button link type="primary" @click="$router.push('/train')">← 返回任务列表</el-button>
        <h2>{{ isNew ? '新建训练任务' : (form.name || '训练任务') }}</h2>
        <p>{{ isNew ? '配置数据源、算法与超参后开始训练。训练完成后会把 LabelEncoder / Scaler 一并写入模型产物，供预测复用。' : '可调整配置后再次训练，完成后在右侧查看评估与日志。' }}</p>
      </div>
      <div class="head-actions">
        <el-tag v-if="!isNew" :type="statusType(job?.status)" size="small">{{ statusLabel(job?.status) }}</el-tag>
        <el-button v-if="!isNew" type="danger" plain @click="removeJob">删除记录</el-button>
        <el-button v-if="job?.status === 'success'" type="success" plain @click="goPredict">去预测</el-button>
        <el-button type="primary" :disabled="running" :loading="starting" @click="start">开始训练</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :lg="10">
        <el-card shadow="never">
          <el-form label-width="108px" :disabled="running">
            <el-form-item label="任务名称"><el-input v-model="form.name" placeholder="任务名称" /></el-form-item>
            <el-form-item label="数据源类型">
              <el-radio-group v-model="form.target_type">
                <el-radio-button label="bundle">逻辑数据集</el-radio-button>
                <el-radio-button label="dataset">原始表</el-radio-button>
                <el-radio-button label="live">实时表</el-radio-button>
                <el-radio-button label="binding">清洗快照</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="数据源">
              <el-select v-model="form.target_id" filterable style="width: 100%" :placeholder="sourcePlaceholder" @change="onSource">
                <el-option v-for="s in sources" :key="s.id" :label="sourceLabel(s)" :value="s.id" />
              </el-select>
              <p v-if="form.target_type === 'live'" class="tip">实时表训练时读当前库表，不是导入时的死快照。</p>
            </el-form-item>
            <el-form-item label="清洗规则" v-if="form.target_type !== 'binding'">
              <el-select v-model="form.rule_id" clearable filterable style="width: 100%" @change="onRuleChange">
                <el-option v-for="r in rules" :key="r.id" :label="r.name" :value="r.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="目标列">
              <el-select v-model="form.target_col" filterable allow-create style="width: 100%">
                <el-option v-for="c in columns" :key="c" :label="colLabel(c)" :value="c" />
              </el-select>
            </el-form-item>
            <el-form-item label="特征列">
              <div class="field-tags" v-if="form.feature_cols?.length">
                <el-tag
                  v-for="c in form.feature_cols"
                  :key="c"
                  closable
                  type="info"
                  effect="plain"
                  @close="form.feature_cols = form.feature_cols.filter(x => x !== c)"
                >{{ colLabel(c) }}</el-tag>
              </div>
              <el-select v-model="form.feature_cols" multiple filterable :collapse-tags="false" :max-collapse-tags="99" style="width: 100%">
                <el-option v-for="c in columns.filter(x => x !== form.target_col)" :key="c" :label="colLabel(c)" :value="c" />
              </el-select>
            </el-form-item>
            <el-form-item label="任务类型">
              <el-radio-group v-model="form.task_type">
                <el-radio-button label="regression" :disabled="!canRegression">回归</el-radio-button>
                <el-radio-button label="classification" :disabled="!canClassification">分类</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="算法">
              <el-select v-model="form.model_type" style="width: 100%" @change="onModel">
                <el-option-group v-for="g in zooGroups" :key="g.family" :label="g.family">
                  <el-option v-for="m in g.items" :key="m.key" :label="`${m.name}${m.available ? '' : '（未安装）'}`" :value="m.key" :disabled="!m.available" />
                </el-option-group>
              </el-select>
            </el-form-item>
            <p class="tip">{{ currentModel?.tips }}</p>
            <el-form-item label="参数预设">
              <el-radio-group v-model="preset" @change="applyPreset">
                <el-radio-button v-for="opt in PRESET_OPTIONS" :key="opt.value" :label="opt.value">{{ opt.label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-for="p in currentModel?.params || []" :key="p.key" :label="p.label">
              <el-select v-if="p.type === 'select'" v-model="form.params[p.key]" style="width: 100%" @change="onParamEdit">
                <el-option v-for="opt in p.options" :key="String(opt)" :label="String(opt)" :value="opt" />
              </el-select>
              <el-input v-else-if="p.type === 'string'" v-model="form.params[p.key]" @input="onParamEdit" />
              <el-input-number
                v-else
                :key="`${paramEpoch}-${p.key}`"
                v-model="form.params[p.key]"
                :min="p.min"
                :max="p.max"
                :step="p.step != null ? p.step : (p.type === 'float' ? 0.01 : 1)"
                :precision="p.step && p.step < 0.01 ? 4 : undefined"
                style="width: 100%"
                @change="onParamEdit"
              />
            </el-form-item>
            <el-form-item label="抽样行数">
              <el-input-number v-model="form.sample_rows" :min="0" :max="2000000" style="width: 100%" />
              <span class="tip">0 表示全量。示例建议 30000~80000。</span>
            </el-form-item>
            <el-form-item label="验证集比例"><el-input-number v-model="form.test_size" :min="0.05" :max="0.4" :step="0.05" /></el-form-item>
            <el-form-item label="随机种子"><el-input-number v-model="form.random_state" :min="0" :max="999999" /></el-form-item>
            <el-form-item label="log1p 目标"><el-switch v-model="form.log_target" :disabled="form.task_type === 'classification'" /></el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :lg="14">
        <el-card v-if="job && job.status !== 'draft'" shadow="never">
          <template #header>
            <div class="card-head">
              <span>{{ job.name }} 评估</span>
              <div class="head-actions">
                <el-tooltip placement="bottom" content="打包随机种子、超参数、评估指标、特征重要性、训练曲线与局限说明，便于论文复现或归档。">
                  <el-button size="small" :disabled="job.status !== 'success'" :loading="exporting" @click="downloadPack">导出实验材料</el-button>
                </el-tooltip>
                <el-button v-if="job.insight_id" size="small" @click="$router.push(`/insight/${job.insight_id}`)">查看完整报告</el-button>
                <el-tooltip placement="bottom" content="用本地 LLM 结合评估指标、特征重要性与知识库，生成可写入论文讨论节/企业附件的解读，并保存到洞察报告。">
                  <el-button size="small" type="primary" :disabled="job.status !== 'success'" :loading="insighting" @click="genInsight">LLM 洞察</el-button>
                </el-tooltip>
              </div>
            </div>
          </template>
          <el-progress :percentage="job.progress || 0" :status="job.status === 'success' ? 'success' : (job.status === 'failed' ? 'exception' : undefined)" />
          <p v-if="job.status === 'running' || job.status === 'pending'" class="tip" style="margin: 8px 0 0 0">
            {{ job.status === 'pending' ? '排队等待执行…' : '正在训练，进度会自动刷新' }}
          </p>
          <el-alert v-if="job.status === 'failed' && job.error_message" type="error" :title="job.error_message" show-icon :closable="false" style="margin-top: 12px" />
          <el-descriptions :column="3" size="small" style="margin: 12px 0">
            <el-descriptions-item v-for="(v, k) in (job.metrics || {})" :key="k" :label="k">
              {{ typeof v === 'number' ? v.toFixed(4) : v }}
            </el-descriptions-item>
            <el-descriptions-item label="种子">{{ job.random_state ?? 42 }}</el-descriptions-item>
            <el-descriptions-item label="预设">{{ job.param_preset || '-' }}</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ job.duration_sec ? `${job.duration_sec}s` : '-' }}</el-descriptions-item>
          </el-descriptions>
          <el-row :gutter="12">
            <el-col :span="12"><div ref="impRef" style="height: 300px"></div></el-col>
            <el-col :span="12"><div ref="curveRef" style="height: 300px"></div></el-col>
            <el-col :span="12"><div ref="histTrainRef" style="height: 300px"></div></el-col>
            <el-col :span="12"><div ref="histRef" style="height: 300px"></div></el-col>
          </el-row>
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="局限说明（会写入导出的实验材料）"
            :description="limitText"
            style="margin-top: 12px"
          />
          <pre class="log">{{ job.log_text }}</pre>
          <div v-if="insightText" class="insight-box">
            <div class="insight-head">
              <strong>{{ job.insight_title || 'LLM 洞察报告' }}</strong>
              <div>
                <el-button v-if="job.insight_id" link type="primary" @click="$router.push(`/insight/${job.insight_id}`)">查看完整报告</el-button>
                <el-button link type="primary" @click="downloadInsight('md')">Markdown</el-button>
                <el-button link type="primary" @click="downloadInsight('docx')">Word</el-button>
              </div>
            </div>
            <p class="tip" style="margin: 0 0 8px 0">本地 Ollama 根据指标、特征重要性与知识库生成，可改写入论文讨论节或作为企业附件。</p>
            <div class="markdown-body" v-html="insightHtml"></div>
          </div>
        </el-card>
        <el-card v-else shadow="never" class="placeholder">
          <p>{{ isNew ? '在左侧选好数据源和算法，点击开始训练。训练进度和评估会显示在这里。' : '这是一份草稿任务。在左侧选好数据源和算法后再开始训练。' }}</p>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="insightDialog" title="LLM 模型洞察" width="760px" append-to-body>
      <el-form label-width="92px">
        <el-form-item label="LLM 模型">
          <el-select v-model="insightForm.llm_config_id" filterable clearable placeholder="不选则用平台默认模型" style="width: 100%">
            <el-option v-for="m in insightOptions.llms" :key="m.id" :label="`${m.name}（${m.model_name}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-select
            v-model="insightForm.prompt_id"
            filterable
            clearable
            placeholder="选模板，或选「自定义」自己填"
            style="width: 100%"
            @change="onPickInsightPrompt"
          >
            <el-option label="自定义（在下方填写）" :value="CUSTOM_PICK" />
            <el-option label="平台默认文风" :value="EMPTY_PICK" />
            <el-option-group v-for="g in insightPromptGroups" :key="g.label" :label="g.label">
              <el-option v-for="p in g.options" :key="p.id" :label="p.name" :value="p.id" />
            </el-option-group>
          </el-select>
          <el-input
            v-model="insightForm.system_prompt"
            type="textarea"
            :rows="8"
            style="margin-top: 8px"
            placeholder="控制文风与章节；可用 {metrics} {importance} {predictions} {context} 占位符，运行时自动填充。留空则用平台默认。"
          />
        </el-form-item>
        <el-form-item label="用户短问题">
          <el-input
            v-model="insightForm.question"
            type="textarea"
            :rows="3"
            placeholder="可留空。填写时会作为补充要求，同时用于知识库召回。"
          />
        </el-form-item>
        <el-form-item label="启用 RAG">
          <el-switch v-model="insightForm.use_rag" />
          <span class="tip" style="margin-left: 10px">留空或召回为空都照常生成报告。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="insightDialog = false">取消</el-button>
        <el-button type="primary" :loading="insighting" @click="runInsight">生成洞察报告</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import * as echarts from 'echarts'
import { useUserStore } from '@/stores/user'
import { axisCaption, featureColsForTarget, featureTick, generatedColumnsFromSteps, headerLabel } from '@/utils/fieldLabels'
import { insightExportFilename } from '@/utils/exportFilename'
import { PRESET_OPTIONS, inferParamPreset, presetParams, resolveParamPreset, fillParamDefaults, allowedTasks, coerceTaskType } from '@/utils/modelPresets'
import {
  getZoo, getJob, startTrain, listRules, listDatasets, listBundles,
  listBindings, previewBundle, previewDataset, createInsight, deleteJob,
  exportTrainPack, exportInsightMd, exportInsightById, listLLM, listPrompts
} from '@/api'
import { unwrapList } from '@/utils/paging'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const zoo = ref([])
const rules = ref([])
const datasets = ref([])
const bundles = ref([])
const bindings = ref([])
const columns = ref([])
const baseColumns = ref([])
const columnLabels = ref({})
const preset = ref('balanced')
const booting = ref(true)
const starting = ref(false)
const paramEpoch = ref(0)
let applyingPreset = false
const exporting = ref(false)
const insighting = ref(false)
const job = ref(null)
const insightText = ref('')

// ── LLM 洞察配置弹框：可选择模型/提示词，也可自己填 ──
const CUSTOM_PICK = '__custom__'
const EMPTY_PICK = '__empty__'
const SCENE_LABEL = {
  insight: '训练洞察',
  power_train: '气象驱动训练',
  price_forecast: '电价预测',
  predict_risk: '风险预警',
  power_decision: '决策报告',
  qa: '问答'
}
const insightDialog = ref(false)
const insightOptions = ref({ llms: [], prompts: [] })
const insightForm = reactive({
  llm_config_id: null,
  prompt_id: null,
  system_prompt: '',
  question: '',
  use_rag: true
})
const insightPromptGroups = computed(() => {
  const groups = {}
  for (const p of insightOptions.value.prompts || []) {
    const key = SCENE_LABEL[p.scene] || p.scene || '通用'
    ;(groups[key] ||= []).push(p)
  }
  return Object.entries(groups).map(([label, options]) => ({ label, options }))
})

const loadInsightOptions = async () => {
  try {
    const [l, p] = await Promise.all([listLLM({ page_size: 200 }), listPrompts({ page_size: 200, prompt_kind: 'system' })])
    insightOptions.value.llms = unwrapList(l) || []
    insightOptions.value.prompts = unwrapList(p) || []
  } catch (e) {
    insightOptions.value = { llms: [], prompts: [] }
  }
}

const openInsightDialog = async () => {
  if (!job.value?.id || job.value.status !== 'success') return
  await loadInsightOptions()
  const llms = insightOptions.value.llms || []
  const prompts = insightOptions.value.prompts || []
  insightForm.llm_config_id = job.value.llm_config_id
    || llms.find(x => x.is_default)?.id
    || llms[0]?.id
    || null
  // 默认带上平台「训练洞察」模板，用户可改可清空
  const tpl = prompts.find(x => x.scene === 'insight') || null
  insightForm.prompt_id = tpl ? tpl.id : EMPTY_PICK
  insightForm.system_prompt = tpl ? (tpl.content || '') : ''
  insightForm.question = ''
  insightForm.use_rag = true
  insightDialog.value = true
}

const onPickInsightPrompt = (id) => {
  if (id === EMPTY_PICK) {
    insightForm.prompt_id = EMPTY_PICK
    insightForm.system_prompt = ''
    return
  }
  insightForm.prompt_id = id
  const p = (insightOptions.value.prompts || []).find(x => x.id === id)
  if (p) insightForm.system_prompt = p.content || ''
}
const impRef = ref()
const curveRef = ref()
const histTrainRef = ref()
const histRef = ref()
const chartMap = {}
let timer = null
const isNew = computed(() => route.name === 'TrainNew' || route.params.id === 'new')
const form = reactive({
  name: '', target_type: 'bundle', target_id: null, rule_id: null, binding_id: null,
  target_col: 'Sales', feature_cols: [], task_type: 'regression', model_type: 'xgboost',
  params: {}, sample_rows: 40000, test_size: 0.2, random_state: 42, log_target: true
})

const STATUS_MAP = {
  draft: { label: '草稿', type: 'info' },
  pending: { label: '排队中', type: 'warning' },
  running: { label: '训练中', type: 'warning' },
  success: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' }
}
const statusLabel = (s) => STATUS_MAP[s]?.label || s || '草稿'
const statusType = (s) => STATUS_MAP[s]?.type || 'info'
const running = computed(() => job.value?.status === 'running' || job.value?.status === 'pending')
const currentModel = computed(() => zoo.value.find(m => m.key === form.model_type))
const modelTasks = computed(() => allowedTasks(currentModel.value))
const canRegression = computed(() => modelTasks.value.includes('regression'))
const canClassification = computed(() => modelTasks.value.includes('classification'))
const zooGroups = computed(() => {
  const order = []
  const map = {}
  for (const m of zoo.value) {
    const fam = m.family || '其他'
    if (!map[fam]) {
      map[fam] = []
      order.push(fam)
    }
    map[fam].push(m)
  }
  return order.map(family => ({ family, items: map[family] }))
})
const isLiveDataset = (d) => !!(d && (d.origin_type === 'mysql_live' || d.is_live))
const sources = computed(() => {
  if (form.target_type === 'live') return datasets.value.filter(isLiveDataset)
  if (form.target_type === 'dataset') return datasets.value.filter(d => !isLiveDataset(d))
  if (form.target_type === 'binding') return bindings.value
  return bundles.value
})
const sourcePlaceholder = computed(() => form.target_type === 'live' ? '选择实时库表' : '请选择')
const sourceLabel = (s) => {
  if (form.target_type === 'live') {
    const loc = [s.source_db, s.source_table].filter(Boolean).join('.')
    const rows = s.n_rows != null ? ` · ${s.n_rows}行` : ''
    return loc ? `${s.name} · ${loc}${rows}` : `${s.name}（${s.n_rows || 0} 行）`
  }
  return `${s.name} (${s.n_rows || 0}行)`
}
const insightHtml = computed(() => marked.parse(insightText.value || ''))
const limitText = computed(() => {
  const j = job.value
  if (!j) return ''
  const hist = j.curves?.history || {}
  const lines = [
    `验证为随机 hold-out（test_size=${j.test_size}，种子 ${j.random_state ?? 42}），不是滚动时序交叉验证。`,
    j.log_target ? '拟合使用 log1p，曲线在目标空间；RMSE/MAE/R2 已还原到业务量纲。' : '',
    '未做系统化超参搜索。标准化只覆盖已选特征，目标列不缩放。系统未下单。'
  ]
    if (!(hist.valid || []).length && !(hist.train || []).length) {
      lines.push('当前记录没有训练过程曲线。重新训练后会出现：提升树记轮次，随机森林记树数，决策树记深度，SVM/逻辑回归记正则 C，岭回归/Lasso 记 alpha，线性回归记样本量，Softmax/BERT 记 epoch。')
    }
  return lines.filter(Boolean).join(' ')
})

const applyPreset = (name) => {
  const n = typeof name === 'string' ? name : preset.value
  if (!n || n === 'custom') return
  applyingPreset = true
  preset.value = n
  if (n === 'accurate') form.sample_rows = 0
  const p = presetParams(currentModel.value, n)
  if (p) {
    form.params = { ...p }
    paramEpoch.value += 1
  }
  nextTick(() => { applyingPreset = false })
}
const onParamEdit = () => {
  if (booting.value || applyingPreset) return
  preset.value = inferParamPreset(currentModel.value, form.params)
}
const onModel = () => {
  form.task_type = coerceTaskType(currentModel.value, form.task_type)
  if (form.task_type === 'classification') form.log_target = false
  if (preset.value === 'custom') preset.value = 'balanced'
  applyPreset(preset.value)
}

function colLabel(c) {
  return columnLabels.value[c] || headerLabel(c)
}

const applyRuleGeneratedColumns = () => {
  const rule = rules.value.find(r => Number(r.id) === Number(form.rule_id))
  const generated = generatedColumnsFromSteps(rule?.steps || [])
  columns.value = [...new Set([...baseColumns.value, ...generated])]
  for (const col of generated) {
    if (col !== form.target_col && !form.feature_cols.includes(col)) form.feature_cols.push(col)
  }
}

const onRuleChange = () => {
  applyRuleGeneratedColumns()
}

const onSource = async (resetFeatures = true) => {
  if (!form.target_id) return
  if (form.target_type === 'binding') {
    form.binding_id = form.target_id
    const b = bindings.value.find(x => x.id === form.target_id)
    columns.value = b?.schema || []
    columnLabels.value = Object.fromEntries((columns.value || []).map(c => [c, headerLabel(c)]))
  } else {
    form.binding_id = null
    const api = form.target_type === 'bundle' ? previewBundle : previewDataset
    const res = await api(form.target_id)
    baseColumns.value = res.data.columns || []
    columns.value = [...baseColumns.value]
    columnLabels.value = res.data.column_labels || {}
  }
  if (form.target_type === 'binding') baseColumns.value = [...columns.value]
  else applyRuleGeneratedColumns()
  if (resetFeatures) {
    if (!form.target_col || !columns.value.includes(form.target_col)) {
      form.target_col = ['price_da', 'wind_mw', 'solar_mw', 'load_mw', 'renewable_mw', 'Sales']
        .find(c => columns.value.includes(c)) || columns.value[0]
    }
    form.feature_cols = featureColsForTarget(columns.value, form.target_col)
  }
}

const trainPayload = () => {
  const payload = {
    name: form.name,
    scenario_code: userStore.scenario,
    target_type: form.target_type,
    target_id: form.target_id,
    rule_id: form.rule_id,
    binding_id: form.binding_id,
    target_col: form.target_col,
    feature_cols: form.feature_cols,
    task_type: form.task_type,
    model_type: form.model_type,
    params: form.params,
    param_preset: preset.value,
    sample_rows: form.sample_rows,
    test_size: form.test_size,
    random_state: form.random_state,
    log_target: form.log_target
  }
  if (form.target_type === 'binding') {
    const b = bindings.value.find(x => x.id === form.target_id)
    payload.target_type = b?.target_type || 'bundle'
    payload.target_id = b?.target_id
    payload.binding_id = form.target_id
    payload.rule_id = null
  } else if (form.target_type === 'live') {
    payload.target_type = 'dataset'
  }
  return payload
}

const start = async () => {
  if (!form.target_id) return ElMessage.warning('请选择数据源')
  starting.value = true
  try {
    const res = await startTrain(trainPayload())
    ElMessage.success('训练已开始')
    insightText.value = ''
    job.value = res.data
    if (res.data?.id) await router.replace(`/train/${res.data.id}`)
  } finally {
    starting.value = false
  }
}

const bindChart = (el, key, option) => {
  if (!el) return
  if (!chartMap[key]) chartMap[key] = echarts.init(el)
  else chartMap[key].resize()
  chartMap[key].setOption(option, true)
}

const residualHist = () => {
  const hist = job.value?.curves?.residual_hist
  if (hist?.counts?.length) return hist
  const actual = job.value?.curves?.actual || []
  const pred = job.value?.curves?.pred || []
  if (!actual.length || pred.length !== actual.length) return null
  const residuals = actual.map((v, i) => Number(pred[i]) - Number(v))
  const min = Math.min(...residuals)
  const max = Math.max(...residuals)
  const n = Math.min(24, Math.max(8, Math.round(Math.sqrt(residuals.length))))
  const step = (max - min) / n || 1
  const counts = Array(n).fill(0)
  const bins = Array.from({ length: n + 1 }, (_, i) => min + i * step)
  residuals.forEach((v) => {
    let idx = Math.floor((v - min) / step)
    if (idx >= n) idx = n - 1
    if (idx < 0) idx = 0
    counts[idx] += 1
  })
  return { bins, counts }
}

const axisNameStyle = { color: '#475569', fontSize: 11 }
const METRIC_CN = {
  error: '分类错误率',
  rmse: 'RMSE',
  mae: 'MAE',
  logloss: '对数损失 LogLoss',
  binary_logloss: '对数损失 LogLoss',
  mlogloss: '多分类 LogLoss',
  loss: '训练损失'
}

const renderCharts = async () => {
  await nextTick()
  if (!job.value || job.value.status !== 'success') return
  const chartStyle = { color: '#1a2433', fontSize: 13, fontWeight: 600 }
  const yTarget = axisCaption(job.value.target_col)
  if (impRef.value) {
    const imp = (job.value.importance || []).slice(0, 12).reverse()
    bindChart(impRef.value, 'imp', {
      backgroundColor: 'transparent',
      title: { text: '特征重要性', textStyle: chartStyle },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 176, right: 20, top: 36, bottom: 40 },
      xAxis: {
        type: 'value',
        name: '重要性得分（模型增益，无量纲）',
        nameLocation: 'middle',
        nameGap: 26,
        nameTextStyle: axisNameStyle,
        axisLabel: { color: '#64748b' },
        splitLine: { lineStyle: { color: '#e8eef5' } }
      },
      yAxis: {
        type: 'category',
        name: '输入特征',
        nameLocation: 'middle',
        nameGap: 156,
        nameTextStyle: axisNameStyle,
        data: imp.map(i => featureTick(i.feature)),
        axisLabel: { color: '#334155', fontSize: 11 }
      },
      series: [{ type: 'bar', data: imp.map(i => i.score), color: '#1d6fd8', barWidth: 14, itemStyle: { borderRadius: [0, 4, 4, 0] } }]
    })
  }
  if (curveRef.value && job.value.curves) {
    const n = (job.value.curves.actual || []).length
    bindChart(curveRef.value, 'curve', {
      backgroundColor: 'transparent',
      title: { text: '验证集抽样：实际 vs 预测', textStyle: chartStyle },
      tooltip: { trigger: 'axis' },
      legend: { data: ['实际', '预测'], textStyle: { color: '#64748b' } },
      grid: { left: 62, right: 16, top: 48, bottom: 44 },
      xAxis: {
        type: 'category',
        name: '验证样本序号（hold-out 抽样，不是时间）',
        nameLocation: 'middle',
        nameGap: 28,
        nameTextStyle: axisNameStyle,
        data: Array.from({ length: n }, (_, i) => String(i + 1)),
        axisLabel: { color: '#64748b' }
      },
      yAxis: {
        type: 'value',
        name: yTarget,
        nameLocation: 'middle',
        nameGap: 42,
        nameTextStyle: axisNameStyle,
        splitLine: { lineStyle: { color: '#e8eef5' } },
        axisLabel: { color: '#64748b' }
      },
      series: [
        { name: '实际', type: 'line', data: job.value.curves.actual, color: '#c2410c', smooth: true },
        { name: '预测', type: 'line', data: job.value.curves.pred, color: '#1d6fd8', smooth: true }
      ]
    })
  }
  if (histTrainRef.value) {
    const history = job.value.curves?.history || {}
    const train = history.train || []
    const valid = history.valid || []
    const metricKey = String(history.metric || 'rmse').toLowerCase()
    const metric = METRIC_CN[metricKey] || (metricKey === 'error' ? '分类错误率' : String(history.metric || 'RMSE').toUpperCase())
    const space = history.space === 'log1p' ? 'log1p 拟合空间，越小越好' : '原始量纲，越小越好'
    const xName = history.x_name === 'n_estimators'
      ? '树的数量（n_estimators）'
      : (history.x_name === 'tree_depth' || history.x_name === 'max_depth')
        ? '树深度（max_depth）'
        : (history.x_name === 'svm_C' || history.x_name === 'C')
          ? '正则系数 C'
          : history.x_name === 'alpha'
            ? '正则强度 alpha'
            : history.x_name === 'n_samples'
              ? '训练样本数'
              : history.x_name === 'epoch'
                ? '训练轮次（epoch）'
                : '训练轮次（iteration）'
    const n = Math.max(train.length, valid.length)
    const xs = (history.x && history.x.length) ? history.x : Array.from({ length: n }, (_, i) => i + 1)
    bindChart(histTrainRef.value, 'histTrain', train.length || valid.length ? {
      backgroundColor: 'transparent',
      title: { text: `训练过程 ${metric}`, textStyle: chartStyle },
      tooltip: { trigger: 'axis' },
      legend: { data: ['训练集', '验证集'].filter((_, i) => (i === 0 ? train.length : valid.length)), textStyle: { color: '#64748b' } },
      grid: { left: 62, right: 16, top: 48, bottom: 44 },
      xAxis: {
        type: 'category',
        name: xName,
        nameLocation: 'middle',
        nameGap: 28,
        nameTextStyle: axisNameStyle,
        data: xs,
        axisLabel: { color: '#64748b' }
      },
      yAxis: {
        type: 'value',
        name: `${metric}（${space}）`,
        nameLocation: 'middle',
        nameGap: 42,
        nameTextStyle: axisNameStyle,
        splitLine: { lineStyle: { color: '#e8eef5' } },
        axisLabel: { color: '#64748b' }
      },
      series: [
        train.length ? { name: '训练集', type: 'line', data: train, color: '#0f766e', smooth: true, showSymbol: false } : null,
        valid.length ? { name: '验证集', type: 'line', data: valid, color: '#1d6fd8', smooth: true, showSymbol: false } : null
      ].filter(Boolean)
    } : {
      backgroundColor: 'transparent',
      title: { text: '训练过程曲线', textStyle: chartStyle },
      graphic: { type: 'text', left: 'center', top: 'middle', style: { text: '暂无训练过程记录\n重新训练后出现（提升树记轮次，线性模型记正则/样本量，Softmax/BERT 记 epoch）', fill: '#94a3b8', fontSize: 13, textAlign: 'center' } }
    })
  }
  if (histRef.value) {
    const hist = residualHist()
    const counts = hist?.counts || []
    const bins = hist?.bins || []
    const labels = counts.map((_, i) => {
      const a = Number(bins[i])
      const b = Number(bins[i + 1])
      if (Number.isFinite(a) && Number.isFinite(b)) return ((a + b) / 2).toFixed(2)
      return String(i)
    })
    bindChart(histRef.value, 'hist', counts.length ? {
      backgroundColor: 'transparent',
      title: { text: '残差分布（预测 − 实际）', textStyle: chartStyle },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 56, right: 16, top: 36, bottom: 52 },
      xAxis: {
        type: 'category',
        name: `残差 = 预测 − 实际（${yTarget}）`,
        nameLocation: 'middle',
        nameGap: 36,
        nameTextStyle: axisNameStyle,
        data: labels,
        axisLabel: { color: '#64748b', fontSize: 10, rotate: 40 }
      },
      yAxis: {
        type: 'value',
        name: '样本频数（个）',
        nameLocation: 'middle',
        nameGap: 36,
        nameTextStyle: axisNameStyle,
        splitLine: { lineStyle: { color: '#e8eef5' } },
        axisLabel: { color: '#64748b' }
      },
      series: [{ type: 'bar', data: counts, color: '#1d6fd8', barWidth: '70%', itemStyle: { borderRadius: [3, 3, 0, 0] } }]
    } : {
      backgroundColor: 'transparent',
      title: { text: '残差分布（预测 − 实际）', textStyle: chartStyle },
      graphic: { type: 'text', left: 'center', top: 'middle', style: { text: '暂无残差样本', fill: '#94a3b8', fontSize: 13 } }
    })
  }
}

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

const packFilename = (row) => {
  const name = String(row?.name || '训练任务').replace(/[\\/:*?"<>|]+/g, '_').replace(/\s+/g, '_').slice(0, 40)
  const model = String(row?.model_type || 'model').replace(/[^\w-]+/g, '_')
  return `实验材料_${name}_${model}_#${row.id}.zip`
}

const downloadPack = async () => {
  if (!job.value?.id) return
  exporting.value = true
  try {
    const res = await exportTrainPack(job.value.id)
    saveBlob(res.data, packFilename(job.value))
    ElMessage.success('已导出实验材料（含种子、参数、指标、图表、局限说明）')
  } finally {
    exporting.value = false
  }
}

const downloadInsight = async (fmt = 'md') => {
  if (!job.value?.id || !insightText.value) return ElMessage.warning('请先生成 LLM 洞察')
  if (job.value.insight_id) {
    const res = await exportInsightById(job.value.insight_id, fmt)
    saveBlob(res.data, insightExportFilename({
      id: job.value.insight_id,
      train_name: job.value.name,
      model_type: job.value.model_type,
      target_col: job.value.target_col,
      create_time: job.value.create_time
    }, fmt))
    ElMessage.success(fmt === 'docx' ? '已导出 Word' : '已导出 Markdown')
    return
  }
  if (fmt === 'docx') return ElMessage.warning('请重新生成洞察后再导出 Word')
  try {
    const res = await exportInsightMd(job.value.id)
    saveBlob(res.data, insightExportFilename({ ...job.value, id: `job-${job.value.id}` }, 'md'))
    ElMessage.success('已导出洞察 Markdown')
  } catch {
    const blob = new Blob([insightText.value], { type: 'text/markdown;charset=utf-8' })
    saveBlob(blob, insightExportFilename({ ...job.value, id: `job-${job.value.id}` }, 'md'))
  }
}

const runInsight = async () => {
  if (!job.value?.id) return
  insighting.value = true
  try {
    const payload = {
      train_job_id: job.value.id,
      use_rag: insightForm.use_rag
    }
    if (insightForm.llm_config_id) payload.llm_config_id = insightForm.llm_config_id
    const pid = insightForm.prompt_id
    if (pid && pid !== CUSTOM_PICK && pid !== EMPTY_PICK) payload.prompt_id = pid
    const sys = (insightForm.system_prompt || '').trim()
    if (sys) payload.system_prompt = sys
    const q = (insightForm.question || '').trim()
    if (q) payload.question = q
    const res = await createInsight(payload)
    insightText.value = res.data.content || ''
    if (job.value) {
      job.value.insight = insightText.value
      job.value.insight_title = res.data.title || job.value.insight_title
      job.value.insight_id = res.data.id
    }
    insightDialog.value = false
    ElMessage.success('洞察报告已生成，可导出 Markdown')
  } finally {
    insighting.value = false
  }
}

const genInsight = () => openInsightDialog()

const goPredict = () => {
  if (!job.value?.id) return
  router.push({ path: '/predict', query: { job_id: String(job.value.id) } })
}

const removeJob = async () => {
  if (!job.value?.id) return
  try {
    await ElMessageBox.confirm(
      running.value
        ? `「${job.value.name}」仍在训练中，删除后记录会消失。确定删除？`
        : `删除训练记录「${job.value.name}」？模型文件会一并删除。`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  await deleteJob(job.value.id)
  ElMessage.success('已删除')
  router.push('/train')
}

const applyJobToForm = async (data) => {
  form.name = data.name || ''
  form.model_type = data.model_type || form.model_type
  form.params = data.params && Object.keys(data.params).length ? { ...data.params } : form.params
  delete form.params._preset
  form.params = fillParamDefaults(currentModel.value, form.params)
  preset.value = resolveParamPreset(currentModel.value, form.params, data.param_preset)
  form.target_col = data.target_col || form.target_col
  form.feature_cols = data.feature_cols || []
  form.sample_rows = data.sample_rows ?? 40000
  form.test_size = Number(data.test_size || 0.2)
  form.random_state = Number(data.random_state || 42)
  form.log_target = !!data.log_target
  form.task_type = coerceTaskType(zoo.value.find(m => m.key === form.model_type), data.task_type || 'regression')
  if (form.task_type === 'classification') form.log_target = false
  form.rule_id = data.rule_id || null
  const liveOf = (id) => datasets.value.find(d => Number(d.id) === Number(id) && isLiveDataset(d))
  if (data.binding_id) {
    const b = bindings.value.find(x => Number(x.id) === Number(data.binding_id))
    const live = liveOf(b?.target_id) || liveOf(data.target_id)
    if (live) {
      form.target_type = 'live'
      form.target_id = live.id
      form.binding_id = null
      form.rule_id = data.rule_id || b?.rule_id || form.rule_id
    } else {
      form.target_type = 'binding'
      form.target_id = data.binding_id
      form.binding_id = data.binding_id
    }
  } else {
    const live = liveOf(data.target_id)
    form.target_type = live ? 'live' : (data.target_type || 'bundle')
    form.target_id = data.target_id || null
    form.binding_id = null
  }
  if (form.target_id) await onSource(false)
}

const refreshJob = async () => {
  if (isNew.value || !route.params.id) return
  const res = await getJob(route.params.id)
  job.value = res.data
  if (res.data?.insight) insightText.value = res.data.insight
}

watch(job, renderCharts)
watch(() => form.task_type, (t) => {
  if (t === 'classification') form.log_target = false
})
watch(() => form.target_type, () => {
  if (booting.value) return
  form.target_id = null
  baseColumns.value = []
  columns.value = []
  columnLabels.value = {}
})

const boot = async () => {
  booting.value = true
  try {
    const reqs = [getZoo(), listRules(), listDatasets(), listBundles(), listBindings()]
    if (!isNew.value) reqs.push(getJob(route.params.id))
    const [z, r, d, b, bd, j] = await Promise.all(reqs)
    zoo.value = z.data || []
    rules.value = unwrapList(r)
    datasets.value = unwrapList(d)
    bundles.value = unwrapList(b)
    bindings.value = unwrapList(bd)
    form.model_type = zoo.value.find(m => m.available && m.key === 'xgboost')?.key
      || zoo.value.find(m => m.available)?.key
      || form.model_type
    if (isNew.value) {
      applyPreset()
      job.value = null
      insightText.value = ''
      if (bundles.value[0]) {
        form.target_id = bundles.value[0].id
        await onSource(true)
      }
      return
    }
    job.value = j?.data
    if (!job.value) {
      ElMessage.error('训练任务不存在')
      router.push('/train')
      return
    }
    insightText.value = job.value.insight || ''
    await applyJobToForm(job.value)
  } finally {
    booting.value = false
  }
}

watch(() => route.params.id, (id, prev) => {
  if (id && id !== prev) boot()
})

onMounted(async () => {
  await boot()
  timer = setInterval(async () => {
    if (!running.value && job.value?.status !== 'pending') return
    await refreshJob()
  }, 1500)
})
onUnmounted(() => {
  timer && clearInterval(timer)
  Object.values(chartMap).forEach((c) => c.dispose())
})
</script>

<style scoped>
.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.tip { color: var(--muted); font-size: 12px; margin: 0 0 8px 108px; }
.field-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.placeholder {
  min-height: 220px;
  display: flex;
  align-items: center;
  color: var(--muted);
  line-height: 1.7;
}
.log {
  max-height: 180px;
  overflow: auto;
  background: var(--panel-soft);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  color: var(--muted);
  margin-top: 12px;
}
.insight-box {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.insight-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
</style>
