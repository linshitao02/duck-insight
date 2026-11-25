<template>
  <div class="studio" @mousemove="onMove" @mouseup="endDrag">
    <header class="toolbar">
      <el-input v-model="form.name" class="name-input" placeholder="看板名称" />
      <span v-if="isLive" class="live-badge">直连实时库表</span>
      <el-button :loading="saving" type="primary" @click="save">保存</el-button>
      <el-button @click="preview">Dash 预览</el-button>
      <el-button @click="autoFill">智能生成</el-button>
      <el-button @click="$router.push('/bi')">返回</el-button>
    </header>

    <div class="body">
      <aside class="left">
        <el-tabs v-model="leftTab" stretch>
          <el-tab-pane label="组件" name="comp">
            <div class="hint">拖到画布，或点选后点组件添加</div>
            <div v-for="group in typeGroups" :key="group.name" class="group">
              <div class="g-name">{{ group.name }}</div>
              <div class="comp-grid">
                <button
                  v-for="t in group.items"
                  :key="t.key"
                  class="comp"
                  draggable="true"
                  @dragstart="onDragStart($event, { kind: 'widget', type: t.key })"
                  @click="addWidget(t.key)"
                >
                  <i :class="'ico ' + t.key" />
                  {{ t.label }}
                </button>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="数据" name="data">
            <el-select v-model="sourceKey" filterable placeholder="选择数据" style="width: 100%" @change="onSourceChange">
              <el-option-group label="数据表 / 实时库表">
                <el-option
                  v-for="ds in sources.datasets"
                  :key="'d' + ds.id"
                  :label="ds.is_live ? `${ds.name}（直连库表）` : ds.name"
                  :value="`dataset:${ds.id}`"
                />
              </el-option-group>
              <el-option-group label="逻辑数据集">
                <el-option
                  v-for="b in sources.bundles"
                  :key="'b' + b.id"
                  :label="b.name"
                  :value="`bundle:${b.id}`"
                />
              </el-option-group>
            </el-select>
            <p class="hint">双击字段加入选中组件；也可直接拖到画布或组件上。所有字段都能当维度或指标。</p>
            <div class="field-block">
              <div class="g-name">维度候选</div>
              <button
                v-for="f in schema.dimensions"
                :key="f.name"
                class="field dim"
                draggable="true"
                @dragstart="onDragStart($event, { kind: 'field', ...f })"
                @dblclick="dropFieldToSelected(f)"
              >{{ f.header }}</button>
            </div>
            <div class="field-block">
              <div class="g-name">指标候选</div>
              <button
                v-for="f in schema.measures"
                :key="f.name"
                class="field mea"
                draggable="true"
                @dragstart="onDragStart($event, { kind: 'field', ...f })"
                @dblclick="dropFieldToSelected(f)"
              >{{ f.header }}</button>
            </div>
          </el-tab-pane>
        </el-tabs>
      </aside>

      <section class="center">
        <div
          ref="canvasRef"
          class="canvas"
          :style="{ minHeight: canvasMinH + 'px' }"
          @dragover.prevent
          @drop="onDropCanvas"
          @click.self="selectedId = ''"
        >
          <article
            v-for="w in layout.widgets"
            :key="w.id"
            class="widget"
            :class="{ on: selectedId === w.id }"
            :style="widgetStyle(w)"
            @click.stop="selectedId = w.id"
            @dragover.prevent
            @drop.stop="onDropWidget($event, w)"
          >
            <header class="w-head" @mousedown.prevent="startMove($event, w)">
              <b>{{ w.title || typeLabel(w.type) }}</b>
              <button class="x" @click.stop="removeWidget(w)">×</button>
            </header>
            <div class="w-body">
              <div v-if="w.type === 'kpi'" class="kpi-preview">
                <em>{{ previewMap[w.id]?.kpis?.[0]?.value ?? '绑定指标' }}</em>
                <small>{{ w.unit || '' }}</small>
              </div>
              <div v-else class="mini">
                <span class="chip time" v-for="d in timeDimsOf(w)" :key="'td' + d.field">
                  时 {{ fieldLabel(d.field) }}<i v-if="d.split && d.split !== 'none'">·{{ splitLabel(d.split) }}</i>
                </span>
                <span class="chip" v-for="d in plainDimsOf(w)" :key="'d' + d.field">维 {{ fieldLabel(d.field) }}</span>
                <span class="chip mea" v-for="m in (w.measures || [])" :key="'m' + m.field">
                  指 {{ fieldLabel(m.field) }}·{{ aggLabel(m.agg) }}
                </span>
                <p v-if="isEmptyWidget(w)" class="placeholder">在右侧配置维度与指标</p>
              </div>
            </div>
            <div class="resize" @mousedown.prevent.stop="startResize($event, w)" />
          </article>
        </div>
      </section>

      <aside class="right">
        <template v-if="selected">
          <h4>组件设置</h4>
          <el-form label-position="top" size="small">
            <el-form-item label="标题">
              <el-input v-model="selected.title" />
            </el-form-item>
            <el-form-item label="图表类型">
              <el-select v-model="selected.type" style="width: 100%">
                <el-option v-for="t in widgetTypes" :key="t.key" :label="t.label" :value="t.key" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="selected.type === 'kpi'" label="单位">
              <el-input v-model="selected.unit" placeholder="MW / ℃ / 元/MWh" />
            </el-form-item>
          </el-form>

          <!-- 时间维度框 -->
          <div class="shelf-box">
            <div class="shelf-head">
              <span class="title time">时间维度</span>
              <el-select
                v-model="timePick"
                class="add-select"
                size="small"
                filterable
                clearable
                placeholder="+ 选时间字段"
                @change="v => addDim(v, 'time')"
              >
                <el-option v-for="f in timeFieldOptions" :key="f.name" :label="f.header" :value="f.name" />
              </el-select>
            </div>
            <p class="shelf-hint">可配置是否拆分：不拆分＝原始时间；拆分＝年 / 年月 / 年月日 / 年月日时 / 年月日时分</p>
            <div v-for="ent in timeDims" :key="'t' + ent.i" class="dim-row">
              <div class="dim-main">
                <span class="chip time">时 {{ fieldLabel(ent.d.field) }}</span>
                <el-select v-model="ent.d.split" size="small" style="width: 132px" @change="refreshOne(selected)">
                  <el-option v-for="s in timeSplits" :key="s.key" :label="s.label" :value="s.key" />
                </el-select>
                <el-button link type="primary" size="small" @click="ent.d._open = !ent.d._open">
                  筛选{{ (ent.d.filters || []).length ? `(${ent.d.filters.length})` : '' }}
                </el-button>
                <el-button link type="danger" size="small" @click="removeDimAt(ent.i)">删除</el-button>
              </div>
              <div v-if="ent.d._open" class="filter-box">
                <div v-for="(flt, j) in ent.d.filters" :key="j" class="filter-row">
                  <el-select v-model="flt.op" size="small" style="width: 104px" @change="onFilterOpChange(flt, ent.d)">
                    <el-option v-for="op in timeFilterOps" :key="op.key" :label="op.label" :value="op.key" />
                  </el-select>
                  <template v-if="flt.op === 'daterange'">
                    <el-date-picker
                      v-model="flt.value"
                      type="daterange"
                      size="small"
                      value-format="YYYY-MM-DD"
                      start-placeholder="开始"
                      end-placeholder="结束"
                      style="flex: 1"
                      @change="refreshOne(selected)"
                    />
                  </template>
                  <template v-else-if="flt.op === 'ondate'">
                    <el-date-picker
                      v-model="flt.value"
                      type="date"
                      size="small"
                      value-format="YYYY-MM-DD"
                      placeholder="选择某一天"
                      style="flex: 1"
                      @change="refreshOne(selected)"
                    />
                  </template>
                  <template v-else-if="flt.op === 'month'">
                    <el-date-picker
                      v-model="flt.value"
                      type="month"
                      size="small"
                      value-format="YYYY-MM"
                      placeholder="选择年月"
                      style="flex: 1"
                      @change="refreshOne(selected)"
                    />
                  </template>
                  <template v-else-if="flt.op === 'between'">
                    <el-date-picker
                      v-model="flt.value"
                      type="daterange"
                      size="small"
                      value-format="YYYY-MM-DD"
                      style="flex: 1"
                      @change="refreshOne(selected)"
                    />
                  </template>
                  <template v-else>
                    <el-date-picker
                      v-model="flt.value"
                      type="date"
                      size="small"
                      value-format="YYYY-MM-DD"
                      placeholder="选择日期"
                      style="flex: 1"
                      @change="refreshOne(selected)"
                    />
                  </template>
                  <el-button link type="danger" size="small" @click="removeFilter(ent.d, j)">×</el-button>
                </div>
                <el-button link type="primary" size="small" @click="addFilter(ent.d, 'time')">+ 添加筛选条件</el-button>
              </div>
            </div>
            <p v-if="!timeDims.length" class="ph">未添加时间维度</p>
          </div>

          <!-- 维度框 -->
          <div class="shelf-box">
            <div class="shelf-head">
              <span class="title dim">维度</span>
              <el-select
                v-model="dimPick"
                class="add-select"
                size="small"
                filterable
                clearable
                placeholder="+ 选任意字段"
                @change="v => addDim(v, 'dim')"
              >
                <el-option v-for="f in allFields" :key="f.name" :label="f.header" :value="f.name" />
              </el-select>
            </div>
            <div v-for="ent in plainDims" :key="'d' + ent.i" class="dim-row">
              <div class="dim-main">
                <span class="chip dim">维 {{ fieldLabel(ent.d.field) }}</span>
                <el-button link type="primary" size="small" @click="ent.d._open = !ent.d._open">
                  筛选{{ (ent.d.filters || []).length ? `(${ent.d.filters.length})` : '' }}
                </el-button>
                <el-button link type="danger" size="small" @click="removeDimAt(ent.i)">删除</el-button>
              </div>
              <div v-if="ent.d._open" class="filter-box">
                <div v-for="(flt, j) in ent.d.filters" :key="j" class="filter-row">
                  <el-select v-model="flt.op" size="small" style="width: 104px" @change="refreshOne(selected)">
                    <el-option v-for="op in opsForDim(ent.d)" :key="op.key" :label="op.label" :value="op.key" />
                  </el-select>
                  <template v-if="flt.op === 'in'">
                    <el-select
                      v-model="flt.value"
                      multiple
                      filterable
                      collapse-tags
                      collapse-tags-tooltip
                      size="small"
                      style="flex: 1"
                      placeholder="多选"
                      @change="refreshOne(selected)"
                    >
                      <el-option v-for="v in filterValues(ent.d.field)" :key="v" :label="v" :value="v" />
                    </el-select>
                  </template>
                  <template v-else-if="flt.op === 'between'">
                    <el-input v-model="flt.value" size="small" placeholder="下限" style="width: 66px" @change="refreshOne(selected)" />
                    <el-input v-model="flt.value2" size="small" placeholder="上限" style="width: 66px" @change="refreshOne(selected)" />
                  </template>
                  <template v-else-if="flt.op === 'daterange'">
                    <el-date-picker
                      v-model="flt.value"
                      type="daterange"
                      size="small"
                      value-format="YYYY-MM-DD"
                      style="flex: 1"
                      @change="refreshOne(selected)"
                    />
                  </template>
                  <template v-else>
                    <el-input
                      v-model="flt.value"
                      size="small"
                      style="flex: 1"
                      :placeholder="fieldMeta(ent.d.field)?.inferred === 'numeric' ? '数值' : '文本'"
                      @change="refreshOne(selected)"
                    />
                  </template>
                  <el-button link type="danger" size="small" @click="removeFilter(ent.d, j)">×</el-button>
                </div>
                <el-button link type="primary" size="small" @click="addFilter(ent.d, 'dim')">+ 添加筛选条件</el-button>
              </div>
            </div>
            <p v-if="!plainDims.length" class="ph">未添加维度</p>
          </div>

          <!-- 指标框 -->
          <div class="shelf-box">
            <div class="shelf-head">
              <span class="title mea">指标</span>
              <el-select
                v-model="meaPick"
                class="add-select"
                size="small"
                filterable
                clearable
                placeholder="+ 选任意字段"
                @change="addMeasure"
              >
                <el-option v-for="f in allFields" :key="f.name" :label="f.header" :value="f.name" />
              </el-select>
            </div>
            <div v-for="(m, i) in selected.measures" :key="'m' + i" class="dim-row">
              <div class="dim-main">
                <span class="chip mea">指 {{ fieldLabel(m.field) }}</span>
                <el-select v-model="m.agg" size="small" style="width: 110px" @change="refreshOne(selected)">
                  <el-option v-for="a in aggs" :key="a.key" :label="a.label" :value="a.key" />
                </el-select>
                <el-button link type="danger" size="small" @click="removeMeasureAt(i)">删除</el-button>
              </div>
            </div>
            <p v-if="!(selected.measures || []).length" class="ph">未添加指标</p>
          </div>

          <el-form label-position="top" size="small">
            <el-form-item label="尺寸（列 × 行）">
              <div class="xy">
                <el-input-number v-model="selected.w" :min="2" :max="12" />
                <el-input-number v-model="selected.h" :min="2" :max="12" />
              </div>
            </el-form-item>
          </el-form>

          <div class="preview-actions">
            <el-button size="small" @click="refreshOne(selected)">刷新预览</el-button>
          </div>
          <div v-if="previewMap[selected.id]?.kpis?.length" class="kpi-preview-box">
            <div v-for="k in previewMap[selected.id].kpis" :key="k.field" class="kv">
              <span>{{ k.label }} · {{ aggLabel(k.agg) }}</span>
              <b>{{ k.value }}</b>
            </div>
          </div>
        </template>
        <template v-else>
          <h4>看板</h4>
          <el-form label-position="top" size="small">
            <el-form-item label="说明">
              <el-input v-model="form.description" type="textarea" :rows="4" />
            </el-form-item>
          </el-form>
          <p class="hint">从左侧添加组件，选中组件后在右侧配置「时间维度 / 维度 / 指标」，每个维度都能加筛选条件。</p>
        </template>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  biCatalog, biSources, biSourceDetail, getBoard, saveBoard, recommendBoard, queryBiWidget
} from '@/api'
import { useUserStore } from '@/stores/user'

