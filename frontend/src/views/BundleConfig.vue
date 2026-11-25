<template>
  <div v-loading="loading" class="bundle-page">
    <div class="page-head">
      <div>
        <el-button link type="primary" @click="backWorkspace">← 返回任务工作区</el-button>
        <h2>{{ isNew ? '新建逻辑数据集' : '配置关联字段' }}</h2>
        <p>配置多表关联键。同一对表的多个键是 AND，必须同时匹配。勾选最终要展示的字段。</p>
      </div>
      <div class="head-actions">
        <el-button @click="backWorkspace">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">
          {{ isNew ? '生成逻辑数据集' : '保存并重新物化' }}
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :lg="14">
        <section class="panel">
          <div class="sec-title">基本信息</div>
          <el-form label-width="96px">
            <el-form-item label="名称" required>
              <el-input v-model="form.name" placeholder="例如：销量事实 × 门店维度" />
            </el-form-item>
            <el-form-item label="参与表" required>
              <el-select
                v-model="form.datasetIds"
                multiple
                filterable
                style="width: 100%"
                placeholder="至少选择 2 张表"
                @change="onTablesChange"
              >
                <el-option v-for="d in datasets" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="事实表" required>
              <el-select v-model="form.factId" style="width: 100%" @change="ensureSelectedDefaults">
                <el-option v-for="id in form.datasetIds" :key="id" :label="nameOf(id)" :value="id" />
              </el-select>
            </el-form-item>
          </el-form>
        </section>

        <section class="panel">
          <div class="join-toolbar">
            <div>
              <div class="sec-title" style="margin: 0">关联字段</div>
              <p class="hint">一对表只需一条关联。同一对表可添加多个键，条件为 AND（例如 row_key、ts、site 同时相等才匹配）。</p>
            </div>
            <div>
              <el-button size="small" :disabled="form.datasetIds.length < 2" :loading="suggesting" @click="runSuggest">
                智能推荐
              </el-button>
              <el-button size="small" type="primary" plain @click="addJoinRow">添加表关联</el-button>
            </div>
          </div>

          <div v-for="(j, i) in form.joins" :key="i" class="join-card">
            <div class="join-row">
              <el-select v-model="j.left_dataset_id" placeholder="左表" style="width: 170px" @change="() => onJoinTableChange(j, 'left')">
                <el-option v-for="id in form.datasetIds" :key="'l'+id" :label="nameOf(id)" :value="id" />
              </el-select>
              <el-select v-model="j.how" style="width: 100px">
                <el-option label="left" value="left" />
                <el-option label="inner" value="inner" />
                <el-option label="outer" value="outer" />
                <el-option label="right" value="right" />
              </el-select>
              <el-select v-model="j.right_dataset_id" placeholder="右表" style="width: 170px" @change="() => onJoinTableChange(j, 'right')">
                <el-option v-for="id in form.datasetIds" :key="'r'+id" :label="nameOf(id)" :value="id" />
              </el-select>
              <el-button link type="danger" @click="form.joins.splice(i, 1)">删除</el-button>
            </div>
            <div v-for="(k, ki) in j.keys" :key="ki" class="key-row">
              <span class="and-flag">{{ ki === 0 ? 'ON' : 'AND' }}</span>
              <el-select v-model="k.left_key" placeholder="左键" filterable style="width: 200px">
                <el-option v-for="c in colsOf(j.left_dataset_id)" :key="'lk'+ki+c" :label="headerLabel(c)" :value="c" />
              </el-select>
              <span class="eq">=</span>
              <el-select v-model="k.right_key" placeholder="右键" filterable style="width: 200px">
                <el-option v-for="c in colsOf(j.right_dataset_id)" :key="'rk'+ki+c" :label="headerLabel(c)" :value="c" />
              </el-select>
              <el-button link type="danger" :disabled="j.keys.length <= 1" @click="j.keys.splice(ki, 1)">删除键</el-button>
            </div>
            <el-button size="small" link type="primary" @click="addJoinKey(j)">+ 添加关联键（AND）</el-button>
          </div>
          <p v-if="!form.joins.length" class="hint">请添加至少一条表关联，或点击「智能推荐」。</p>

          <el-collapse v-if="suggestions.length" style="margin-top: 12px">
            <el-collapse-item title="智能推荐候选（点击采用）" name="1">
              <el-table :data="suggestions" size="small" @row-click="(row) => adoptSuggest(row)">
                <el-table-column prop="left_dataset" label="左表" />
                <el-table-column prop="left_key" label="左键" width="100" />
                <el-table-column prop="right_dataset" label="右表" />
                <el-table-column prop="right_key" label="右键" width="100" />
                <el-table-column prop="score" label="置信" width="70" />
                <el-table-column label="理由">
                  <template #default="{ row }">{{ (row.reasons || []).join('；') }}</template>
                </el-table-column>
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </section>
      </el-col>

      <el-col :lg="10">
        <section class="panel sticky">
          <div class="field-head">
            <div>
              <div class="sec-title" style="margin: 0">展示字段</div>
              <p class="hint">勾选需要出现在逻辑数据集中的列</p>
            </div>
            <div class="field-actions">
              <el-button link type="primary" @click="selectAllFields">全选</el-button>
              <el-button link @click="clearFields">清空</el-button>
            </div>
          </div>

          <div v-if="!form.datasetIds.length" class="hint">先选择参与表</div>
          <div v-for="id in form.datasetIds" :key="'f'+id" class="field-group">
            <div class="field-group-title">
              <span>{{ nameOf(id) }}</span>
              <el-tag v-if="id === form.factId" size="small" type="warning">事实表</el-tag>
              <el-button link type="primary" @click="toggleTableFields(id, true)">全选</el-button>
              <el-button link @click="toggleTableFields(id, false)">清空</el-button>
            </div>
            <div class="field-checks">
              <label v-for="c in colsOf(id)" :key="id + ':' + c" class="field-check">
                <el-checkbox
                  :model-value="isFieldSelected(id, c)"
                  @change="(v) => toggleField(id, c, v)"
                />
                <span class="fname">{{ headerLabel(c) }}</span>
              </label>
            </div>
          </div>

          <div class="selected-count">已选 {{ form.selectedKeys.length }} 个字段</div>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { headerLabel } from '@/utils/fieldLabels'
