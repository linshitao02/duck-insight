<template>
  <div>
    <div class="page-head">
      <div>
        <h2>清洗规则</h2>
        <p>在画布上拖拉拽组件编排清洗流水线，从节点右端口拉线接到下一节点，点节点从底部弹出具体配置，再绑定到原始表或逻辑数据集。</p>
      </div>
      <el-button type="primary" @click="$router.push('/clean/rule/new')">新建规则</el-button>
    </div>

    <el-row :gutter="16">
      <el-col :md="14">
        <el-card shadow="never">
          <template #header>规则库</template>
          <el-table :data="rules">
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="场景" width="120">
              <template #default="{ row }">{{
                ({ store_sales: '商店销售', power_trading: '电力交易', generic: '通用' })[row.scenario_code] || row.scenario_code
              }}</template>
            </el-table-column>
            <el-table-column label="步骤数" width="80">
              <template #default="{ row }">{{ (row.steps || []).length }}</template>
            </el-table-column>
            <el-table-column label="操作" width="300">
              <template #default="{ row }">
                <el-button link type="primary" @click="$router.push(`/clean/rule/${row.id}`)">编辑</el-button>
                <el-button link type="primary" @click="copyOne(row)">复制</el-button>
                <el-button link type="success" @click="openBind(row)">绑定数据</el-button>
                <el-button link type="danger" :disabled="row.is_preset" @click="removeRule(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <ListPager
            v-model:page="rulePage"
            v-model:pageSize="rulePageSize"
            :total="ruleTotal"
            @change="onRulePager"
          />
        </el-card>
      </el-col>
      <el-col :md="10">
        <el-card shadow="never">
          <template #header>
            <div class="bind-head">
              <span>已绑定快照</span>
              <el-button
                size="small"
                type="danger"
                plain
                :disabled="!pickedBinds.length"
                @click="removePickedBinds"
              >删除所选{{ pickedBinds.length ? `（${pickedBinds.length}）` : '' }}</el-button>
            </div>
          </template>
          <p class="bind-tip">
            每条快照 = 一条清洗规则 + 一个数据源，物化后的成品表。训练任务、BI 看板可直接读它，省去每次重跑清洗。
          </p>
          <div class="bind-filter">
            <el-switch
              v-model="showTransient"
              size="small"
              active-text="显示流程临时产物"
              @change="onTransientToggle"
            />
            <span v-if="showTransient" class="bind-filter-hint">
              这些是流程跑批时产生的中间绑定，没落盘 CSV；预览/下载会按清洗状态现场重算，较慢。
            </span>
          </div>
          <el-table :data="bindings" size="small" v-loading="bindLoading" @selection-change="onBindSelect">
            <el-table-column type="selection" width="42" />
            <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.name }}
                <el-tag v-if="row.used_count" size="small" type="warning" effect="plain">{{ row.used_count }} 处引用</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="来源" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.source_name || `${row.target_type} #${row.target_id}` }}
              </template>
            </el-table-column>
            <el-table-column label="规则" min-width="110" show-overflow-tooltip>
              <template #default="{ row }">{{ row.rule_name || '规则已删除' }}</template>
            </el-table-column>
            <el-table-column prop="n_rows" label="行" width="72" />
            <el-table-column label="快照" width="92">
              <template #default="{ row }">
                <el-tag v-if="row.has_snapshot" size="small" type="success" effect="plain">{{ fileSize(row.snapshot_size) }}</el-tag>
                <el-tooltip v-else-if="row.can_rebuild" content="流程内临时产物，没有落盘 CSV；预览/下载会按清洗状态现场重算" placement="top">
                  <el-tag size="small" type="warning" effect="plain">临时·可重算</el-tag>
                </el-tooltip>
                <el-tooltip v-else content="流程内临时产物，既无快照文件也无可用清洗状态，只能删除" placement="top">
                  <el-tag size="small" type="info" effect="plain">无文件</el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="时间" width="130">
              <template #default="{ row }">{{ fmtTime(row.create_time) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :disabled="!row.can_view" @click="openPreview(row)">预览</el-button>
                <el-button link type="primary" :disabled="!row.can_view" @click="downloadSnap(row)">下载</el-button>
                <el-button link type="danger" @click="removeBind(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <ListPager
            v-model:page="bindPage"
            v-model:pageSize="bindPageSize"
            :total="bindTotal"
            :page-sizes="[10, 20, 50]"
            @change="onBindPager"
          />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog
      v-model="peek.visible"
      :title="`快照预览 · ${peek.row?.name || ''}`"
      width="88%"
      top="5vh"
      destroy-on-close
      @opened="loadPeek"
    >
      <div class="peek-bar">
        <el-descriptions :column="4" size="small" border>
          <el-descriptions-item label="来源">{{ peek.row?.source_name || `${peek.row?.target_type} #${peek.row?.target_id}` }}</el-descriptions-item>
          <el-descriptions-item label="清洗规则">{{ peek.row?.rule_name || '规则已删除' }}</el-descriptions-item>
          <el-descriptions-item label="快照尺寸">{{ peek.row?.n_rows }} 行 × {{ peek.row?.n_cols }} 列</el-descriptions-item>
          <el-descriptions-item label="文件">{{ peek.row?.has_snapshot ? fileSize(peek.row?.snapshot_size) : '未落盘（现场重算）' }}</el-descriptions-item>
        </el-descriptions>
        <p v-if="peek.row?.message" class="peek-log">清洗摘要：{{ peek.row.message }}</p>
        <p v-if="peek.row?.used_count" class="peek-log warn">
          正被 {{ peek.row.used_count }} 处引用：{{ (peek.row.used_by || []).map(u => u.name).join('、') }}
        </p>
      </div>
      <el-table
        v-loading="peek.loading"
        :data="peek.records"
        size="small"
        border
        stripe
        max-height="440"
        :empty-text="peek.error || '暂无数据'"
      >
        <el-table-column type="index" label="#" width="64">
          <template #default="{ $index }">{{ peek.row_nos[$index] || $index + 1 }}</template>
        </el-table-column>
        <el-table-column
          v-for="col in peek.columns"
          :key="col"
          :prop="col"
          :label="colLabel(col)"
          min-width="128"
          show-overflow-tooltip
        />
      </el-table>
      <ListPager
        v-if="peek.total > peek.pageSize"
        v-model:page="peek.page"
        v-model:pageSize="peek.pageSize"
        :total="peek.total"
        :page-sizes="[20, 50, 100, 200]"
        @change="onPeekPager"
      />
      <template #footer>
        <span class="peek-count">共 {{ peek.total }} 行</span>
        <el-button @click="peek.visible = false">关闭</el-button>
        <el-button type="primary" plain :disabled="!peek.row?.can_view" @click="downloadSnap(peek.row)">下载 CSV</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="binder.visible" title="绑定清洗规则" width="520px">
      <el-form label-width="100px">
        <el-form-item label="数据集配置">
          <el-select v-model="binder.projectId" filterable style="width: 100%" @change="loadBinderSources">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据源类型">
          <el-select v-model="binder.targetType" @change="onBinderTypeChange">
            <el-option label="逻辑数据集" value="bundle" />
            <el-option label="原始数据集" value="dataset" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据源">
          <el-select v-model="binder.targetId" filterable style="width: 100%">
            <el-option v-for="item in binderSources" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="binder.visible = false">取消</el-button>
        <el-button type="primary" :loading="binder.loading" @click="doBind">绑定并物化</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import Cookies from 'js-cookie'