const COLS = 12
const ROW = 86
const GAP = 10
const TIME_HINTS = ['ts', 'date', 'datetime', 'time']

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const canvasRef = ref()
const leftTab = ref('comp')
const saving = ref(false)
const selectedId = ref('')
const sourceKey = ref('')
const widgetTypes = ref([])
const aggs = ref([])
const timeSplits = ref([])
const filterOps = ref([])
const timeFilterOps = ref([])
const timePick = ref('')
const dimPick = ref('')
const meaPick = ref('')
const sources = reactive({ datasets: [], bundles: [] })
const schema = reactive({ fields: [], dimensions: [], measures: [], filters: [] })
const form = reactive({ id: null, name: '未命名看板', description: '', scenario_code: 'generic' })
const layout = reactive({ theme: 'finebi', grain: 'day', filters: [], widgets: [], default_source: null, realtime: false })
const previewMap = reactive({})
const drag = reactive({ mode: '', id: '', sx: 0, sy: 0, ox: 0, oy: 0, ow: 0, oh: 0 })

const typeGroups = computed(() => {
  const g = {}
  for (const t of widgetTypes.value) {
    const name = t.group || '其他'
    if (!g[name]) g[name] = []
    g[name].push(t)
  }
  return Object.keys(g).map(name => ({ name, items: g[name] }))
})
const selected = computed(() => layout.widgets.find(w => w.id === selectedId.value) || null)
const canvasMinH = computed(() => {
  const maxY = layout.widgets.reduce((m, w) => Math.max(m, (w.y || 0) + (w.h || 3)), 8)
  return maxY * ROW + 40
})
const allFields = computed(() => schema.fields || [])
const timeFieldOptions = computed(() => {
  const list = allFields.value.filter(f => isTimeField(f.name))
  return list.length ? list : allFields.value
})
const isLive = computed(() => {
  const src = currentSource()
  if (!src) return false
  const ds = sources.datasets.find(d => Number(d.id) === Number(src.id))
  return !!ds?.is_live
})
const timeDims = computed(() => indexedDims('time'))
const plainDims = computed(() => indexedDims('dim'))