import {
  getProject, getBundle, listDatasets, suggestJoins, createBundle, rebuildBundle
} from '@/api'
import { unwrapList } from '@/utils/paging'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const projectId = computed(() => Number(route.params.projectId))
const bundleId = computed(() => {
  const id = route.params.bundleId
  if (!id || id === 'new') return null
  return Number(id)
})
const isNew = computed(() => !bundleId.value)

const loading = ref(false)
const saving = ref(false)
const suggesting = ref(false)
const datasets = ref([])
const suggestions = ref([])
const form = reactive({
  name: '销量事实 × 门店维度',
  datasetIds: [],
  factId: null,
  joins: [],
  selectedKeys: []
})

const fieldKey = (datasetId, name) => `${datasetId}::${name}`
const nameOf = (id) => datasets.value.find(d => d.id === id)?.name || `#${id}`
const colsOf = (id) => {
  const ds = datasets.value.find(d => d.id === id)
  return (ds?.profile?.columns || []).map(c => c.name)
}
const isFieldSelected = (datasetId, name) => form.selectedKeys.includes(fieldKey(datasetId, name))
const backWorkspace = () => router.push(`/dataset/workspace/${projectId.value}`)

const PREFERRED_KEYS = ['row_key', 'ts', 'site', 'Store', 'Date']

const defaultKeysFor = (leftId, rightId) => {
  const left = colsOf(leftId)
  const right = colsOf(rightId)
  const matched = PREFERRED_KEYS.filter(c => left.includes(c) && right.includes(c))
    .map(c => ({ left_key: c, right_key: c }))
  return matched.length ? matched : [{ left_key: '', right_key: '' }]
}

const joinKeysOf = (j) => {
  if (Array.isArray(j.keys) && j.keys.length) {
    return j.keys.map(k => ({ left_key: k.left_key || '', right_key: k.right_key || '' }))
  }
  if (j.left_key && j.right_key) return [{ left_key: j.left_key, right_key: j.right_key }]
  return [{ left_key: '', right_key: '' }]
}

const normalizeJoins = (list) => {
  const out = []
  const index = {}
  for (const j of list || []) {
    const how = j.how || 'left'
    const key = `${j.left_dataset_id}|${j.right_dataset_id}|${how}`
    const pairs = joinKeysOf(j)
    if (index[key] != null) {
      const row = out[index[key]]
      for (const p of pairs) {
        if (!row.keys.some(x => x.left_key === p.left_key && x.right_key === p.right_key)) {
          row.keys.push(p)
        }
      }
    } else {
      index[key] = out.length
      out.push({
        left_dataset_id: j.left_dataset_id,
        right_dataset_id: j.right_dataset_id,
        how,
        keys: pairs
      })
    }
  }
  return out
}

