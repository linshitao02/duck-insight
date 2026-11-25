<template>
  <div v-loading="booting">
    <div class="page-head">
      <div>
        <el-button link type="primary" @click="$router.push('/dataset')">← 返回数据集配置</el-button>
        <h2>{{ project.name || '数据集工作区' }}</h2>
        <p>在本数据集配置下上传文件或从数据源导入多张表，配置字段，再做多表关联。</p>
      </div>
      <div class="head-actions">
        <el-button v-if="(project.scenario_code || userStore.scenario) === 'power_trading'" @click="doPowerDemo" :loading="demoLoading">导入极端天气电力样本</el-button>
        <el-button v-else @click="doDemo" :loading="demoLoading">一键导入 Rossmann 示例</el-button>
        <el-button type="primary" :disabled="selectedIds.length < 2" @click="goWeave()">
          配置多表关联（已选 {{ selectedIds.length }}）
        </el-button>
      </div>
    </div>

    <section class="block-card panel">
      <div class="card-head">
        <div>
          <strong>数据集任务</strong>
          <span class="sub">每个方块是一张表，点进去上传并配置字段</span>
        </div>
      </div>

      <div class="task-grid">
        <button type="button" class="task-square add-square" @click="goNew">
          <span class="plus">+</span>
          <span class="add-title">新建数据表</span>
          <span class="add-desc">上传文件或从库导入</span>
        </button>

        <div
          v-for="row in pagedDatasets"
          :key="row.id"
          class="task-square"
          :class="{ selected: selectedIds.includes(row.id) }"
          @click="goTask(row)"
        >
          <label class="pick" @click.stop>
            <el-checkbox
              :model-value="selectedIds.includes(row.id)"
              @change="(v) => toggleSelect(row.id, v)"
            />
          </label>
          <button type="button" class="del" title="删除" @click.stop="removeDs(row)">×</button>
          <div class="sq-icon">{{ (row.name || 'D').slice(0, 1) }}</div>
          <div class="sq-name" :title="row.name">{{ row.name }}</div>
          <div class="sq-meta">
            <el-tag v-if="row.origin_type === 'mysql_live'" size="small" type="success" style="margin-right: 4px">实时</el-tag>
            {{ row.origin_type === 'mysql_live' ? `${row.source_db}.${row.source_table}` : (row.filename || '未上传') }}
          </div>
          <div class="sq-stats">
            <span>{{ row.n_rows || 0 }} 行</span>
            <span>{{ row.n_cols || 0 }} 列</span>
          </div>
          <div class="sq-foot">
            <el-tag v-if="targetOf(row)" size="small" type="warning">{{ targetOf(row) }}</el-tag>
            <span v-else class="muted">未设目标</span>
          </div>
        </div>
      </div>
      <ListPager
        v-model:page="dsPage"
        v-model:pageSize="dsPageSize"
        :total="datasets.length"
        @change="onDsPager"
      />
    </section>

    <section class="block-card panel">
      <div class="card-head">
        <div>
          <strong>逻辑数据集（多表关联结果）</strong>
          <span class="sub">勾选上方至少 2 张表后进入页面配置关联与展示字段</span>
        </div>
        <el-button type="primary" plain @click="goWeave()" :disabled="datasets.length < 2">新建关联</el-button>
      </div>

      <div v-if="!bundles.length" class="empty-hint">暂无逻辑数据集，勾选表后点击「新建关联」</div>
      <div v-else class="bundle-grid">
        <div v-for="row in pagedBundles" :key="row.id" class="bundle-card">
          <div class="bundle-name">{{ row.name }}</div>
          <div class="sq-stats">
            <span>{{ row.n_rows }} 行</span>
            <span>{{ row.n_cols }} 列</span>
          </div>
          <div class="join-lines">
            <div v-for="(j, i) in (row.joins || [])" :key="i" class="join-line">
              {{ nameOf(j.left_dataset_id) }}
              <span class="how">{{ j.how || 'left' }}</span>
              {{ nameOf(j.right_dataset_id) }}
              ：{{ joinKeyText(j) }}
            </div>
          </div>
          <div class="bundle-actions">
            <el-button link type="primary" @click="goWeave(row)">配置关联</el-button>
            <el-button link type="primary" @click="openBundle(row)">预览</el-button>
            <el-button link type="danger" @click="removeBundle(row)">删除</el-button>
          </div>
        </div>
      </div>
      <ListPager
        v-if="bundles.length"
        v-model:page="bundlePage"
        v-model:pageSize="bundlePageSize"
        :total="bundles.length"
        @change="onBundlePager"
      />
    </section>

    <el-drawer v-model="preview.visible" size="68%" :title="preview.title">
      <el-table :data="preview.records" size="small" max-height="520" stripe>
        <el-table-column
          v-for="col in preview.columns"
          :key="col"
          :prop="col"
          :label="preview.labels[col] || columnHeader(col, datasets, { factId: preview.factId })"
          min-width="150"
          show-overflow-tooltip
        />
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import {
  getProject, listDatasets, listBundles, previewBundle,
  deleteDataset, deleteBundle, importDemo, importExtremeWeather
} from '@/api'
import { columnHeader } from '@/utils/fieldLabels'
import ListPager from '@/components/ListPager.vue'
import { slicePage, unwrapList } from '@/utils/paging'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const projectId = computed(() => Number(route.params.projectId))
const project = ref({})
const datasets = ref([])
const bundles = ref([])
const dsPage = ref(1)
const dsPageSize = ref(10)
const bundlePage = ref(1)
const bundlePageSize = ref(10)
const selectedIds = ref([])
const demoLoading = ref(false)
const booting = ref(false)
const preview = reactive({ visible: false, title: '', records: [], columns: [], labels: {}, factId: null })