const typeLabel = (k) => widgetTypes.value.find(t => t.key === k)?.label || k
const aggLabel = (k) => aggs.value.find(a => a.key === k)?.label || k || '平均'
const splitLabel = (k) => timeSplits.value.find(s => s.key === k)?.label || k
const fieldMeta = (name) => allFields.value.find(f => f.name === name) || null
const fieldLabel = (name) => fieldMeta(name)?.header || name
const isTimeField = (name) => {
  const meta = fieldMeta(name)
  if (meta?.is_time) return true
  return TIME_HINTS.includes(String(name || '').toLowerCase())
}
const dimKind = (d) => d?.kind || (d?.split && d.split !== 'none' ? 'time' : 'dim')
const filterValues = (name) => (schema.filters.find(f => f.field === name)?.values || []).slice(0, 200)
const isNumericField = (name) => {
  const meta = fieldMeta(name)
  return meta?.inferred === 'numeric' || meta?.role === 'measure'
}
// 普通维度的可用运算符：数值列给比较类，文本列给匹配类
const opsForDim = (dim) => {
  const numeric = isNumericField(dim?.field)
  return (filterOps.value || []).filter(op => {
    if (['daterange', 'ondate', 'month'].includes(op.key)) return false
    if (numeric) return true
    return !['gt', 'gte', 'lt', 'lte', 'between'].includes(op.key)
  })
}
const defaultFilterOp = (kind, field) => {
  if (kind === 'time') return 'daterange'
  return isNumericField(field) ? 'between' : 'in'
}
const onFilterOpChange = (flt, dim) => {
  const multi = flt.op === 'daterange' || flt.op === 'between'
  flt.value = multi ? [] : ''
  flt.value2 = ''
  refreshOne(selected.value)
}
// 空值判定：'' / null / [] / [null,null] 均视为未填写
const isEmptyFilterValue = (v) => {
  if (v === '' || v === null || v === undefined) return true
  if (Array.isArray(v)) return v.length === 0 || v.every(x => x === null || x === undefined || x === '')
  return false
}