const serializeJoins = () => form.joins.map(j => {
  const keys = (j.keys || []).filter(k => k.left_key && k.right_key)
  return {
    left_dataset_id: j.left_dataset_id,
    right_dataset_id: j.right_dataset_id,
    how: j.how || 'left',
    keys,
    left_key: keys[0]?.left_key,
    right_key: keys[0]?.right_key
  }
}).filter(j => j.left_dataset_id && j.right_dataset_id && j.keys.length)

const addJoinKey = (j) => {
  if (!Array.isArray(j.keys)) j.keys = []
  j.keys.push({ left_key: '', right_key: '' })
}

const onJoinTableChange = (j, side) => {
  if (side === 'left') j.keys = (j.keys || []).map(k => ({ ...k, left_key: '' }))
  else j.keys = (j.keys || []).map(k => ({ ...k, right_key: '' }))
  const filled = defaultKeysFor(j.left_dataset_id, j.right_dataset_id)
  if (filled[0].left_key) j.keys = filled
}

const selectedFieldsPayload = () => form.selectedKeys.map(k => {
  const [dataset_id, name] = k.split('::')
  return { dataset_id: Number(dataset_id), name }
})

const ensureSelectedDefaults = () => {
  if (!form.selectedKeys.length) {
    form.selectedKeys = form.datasetIds.flatMap(id => colsOf(id).map(c => fieldKey(id, c)))
    return
  }
  form.selectedKeys = form.selectedKeys.filter(k => {
    const [id, name] = k.split('::')
    return form.datasetIds.includes(Number(id)) && colsOf(Number(id)).includes(name)
  })
  // 新加入的表默认全选其字段
  for (const id of form.datasetIds) {
    const hasAny = form.selectedKeys.some(k => k.startsWith(`${id}::`))
    if (!hasAny) {
      colsOf(id).forEach(c => form.selectedKeys.push(fieldKey(id, c)))
    }
  }
}

const onTablesChange = () => {
  if (!form.datasetIds.includes(form.factId)) {
    form.factId = form.datasetIds[0] || null
  }
  form.joins = form.joins.filter(j =>
    form.datasetIds.includes(j.left_dataset_id) && form.datasetIds.includes(j.right_dataset_id)
  )
  ensureSelectedDefaults()
}

const toggleField = (datasetId, name, checked) => {
  const key = fieldKey(datasetId, name)
  if (checked) {
    if (!form.selectedKeys.includes(key)) form.selectedKeys.push(key)
  } else {
    form.selectedKeys = form.selectedKeys.filter(k => k !== key)
  }
}

const toggleTableFields = (datasetId, on) => {
  const keys = colsOf(datasetId).map(c => fieldKey(datasetId, c))
  if (on) {
    const set = new Set(form.selectedKeys)
    keys.forEach(k => set.add(k))
    form.selectedKeys = [...set]
  } else {
    form.selectedKeys = form.selectedKeys.filter(k => !keys.includes(k))
  }
}

const selectAllFields = () => {
  form.selectedKeys = form.datasetIds.flatMap(id => colsOf(id).map(c => fieldKey(id, c)))
}
const clearFields = () => { form.selectedKeys = [] }

const addJoinRow = () => {
  const [a, b] = form.datasetIds
  form.joins.push({
    left_dataset_id: a || null,
    right_dataset_id: b || a || null,
    how: 'left',
    keys: defaultKeysFor(a, b)
  })
}

const adoptSuggest = (row, toast = true) => {
  const how = row.how || 'left'
  const existing = form.joins.find(j =>
    j.left_dataset_id === row.left_dataset_id &&
    j.right_dataset_id === row.right_dataset_id &&
    (j.how || 'left') === how
  )
  const pair = { left_key: row.left_key, right_key: row.right_key }
  if (existing) {
    if (!existing.keys.some(k => k.left_key === pair.left_key && k.right_key === pair.right_key)) {
      existing.keys.push(pair)
    }
  } else {
    form.joins.push({
      left_dataset_id: row.left_dataset_id,
      right_dataset_id: row.right_dataset_id,
      how,
      keys: [pair]
    })
  }
  if (toast) ElMessage.success('已采用该推荐（同一对表的多个键为 AND）')
}