const nameOf = (id) => datasets.value.find(d => d.id === id)?.name || `#${id}`
const joinKeyText = (j) => {
  if (Array.isArray(j.keys) && j.keys.length) {
    return j.keys.map(k => k.left_key === k.right_key ? k.left_key : `${k.left_key}=${k.right_key}`).join(' AND ')
  }
  return j.left_key || ''
}
const targetOf = (row) => {
  const meta = row.profile?.meta?.target_col
  if (meta) return meta
  const col = (row.profile?.columns || []).find(c => c.role === 'target')
  return col?.name
}

const pagedDatasets = computed(() => slicePage(datasets.value, dsPage.value, dsPageSize.value))
const pagedBundles = computed(() => slicePage(bundles.value, bundlePage.value, bundlePageSize.value))

const onDsPager = ({ page: p, pageSize: s }) => {
  dsPage.value = p
  dsPageSize.value = s
}
const onBundlePager = ({ page: p, pageSize: s }) => {
  bundlePage.value = p
  bundlePageSize.value = s
}

const load = async () => {
  if (!projectId.value) return
  booting.value = true
  try {
    const [p, d, b] = await Promise.all([
      getProject(projectId.value),
      listDatasets({ project_id: projectId.value }),
      listBundles({ project_id: projectId.value })
    ])
    if (!p.data) {
      ElMessage.error('数据集配置不存在')
      return router.push('/dataset')
    }
    project.value = p.data
    datasets.value = unwrapList(d)
    bundles.value = unwrapList(b)
    selectedIds.value = selectedIds.value.filter(id => datasets.value.some(x => x.id === id))
  } finally {
    booting.value = false
  }
}

const goTask = (row) => router.push(`/dataset/workspace/${projectId.value}/table/${row.id}`)
const goNew = () => router.push(`/dataset/workspace/${projectId.value}/table/new`)

const goWeave = (bundle = null) => {
  if (bundle?.id) {
    router.push(`/dataset/workspace/${projectId.value}/bundle/${bundle.id}`)
    return
  }
  const ids = selectedIds.value.length >= 2
    ? selectedIds.value
    : datasets.value.slice(0, 2).map(d => d.id)
  const q = ids.length ? `?tables=${ids.join(',')}` : ''
  router.push(`/dataset/workspace/${projectId.value}/bundle/new${q}`)
}