function indexedDims(kind) {
  const list = selected.value?.dims || []
  const out = []
  list.forEach((d, i) => { if (dimKind(d) === kind) out.push({ d, i }) })
  return out
}
function timeDimsOf(w) { return (w.dims || []).filter(d => dimKind(d) === 'time') }
function plainDimsOf(w) { return (w.dims || []).filter(d => dimKind(d) !== 'time') }
function isEmptyWidget(w) {
  return !(w.dims || []).length && !(w.measures || []).length
}

const parseSource = (key) => {
  if (!key) return null
  const [kind, id] = String(key).split(':')
  return { kind, id: Number(id) }
}
const currentSource = () => parseSource(sourceKey.value) || layout.default_source

const widgetStyle = (w) => ({
  left: `calc(${((w.x || 0) / COLS) * 100}% )`,
  width: `calc(${((w.w || 4) / COLS) * 100}% - ${GAP}px)`,
  top: `${(w.y || 0) * ROW}px`,
  height: `${(w.h || 3) * ROW - GAP}px`
})

const uid = () => 'w_' + Math.random().toString(16).slice(2, 10)

const defaultSize = (type) => {
  if (type === 'kpi') return { w: 3, h: 2 }
  if (type === 'pie') return { w: 4, h: 4 }
  if (type === 'table') return { w: 12, h: 4 }
  if (type === 'heatmap' || type === 'scatter') return { w: 6, h: 4 }
  return { w: 6, h: 4 }
}