const runSuggest = async () => {
  if (form.datasetIds.length < 2) return
  suggesting.value = true
  try {
    const res = await suggestJoins(form.datasetIds)
    suggestions.value = res.data || []
    if (!form.joins.length && suggestions.value[0]) {
      adoptSuggest(suggestions.value[0], false)
    }
    for (const j of form.joins) {
      const extra = defaultKeysFor(j.left_dataset_id, j.right_dataset_id)
      if (!Array.isArray(j.keys)) j.keys = []
      for (const p of extra) {
        if (p.left_key && !j.keys.some(k => k.left_key === p.left_key && k.right_key === p.right_key)) {
          j.keys.push(p)
        }
      }
    }
  } finally {
    suggesting.value = false
  }
}

const load = async () => {
  if (!projectId.value) return backWorkspace()
  loading.value = true
  try {
    const [p, d] = await Promise.all([
      getProject(projectId.value),
      listDatasets({ project_id: projectId.value })
    ])
    if (!p.data) {
      ElMessage.error('数据集配置不存在')
      return router.push('/dataset')
    }
    datasets.value = unwrapList(d)

    const presetIds = String(route.query.tables || '')
      .split(',')
      .map(x => Number(x))
      .filter(Boolean)

    if (isNew.value) {
      form.name = '销量事实 × 门店维度'
      form.datasetIds = presetIds.length >= 2
        ? presetIds.filter(id => datasets.value.some(d => d.id === id))
        : datasets.value.slice(0, 2).map(d => d.id)
      form.factId = form.datasetIds[0] || null
      form.joins = []
      form.selectedKeys = []
      ensureSelectedDefaults()
      if (form.datasetIds.length >= 2) runSuggest()
      return
    }

    const res = await getBundle(bundleId.value)
    const b = res.data
    if (!b) {
      ElMessage.error('逻辑数据集不存在')
      return backWorkspace()
    }
    form.name = b.name
    form.datasetIds = [...(b.dataset_ids || [])]
    form.factId = b.fact_dataset_id
    form.joins = normalizeJoins(b.joins || [])
    for (const j of form.joins) {
      const extra = defaultKeysFor(j.left_dataset_id, j.right_dataset_id)
      if (!Array.isArray(j.keys)) j.keys = []
      for (const p of extra) {
        if (p.left_key && !j.keys.some(k => k.left_key === p.left_key && k.right_key === p.right_key)) {
          j.keys.push(p)
        }
      }
    }
    if (b.selected_fields?.length) {
      form.selectedKeys = b.selected_fields.map(f => fieldKey(f.dataset_id, f.name))
    } else {
      form.selectedKeys = []
      ensureSelectedDefaults()
    }
  } finally {
    loading.value = false
  }
}

const save = async () => {
  if (!form.name.trim()) return ElMessage.warning('请填写名称')
  if (form.datasetIds.length < 2) return ElMessage.warning('请至少选择两张表')
  if (!form.factId) return ElMessage.warning('请选择事实表')
  const joins = serializeJoins()
  if (!joins.length) return ElMessage.warning('请配置关联字段（至少一对键）')
  if (!form.selectedKeys.length) return ElMessage.warning('请至少勾选一个展示字段')

  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      dataset_ids: form.datasetIds,
      joins,
      fact_dataset_id: form.factId,
      scenario_code: userStore.scenario,
      project_id: projectId.value,
      selected_fields: selectedFieldsPayload()
    }
    if (isNew.value) {
      await createBundle(payload)
      ElMessage.success('逻辑数据集已生成')
    } else {
      await rebuildBundle(bundleId.value, payload)
      ElMessage.success('关联已更新')
    }
    backWorkspace()
  } catch (e) {
    // request 拦截器通常已提示
  } finally {
    saving.value = false
  }
}

watch(() => route.fullPath, load)
onMounted(load)
</script>

<style scoped>
.panel {
  margin-bottom: 16px;
  padding: 16px 18px 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}
.sticky { position: sticky; top: 12px; }
.sec-title { font-weight: 700; margin-bottom: 12px; color: var(--text); }
.hint { color: var(--muted); margin: 4px 0 10px; font-size: 12px; }
.head-actions { display: flex; gap: 8px; }

.join-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}
.join-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.join-card {
  margin-bottom: 12px;
  padding: 12px;
  background: var(--panel-soft);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.key-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
}
.and-flag {
  width: 42px;
  font-size: 12px;
  font-weight: 700;
  color: var(--accent, #1d6fd8);
}
.eq { color: var(--muted); font-weight: 700; }

.field-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}
.field-actions { display: flex; gap: 4px; }
.field-group {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--panel-soft);
}
.field-group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  margin-bottom: 8px;
}
.field-checks {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 6px 8px;
}
.field-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
}
.fname {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.selected-count {
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}
</style>