import { useUserStore } from '@/stores/user'
import {
  listRules, copyRule, deleteRule, bindRule, listBindings, deleteBinding,
  previewBinding, listProjects, listDatasets, listBundles
} from '@/api'
import ListPager from '@/components/ListPager.vue'
import { unwrapList, unwrapPage } from '@/utils/paging'
import { headerLabel } from '@/utils/fieldLabels'

const router = useRouter()
const userStore = useUserStore()
const rules = ref([])
const bindings = ref([])
const rulePage = ref(1)
const rulePageSize = ref(10)
const ruleTotal = ref(0)
const bindPage = ref(1)
const bindPageSize = ref(10)
const bindTotal = ref(0)
const projects = ref([])
const datasets = ref([])
const bundles = ref([])
const bindLoading = ref(false)
const pickedBinds = ref([])
const showTransient = ref(false)
const peek = reactive({
  visible: false,
  loading: false,
  row: null,
  records: [],
  columns: [],
  row_nos: [],
  total: 0,
  page: 1,
  pageSize: 50,
  error: ''
})
const binder = reactive({
  visible: false,
  ruleId: null,
  projectId: null,
  targetType: 'bundle',
  targetId: null,
  loading: false
})

const binderSources = computed(() =>
  binder.targetType === 'bundle' ? bundles.value : datasets.value
)