const nextSlot = (w, h) => {
  let y = 0
  while (y < 60) {
    for (let x = 0; x <= COLS - w; x++) {
      const hit = layout.widgets.some(o =>
        x < o.x + o.w && x + w > o.x && y < o.y + o.h && y + h > o.y
      )
      if (!hit) return { x, y }
    }
    y += 1
  }
  return { x: 0, y: 0 }
}

const addWidget = (type, at) => {
  const size = defaultSize(type)
  const pos = at || nextSlot(size.w, size.h)
  const src = currentSource()
  const w = {
    id: uid(),
    type,
    title: typeLabel(type),
    x: Math.max(0, Math.min(COLS - size.w, pos.x ?? 0)),
    y: Math.max(0, pos.y ?? 0),
    w: size.w,
    h: size.h,
    source: src,
    dims: [],
    measures: [],
    filters: []
  }
  layout.widgets.push(w)
  selectedId.value = w.id
  layout.default_source = src || layout.default_source
}

const removeWidget = (w) => {
  layout.widgets = layout.widgets.filter(x => x.id !== w.id)
  if (selectedId.value === w.id) selectedId.value = ''
}

const onDragStart = (e, payload) => {
  e.dataTransfer.setData('application/json', JSON.stringify(payload))
  e.dataTransfer.effectAllowed = 'copy'
}

const readDrag = (e) => {
  try { return JSON.parse(e.dataTransfer.getData('application/json') || '{}') } catch { return {} }
}

const canvasCell = (e) => {
  const el = canvasRef.value
  if (!el) return { x: 0, y: 0 }
  const rect = el.getBoundingClientRect()
  const x = Math.max(0, Math.min(COLS - 1, Math.floor((e.clientX - rect.left) / (rect.width / COLS))))
  const y = Math.max(0, Math.floor((e.clientY - rect.top + el.scrollTop) / ROW))
  return { x, y }
}

const onDropCanvas = (e) => {
  const payload = readDrag(e)
  const cell = canvasCell(e)
  if (payload.kind === 'widget') {
    addWidget(payload.type, cell)
  } else if (payload.kind === 'field') {
    const type = payload.role === 'measure' ? 'kpi' : 'bar'
    addWidget(type, cell)
    dropFieldToSelected(payload)
  }
}

// ---------------- 维度 / 指标 ----------------
const newDim = (field, kind) => ({
  field,
  kind,
  split: kind === 'time' ? 'year_month_day_hour' : 'none',
  filters: [],
  _open: false
})
const pushDim = (w, field) => {
  w.dims = w.dims || []
  if (w.dims.some(d => d.field === field && dimKind(d) === 'dim')) return
  w.dims.push(newDim(field, 'dim'))
}
const pushTimeDim = (w, field, split = 'year_month_day_hour') => {
  w.dims = w.dims || []
  if (w.dims.some(d => d.field === field && dimKind(d) === 'time')) return
  const item = newDim(field, 'time')
  item.split = split
  w.dims.push(item)
}
const pushMea = (w, field) => {
  w.measures = w.measures || []
  if (!w.measures.some(m => m.field === field)) w.measures.push({ field, agg: 'avg' })
}