const toggleSelect = (id, checked) => {
  if (checked) {
    if (!selectedIds.value.includes(id)) selectedIds.value.push(id)
  } else {
    selectedIds.value = selectedIds.value.filter(x => x !== id)
  }
}

const doDemo = async () => {
  demoLoading.value = true
  try {
    await importDemo(projectId.value, 80000)
    ElMessage.success('示例数据已导入')
    await load()
  } finally {
    demoLoading.value = false
  }
}

const doPowerDemo = async () => {
  demoLoading.value = true
  try {
    await importExtremeWeather(projectId.value)
    ElMessage.success('极端天气负荷/风光样本已导入，并完成关联与清洗绑定')
    await load()
  } finally {
    demoLoading.value = false
  }
}

const openBundle = async (row) => {
  const res = await previewBundle(row.id)
  preview.title = row.name
  preview.records = res.data.records || []
  preview.columns = res.data.columns || []
  preview.labels = res.data.column_labels || {}
  preview.factId = row.fact_dataset_id
  preview.visible = true
}

const removeDs = async (row) => {
  await ElMessageBox.confirm(`确认删除数据表「${row.name}」？`)
  await deleteDataset(row.id)
  selectedIds.value = selectedIds.value.filter(id => id !== row.id)
  load()
}
const removeBundle = async (row) => {
  await ElMessageBox.confirm('确认删除逻辑数据集？')
  await deleteBundle(row.id)
  load()
}

watch(projectId, load)
onMounted(load)
</script>

<style scoped>
.head-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.panel {
  margin-bottom: 16px;
  padding: 16px 18px 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.card-head .sub { margin-left: 10px; color: var(--muted); font-size: 12px; font-weight: 400; }
.muted { color: var(--muted); font-size: 12px; }
.empty-hint { color: var(--muted); font-size: 13px; padding: 12px 0; }

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 14px;
}

.task-square {
  position: relative;
  aspect-ratio: 1 / 1;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel-soft);
  padding: 14px 12px 12px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}
.task-square:hover {
  border-color: var(--accent);
  box-shadow: 0 8px 20px rgba(29, 111, 216, 0.1);
  transform: translateY(-2px);
}
.task-square.selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.add-square {
  border-style: dashed;
  background: #fff;
  color: var(--muted);
}
.add-square:hover { color: var(--accent); }
.plus {
  font-size: 42px;
  line-height: 1;
  font-weight: 300;
  color: var(--accent);
  margin-top: 18%;
}
.add-title { margin-top: 10px; font-weight: 700; color: var(--text); font-size: 15px; }
.add-desc { margin-top: 4px; font-size: 12px; }

.sq-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  margin-top: 18px;
  background: linear-gradient(145deg, #1d6fd8, #0f766e);
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 800;
  font-size: 18px;
}
.sq-name {
  margin-top: 12px;
  font-weight: 700;
  font-size: 14px;
  color: var(--text);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sq-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sq-stats {
  margin-top: auto;
  display: flex;
  gap: 10px;
  font-size: 12px;
  color: var(--muted);
}
.sq-foot { margin-top: 8px; min-height: 22px; }

.pick {
  position: absolute;
  top: 8px;
  left: 10px;
  z-index: 2;
}
.del {
  position: absolute;
  top: 6px;
  right: 8px;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}
.del:hover { color: var(--danger); background: #fee2e2; }

.bundle-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.bundle-card {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px;
  background: var(--panel-soft);
}
.bundle-name { font-weight: 700; margin-bottom: 8px; }
.join-lines { margin: 10px 0; min-height: 40px; }
.join-line { font-size: 12px; color: var(--text); margin-bottom: 4px; }
.how {
  display: inline-block;
  margin: 0 6px;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
}
.bundle-actions { display: flex; gap: 4px; flex-wrap: wrap; }
</style>