const loadRules = async () => {
  const packed = unwrapPage(await listRules({ page: rulePage.value, page_size: rulePageSize.value }))
  rules.value = packed.items
  ruleTotal.value = packed.total
  if (!rules.value.length && ruleTotal.value > 0 && rulePage.value > 1) {
    rulePage.value -= 1
    return loadRules()
  }
}

const loadBindings = async () => {
  bindLoading.value = true
  try {
    const packed = unwrapPage(await listBindings({
      page: bindPage.value,
      page_size: bindPageSize.value,
      include_transient: showTransient.value ? 1 : 0
    }))
    bindings.value = packed.items
    bindTotal.value = packed.total
    const ids = new Set(bindings.value.map(r => r.id))
    pickedBinds.value = pickedBinds.value.filter(r => ids.has(r.id))
    if (!bindings.value.length && bindTotal.value > 0 && bindPage.value > 1) {
      bindPage.value -= 1
      return loadBindings()
    }
  } finally {
    bindLoading.value = false
  }
}

const onTransientToggle = () => {
  bindPage.value = 1
  pickedBinds.value = []
  loadBindings()
}

const load = async () => {
  const [, , pj] = await Promise.all([
    loadRules(),
    loadBindings(),
    listProjects()
  ])
  projects.value = unwrapList(pj)
}

const onRulePager = ({ page: p, pageSize: s }) => {
  rulePage.value = p
  rulePageSize.value = s
  loadRules()
}

const onBindPager = ({ page: p, pageSize: s }) => {
  bindPage.value = p
  bindPageSize.value = s
  loadBindings()
}

const loadBinderSources = async () => {
  if (!binder.projectId) {
    datasets.value = []
    bundles.value = []
    binder.targetId = null
    return
  }
  const [ds, bd] = await Promise.all([
    listDatasets({ project_id: binder.projectId }),
    listBundles({ project_id: binder.projectId })
  ])
  datasets.value = unwrapList(ds)
  bundles.value = unwrapList(bd)
  binder.targetId = binderSources.value[0]?.id || null
}

const onBinderTypeChange = () => {
  binder.targetId = binderSources.value[0]?.id || null
}

const openBind = async (row) => {
  binder.ruleId = row.id
  binder.targetType = 'bundle'
  binder.projectId = projects.value[0]?.id || null
  binder.visible = true
  await loadBinderSources()
}

const doBind = async () => {
  if (!binder.targetId) return ElMessage.warning('请选择数据源')
  binder.loading = true
  try {
    await bindRule({
      target_type: binder.targetType,
      target_id: binder.targetId,
      rule_id: binder.ruleId
    })
    ElMessage.success('绑定完成')
    binder.visible = false
    load()
  } finally {
    binder.loading = false
  }
}

const copyOne = async (row) => {
  const res = await copyRule(row.id)
  ElMessage.success('已复制规则')
  if (res.data?.id) {
    router.push(`/clean/rule/${res.data.id}`)
    return
  }
  load()
}

const removeRule = async (row) => {
  await ElMessageBox.confirm('删除该规则？')
  await deleteRule(row.id)
  load()
}