const addDim = (field, kind) => {
  const w = selected.value
  if (kind === 'time') timePick.value = ''
  else dimPick.value = ''
  if (!w || !field) return
  if (kind === 'time') pushTimeDim(w, field)
  else pushDim(w, field)
  refreshOne(w)
}
const removeDimAt = (index) => {
  const w = selected.value
  if (!w) return
  w.dims.splice(index, 1)
  refreshOne(w)
}
const addMeasure = (field) => {
  const w = selected.value
  meaPick.value = ''
  if (!w || !field) return
  pushMea(w, field)
  refreshOne(w)
}
const removeMeasureAt = (index) => {
  const w = selected.value
  if (!w) return
  w.measures.splice(index, 1)
  refreshOne(w)
}
const addFilter = (dim, kind) => {
  dim.filters = dim.filters || []
  dim._open = true
  const mode = kind || dimKind(dim)
  dim.filters.push({ field: dim.field, op: defaultFilterOp(mode, dim.field), value: '', value2: '' })
}
const removeFilter = (dim, index) => {
  dim.filters.splice(index, 1)
  refreshOne(selected.value)
}

const applyField = (w, f) => {
  if (!w || !f?.name) return
  const meta = fieldMeta(f.name)
  if (isTimeField(f.name)) pushTimeDim(w, f.name)
  else if (w.type === 'kpi' || (f.role || meta?.role) === 'measure') pushMea(w, f.name)
  else pushDim(w, f.name)
  refreshOne(w)
}

const dropFieldToSelected = (f) => {
  if (!selected.value) addWidget(f.role === 'measure' ? 'kpi' : 'bar')
  applyField(selected.value, f)
}

const onDropWidget = (e, w) => {
  const payload = readDrag(e)
  selectedId.value = w.id
  if (payload.kind === 'field') applyField(w, payload)
}

// ---------------- 拖拽移动 / 缩放 ----------------
const startMove = (e, w) => {
  selectedId.value = w.id
  drag.mode = 'move'
  drag.id = w.id
  drag.sx = e.clientX
  drag.sy = e.clientY
  drag.ox = w.x
  drag.oy = w.y
}
const startResize = (e, w) => {
  selectedId.value = w.id
  drag.mode = 'resize'
  drag.id = w.id
  drag.sx = e.clientX
  drag.sy = e.clientY
  drag.ow = w.w
  drag.oh = w.h
}
const onMove = (e) => {
  if (!drag.mode) return
  const w = layout.widgets.find(x => x.id === drag.id)
  if (!w) return
  const el = canvasRef.value
  const unit = el ? el.clientWidth / COLS : 80
  if (drag.mode === 'move') {
    const dx = Math.round((e.clientX - drag.sx) / unit)
    const dy = Math.round((e.clientY - drag.sy) / ROW)
    w.x = Math.max(0, Math.min(COLS - w.w, drag.ox + dx))
    w.y = Math.max(0, drag.oy + dy)
  } else {
    const dw = Math.round((e.clientX - drag.sx) / unit)
    const dh = Math.round((e.clientY - drag.sy) / ROW)
    w.w = Math.max(2, Math.min(COLS - w.x, drag.ow + dw))
    w.h = Math.max(2, Math.min(12, drag.oh + dh))
  }
}
const endDrag = () => { drag.mode = '' }

// ---------------- 数据源 / 预览 ----------------
const loadSchema = async (key) => {
  const src = parseSource(key)
  if (!src?.id) {
    schema.fields = []
    schema.dimensions = []
    schema.measures = []
    schema.filters = []
    return
  }
  const res = await biSourceDetail(src.kind, src.id)
  schema.fields = res.data?.fields || []
  schema.dimensions = res.data?.dimensions || []
  schema.measures = res.data?.measures || []
  schema.filters = res.data?.filters || []
  layout.default_source = src
  layout.widgets.forEach(w => {
    if (!w.source?.id) w.source = src
  })
}

const onSourceChange = () => loadSchema(sourceKey.value)

const refreshOne = async (w) => {
  if (!w?.source?.id || !(w.measures || []).length) return
  try {
    const res = await queryBiWidget({
      type: w.type,
      source: w.source,
      dims: (w.dims || []).map(d => ({
        field: d.field,
        kind: dimKind(d),
        split: d.split || 'none',
        filters: (d.filters || [])
          .filter(f => !isEmptyFilterValue(f.value))
          .map(f => ({
            field: f.field || d.field,
            op: f.op,
            value: f.value,
            value2: f.value2,
            kind: dimKind(d)
          }))
      })),
      measures: w.measures,
      grain: layout.grain,
      color_field: w.color_field
    })
    previewMap[w.id] = res.data || {}
  } catch {
    previewMap[w.id] = {}
  }
}

const loadBoard = async () => {
  const id = route.params.id
  if (!id) return
  const res = await getBoard(id)
  const row = res.data || {}
  form.id = row.id
  form.name = row.name
  form.description = row.description || ''
  form.scenario_code = row.scenario_code || userStore.scenario || 'generic'
  const ly = row.layout || {}
  layout.theme = ly.theme || 'finebi'
  layout.grain = ly.grain || row.grain || 'day'
  layout.filters = ly.filters || []
  layout.realtime = !!ly.realtime
  layout.widgets = (ly.widgets || []).map(w => ({
    ...w,
    dims: (w.dims || []).map(d => ({ ...d, filters: d.filters || [], _open: false })),
    measures: w.measures || []
  }))
  layout.default_source = ly.default_source || null
  if (layout.default_source?.id) {
    sourceKey.value = `${layout.default_source.kind}:${layout.default_source.id}`
    await loadSchema(sourceKey.value)
  }
  await nextTick()
  layout.widgets.filter(w => w.type === 'kpi').forEach(refreshOne)
}

const cleanDims = (dims) => (dims || []).map(d => ({
  field: d.field,
  kind: dimKind(d),
  split: d.split || 'none',
  filters: (d.filters || []).map(f => ({
    field: f.field || d.field,
    op: f.op,
    value: f.value,
    value2: f.value2
  }))
}))

const save = async () => {
  if (!form.name.trim()) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description,
      layout: {
        theme: layout.theme,
        grain: layout.grain,
        filters: layout.filters,
        realtime: layout.realtime || undefined,
        widgets: layout.widgets.map(w => ({
          ...w,
          dims: cleanDims(w.dims),
          measures: (w.measures || []).map(m => ({ field: m.field, agg: m.agg }))
        })),
        default_source: currentSource()
      },
      grain: layout.grain,
      scenario_code: form.scenario_code,
      source: currentSource()
    }
    if (layout.default_source?.kind === 'dataset') payload.dataset_id = layout.default_source.id
    const res = await saveBoard(payload, form.id)
    form.id = res.data?.id || form.id
    ElMessage.success('已保存')
    if (!route.params.id && form.id) router.replace(`/bi/${form.id}`)
  } finally {
    saving.value = false
  }
}

const preview = async () => {
  await save()
  if (form.id) router.push(`/bi/${form.id}/view`)
}

const autoFill = async () => {
  const src = currentSource()
  if (!src?.id) return ElMessage.warning('请先在「数据」中选择一张表')
  const res = await recommendBoard({ source: src, name: form.name })
  const ly = res.data || {}
  layout.filters = ly.filters || []
  layout.widgets = (ly.widgets || []).map(w => ({
    ...w,
    dims: (w.dims || []).map(d => ({ ...d, filters: d.filters || [], _open: false })),
    measures: w.measures || []
  }))
  layout.grain = ly.grain || layout.grain
  layout.default_source = ly.default_source || src
  ElMessage.success('已按字段类型生成组件，可在右侧继续调整')
}

onMounted(async () => {
  const [cat, src] = await Promise.all([biCatalog(), biSources({})])
  widgetTypes.value = cat.data?.widget_types || []
  aggs.value = cat.data?.aggregations || []
  timeSplits.value = cat.data?.time_splits || []
  filterOps.value = cat.data?.filter_ops || []
  timeFilterOps.value = cat.data?.time_filter_ops || cat.data?.filter_ops || []
  sources.datasets = src.data?.datasets || []
  sources.bundles = src.data?.bundles || []
  if (route.params.id) await loadBoard()
  else {
    form.scenario_code = userStore.scenario || 'generic'
    const wide = sources.datasets.find(d => d.name && d.name.includes('负荷风光'))
    if (wide) {
      sourceKey.value = `dataset:${wide.id}`
      await loadSchema(sourceKey.value)
    }
  }
})
</script>