const fmtTime = (t) => {
  if (!t) return ''
  const s = String(t).replace('T', ' ')
  return s.length > 16 ? s.slice(0, 16) : s
}
const fileSize = (bytes) => {
  const n = Number(bytes || 0)
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
const colLabel = (col) => headerLabel(col, '')

const onBindSelect = (rows) => {
  pickedBinds.value = rows || []
}

const openPreview = (row) => {
  peek.row = row
  peek.page = 1
  peek.records = []
  peek.columns = []
  peek.row_nos = []
  peek.total = Number(row?.n_rows || 0)
  peek.error = ''
  peek.visible = true
}

const loadPeek = async () => {
  if (!peek.row?.id) return
  peek.loading = true
  peek.error = ''
  try {
    const res = await previewBinding(peek.row.id, { n: peek.pageSize, skip: (peek.page - 1) * peek.pageSize })
    peek.records = res.data?.records || []
    peek.columns = res.data?.columns || []
    peek.row_nos = res.data?.row_nos || []
    peek.total = Number(res.data?.n_rows || peek.total || 0)
  } catch (e) {
    peek.error = e?.message || '预览失败'
    peek.records = []
  } finally {
    peek.loading = false
  }
}

const onPeekPager = ({ page, pageSize }) => {
  peek.page = page
  peek.pageSize = pageSize
  loadPeek()
}

const downloadSnap = (row) => {
  if (!row?.id) return
  if (!row.can_view) return ElMessage.warning('这条绑定没有快照文件，也没有可用的清洗状态，无法下载')
  if (!row.has_snapshot) ElMessage.info('该绑定没有落盘 CSV，正在按清洗状态现场重算，请稍候…')
  const token = Cookies.get('token')
  window.open(`/api/clean/bind/${row.id}/download?token=${token}`)
}

const confirmRemoveBind = async (row) => {
  const used = Number(row?.used_count || 0)
  const who = (row?.used_by || []).map(u => u.name).join('、')
  const extra = used
    ? `\n\n注意：正被 ${used} 处引用（${who}），删除后这些训练 / 看板可能读不到数据。`
    : ''
  try {
    await ElMessageBox.confirm(
      `删除快照「${row.name}」？快照文件与清洗状态会一并删除，不可恢复。${extra}`,
      used ? '该快照正在被引用' : '删除清洗快照',
      { type: used ? 'error' : 'warning', confirmButtonText: used ? '仍然删除' : '确定', dangerouslyUseHTMLString: false }
    )
  } catch {
    return false
  }
  return true
}

const removeBind = async (row) => {
  if (!(await confirmRemoveBind(row))) return
  try {
    await deleteBinding(row.id, Number(row.used_count || 0) > 0)
    ElMessage.success('已删除')
    if (peek.row?.id === row.id) peek.visible = false
    load()
  } catch (e) {
    // 引用校验失败时后端会返回原因，这里不再重复提示
  }
}

const removePickedBinds = async () => {
  const rows = pickedBinds.value.filter(r => r?.id)
  if (!rows.length) return ElMessage.warning('请先勾选要删除的快照')
  const usedCount = rows.filter(r => Number(r.used_count || 0) > 0).length
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${rows.length} 条快照？快照文件会一并删除，不可恢复。` +
      (usedCount ? `其中 ${usedCount} 条正在被训练 / 看板引用。` : ''),
      '批量删除清洗快照',
      { type: usedCount ? 'error' : 'warning' }
    )
  } catch {
    return
  }
  let done = 0
  let blocked = 0
  for (const row of rows) {
    try {
      await deleteBinding(row.id, Number(row.used_count || 0) > 0)
      done += 1
    } catch {
      blocked += 1
    }
  }
  if (done) ElMessage.success(`已删除 ${done} 条`)
  if (blocked) ElMessage.warning(`${blocked} 条被引用，未删除`)
  pickedBinds.value = []
  load()
}

onMounted(load)
</script>

<style scoped>
.bind-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.bind-tip {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.6;
}
.bind-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 0 0 10px;
}
.bind-filter-hint {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.peek-bar { margin-bottom: 12px; }
.peek-log {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.6;
}
.peek-log.warn { color: #c2410c; }
.peek-count {
  float: left;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 32px;
}
</style>