<style scoped>
.studio { height: 100vh; display: flex; flex-direction: column; background: #eef2f6; }
.toolbar {
  height: 48px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  background: #fff;
  border-bottom: 1px solid var(--line);
}
.name-input { width: 280px; }
.live-badge {
  font-size: 12px;
  color: #0ea5e9;
  background: #e0f2fe;
  border-radius: 999px;
  padding: 2px 10px;
}
.body { flex: 1; display: grid; grid-template-columns: 240px 1fr 330px; min-height: 0; }
.left, .right {
  background: #fff;
  border-right: 1px solid var(--line);
  overflow: auto;
  padding: 8px 10px 16px;
}
.right { border-right: 0; border-left: 1px solid var(--line); }
.hint { color: var(--muted); font-size: 12px; line-height: 1.5; margin: 6px 0 10px; }
.g-name { font-size: 11px; letter-spacing: 0.08em; color: #94a3b8; font-weight: 700; margin: 10px 0 6px; }
.comp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.comp {
  border: 1px solid var(--line);
  background: #f8fafc;
  border-radius: 8px;
  padding: 8px 6px;
  font-size: 12px;
  cursor: grab;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.comp:hover { border-color: var(--accent); color: var(--accent); }
.ico { width: 22px; height: 10px; border-radius: 2px; background: #93c5fd; display: block; }
.ico.kpi { height: 16px; background: #1d6fd8; }
.ico.line { background: linear-gradient(#1d6fd8, #93c5fd); }
.ico.bar { background: repeating-linear-gradient(90deg, #0f766e 0 4px, transparent 4px 7px); }
.ico.pie { border-radius: 50%; background: conic-gradient(#1d6fd8 0 40%, #0f766e 40% 70%, #fdba74 70%); }
.ico.heat { background: linear-gradient(90deg, #99f6e4, #0f766e); }
.field-block { margin-top: 8px; }
.field {
  display: block;
  width: 100%;
  text-align: left;
  border: 0;
  background: transparent;
  padding: 5px 6px;
  border-radius: 6px;
  font-size: 12px;
  cursor: grab;
  color: var(--text);
}
.field:hover { background: var(--accent-soft); }
.field.mea { color: #0f766e; }
.field.dim { color: #1d6fd8; }
.center { display: flex; flex-direction: column; min-width: 0; overflow: auto; }
.canvas {
  flex: 1;
  overflow: auto;
  position: relative;
  margin: 12px;
  min-width: 920px;
  background:
    linear-gradient(90deg, rgba(148,163,184,.18) 1px, transparent 1px),
    linear-gradient(rgba(148,163,184,.18) 1px, transparent 1px);
  background-size: calc(100% / 12) 86px;
  background-color: #e8eef5;
  border: 1px dashed #c5d0dc;
  border-radius: 10px;
}
.widget {
  position: absolute;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(26,36,51,.05);
}
.widget.on { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(29,111,216,.15); }
.w-head {
  height: 32px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 10px;
  background: #f8fafc;
  border-bottom: 1px solid var(--line);
  cursor: move;
  font-size: 12px;
}
.w-head .x { border: 0; background: transparent; cursor: pointer; color: var(--muted); }
.w-body { padding: 8px 10px; height: calc(100% - 32px); }
.kpi-preview { display: flex; align-items: baseline; gap: 8px; padding-top: 8px; }
.kpi-preview em { font-style: normal; font-size: 26px; font-weight: 700; }
.mini { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 11px; background: #e8f1fc; color: #1d6fd8; border-radius: 999px; padding: 2px 8px; }
.chip.mea { background: #d1fae5; color: #0f766e; }
.chip.time { background: #fef3c7; color: #b45309; }
.chip i { font-style: normal; opacity: .8; }
.placeholder { color: var(--muted); font-size: 12px; }
.resize {
  position: absolute; right: 0; bottom: 0; width: 12px; height: 12px;
  cursor: nwse-resize; background: linear-gradient(135deg, transparent 50%, #94a3b8 50%);
}
.shelf-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px 10px;
  margin-bottom: 10px;
  background: #fbfdff;
}
.shelf-head { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.shelf-head .title { font-size: 12px; font-weight: 700; }
.shelf-head .title.time { color: #b45309; }
.shelf-head .title.dim { color: #1d6fd8; }
.shelf-head .title.mea { color: #0f766e; }
.add-select { flex: 1; max-width: 170px; }
.shelf-hint { color: #94a3b8; font-size: 11px; line-height: 1.5; margin: 6px 0 4px; }
.dim-row { margin-top: 8px; }
.dim-main { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.filter-box {
  margin-top: 6px;
  padding: 6px 8px;
  border-radius: 8px;
  background: #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.filter-row { display: flex; align-items: center; gap: 6px; }
.ph { color: #94a3b8; font-size: 12px; margin: 6px 0 0; }
.xy { display: flex; gap: 8px; }
.preview-actions { margin: 4px 0 8px; }
.kpi-preview-box {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.kpi-preview-box .kv { display: flex; justify-content: space-between; gap: 8px; }
.kpi-preview-box b { color: #1d6fd8; }
h4 { font-size: 13px; margin: 8px 0 12px; }
</style>
