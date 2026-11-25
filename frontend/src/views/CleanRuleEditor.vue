<template>
  <div v-loading="booting" class="studio" :class="{ 'has-drawer': !!selected, placing: !!placing }">
    <aside class="palette">
      <el-button v-if="fromDag" link type="primary" @click="backToDag">← 返回 DAG 编排</el-button>
      <el-button v-else link type="primary" @click="$router.push('/clean')">← 返回规则库</el-button>
      <h2>{{ isNew ? '新建清洗规则' : '编辑清洗规则' }}</h2>
      <p>点击左侧组件后会跟着鼠标，再在画布上点一下放下。从节点右侧圆点拉线到下一节点左侧圆点。空白处按住可拖动画布，滚轮缩放。</p>
      <el-input v-model="form.name" placeholder="规则名称" style="margin-top: 8px" />
      <el-input v-model="form.description" type="textarea" :rows="2" placeholder="说明（可选）" style="margin-top: 8px" />

      <div class="sec">数据源</div>
      <el-select v-model="ctx.projectId" filterable placeholder="数据空间" style="width: 100%" @change="onProjectChange">
        <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-radio-group v-model="ctx.targetType" size="small" style="margin: 8px 0" @change="onSourceTypeChange">
        <el-radio-button label="dataset">原始表</el-radio-button>
        <el-radio-button label="bundle">逻辑数据集</el-radio-button>
      </el-radio-group>
      <el-select v-model="ctx.targetId" filterable placeholder="选择表" style="width: 100%" @change="loadSchema">
        <el-option v-for="item in sourceOptions" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>

      <div v-for="cat in categoryList" :key="cat.key" class="cat">
        <div class="cat-name">{{ cat.label }}</div>
        <div
          v-for="op in cat.ops"
          :key="op.op"
          class="comp"
          :class="{ picking: placing?.op === op.op }"
          title="点击后在画布上再点一下放下"
          @click.stop="pickOp(op, $event)"
        >
          <i :style="{ background: colorOf(op.category) }" />
          <div>
            <b>{{ op.label }}</b>
            <span>{{ op.desc }}</span>
          </div>
        </div>
      </div>
    </aside>

    <div class="stage-wrap">
    <div class="stage-toolbar">
      <el-button v-if="fromDag" @click="backToDag">返回 DAG 编排</el-button>
      <el-button type="success" :loading="previewing" @click="doPreview">试运行</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </div>
    <div
      class="stage"
      ref="stageRef"
      :class="{ placing: !!placing, panning }"
      :data-linking="linking.from || ''"
      @mousedown="onStageMouseDown"
      @click="onStageClick"
      @contextmenu.prevent="cancelPlace"
      @wheel.prevent="onWheel"
    >
      <div class="world" :style="worldBox">
        <div class="world-inner" :style="worldInner">
      <svg class="wires" :width="canvas.w" :height="canvas.h">
        <defs>
          <marker id="clean-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#94a3b8" />
          </marker>
        </defs>
        <path
          v-for="(e, i) in edges"
          :key="i"
          class="wire"
          :d="edgePath(e)"
          fill="none"
          stroke="#94a3b8"
          stroke-width="2.5"
          marker-end="url(#clean-arrow)"
          @dblclick.stop="removeEdge(i)"
        />
        <path v-if="draft" :d="draft" fill="none" stroke="#1d6fd8" stroke-width="2" stroke-dasharray="6 4" />
      </svg>
      <div
        v-for="n in nodes"
        :key="n.id"
        class="node"
        :class="{ on: selected === n.id, orphan: !isWired(n.id) && nodes.length > 1 }"
        :data-id="n.id"
        :style="nodeStyle(n)"
        @mousedown.stop="startMove(n, $event)"
        @mouseup.stop="endLink(n)"
        @click.stop="onNodeClick(n, $event)"
      >
        <span class="port in" role="button" :aria-label="'接到 ' + (metaOf(n.op)?.label || n.op)" title="接到这里" @mousedown.stop.prevent @mouseup.stop="endLink(n)" />
        <span class="ord">{{ orderIndex(n) }}</span>
        <i :style="{ background: colorOf(metaOf(n.op)?.category) }" />
        <div class="body">
          <b>{{ metaOf(n.op)?.label || n.op }}</b>
          <em>{{ summarize(n) }}</em>
        </div>
        <span class="port out" role="button" :aria-label="'从 ' + (metaOf(n.op)?.label || n.op) + ' 拉线'" title="按住拖到下一节点左侧圆点" @mousedown.stop="startLink(n, $event)" />
      </div>
        </div>
      </div>
      <div v-if="!nodes.length && !placing" class="empty-hint">点击左侧组件，再在画布上点一下放下，然后从右端口拉线连接</div>
    </div>
    <button type="button" class="zoom-badge" title="点击恢复 100%" @click="resetZoom">{{ zoomPct }}%</button>

    <transition name="sheet">
      <aside v-if="selectedNode" class="drawer" @click.stop>
        <div class="grabber" />
        <div class="drawer-head">
          <div>
            <strong>{{ metaOf(selectedNode.op)?.label || selectedNode.op }}</strong>
            <p>{{ metaOf(selectedNode.op)?.desc }}</p>
          </div>
          <div class="drawer-ops">
            <el-button size="small" :loading="previewing" @click="doPreview">试运行</el-button>
            <el-button v-if="after.length" size="small" type="primary" plain @click="previewOpen = true">查看预览</el-button>
            <el-button size="small" type="danger" plain @click="removeNode">删除组件</el-button>
            <el-button size="small" @click="selected = ''">收起</el-button>
          </div>
        </div>
        <div class="drawer-body">
          <el-form class="cfg" label-width="88px" label-position="left">
            <template v-if="selectedNode.op === 'filter'">
              <el-form-item label="列">
                <el-select v-model="selectedNode.column" filterable>
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
              <el-form-item label="条件">
                <el-select v-model="selectedNode.operator">
                  <el-option v-for="o in operatorOptions" :key="o" :label="o" :value="o" />
                </el-select>
              </el-form-item>
              <el-form-item v-if="selectedNode.operator !== 'notnull'" label="值">
                <el-input v-model="selectedNode.value" placeholder="如 0" />
              </el-form-item>
            </template>

            <template v-else-if="selectedNode.op === 'fill_missing'">
              <el-form-item label="作用字段">
                <el-select v-model="selectedNode.columns" multiple filterable :collapse-tags="false" :max-collapse-tags="99" class="field-select" placeholder="选择仍存在的字段，空=全部">
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
              <el-form-item label="默认策略">
                <el-select v-model="selectedNode.strategy">
                  <el-option v-for="s in fillStrategies" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </el-form-item>
              <el-form-item v-if="selectedNode.strategy === 'constant'" label="默认常数">
                <el-input v-model="selectedNode.value" />
              </el-form-item>
              <p class="hint">默认「自动」：数值列填均值，非数值列填众数。上游「删除列」去掉的字段不会出现在这里。</p>
              <div class="override-head">
                <span>字段策略</span>
                <div>
                  <el-button link type="primary" @click="suggestFillOverrides">按类型建议</el-button>
                  <el-button link type="primary" @click="addFillOverride">+ 覆盖</el-button>
                </div>
              </div>
              <div v-if="!liveOverrides.length" class="muted">未覆盖时，对上游仍存在的字段走默认策略。</div>
              <div v-for="(row, i) in liveOverrides" :key="row.column + i" class="override-row">
                <el-select v-model="row.column" filterable placeholder="字段">
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="`${colLabel(c)} · ${isNumericCol(c) ? '数值' : '非数值'}`" :value="c" />
                </el-select>
                <el-select v-model="row.strategy" placeholder="策略">
                  <el-option v-for="s in fillStrategies" :key="s.value" :label="s.short" :value="s.value" />
                </el-select>
                <el-input v-if="row.strategy === 'constant'" v-model="row.value" placeholder="常数" />
                <el-button link type="danger" @click="removeOverride(row)">删除</el-button>
              </div>
            </template>

            <template v-else-if="selectedNode.op === 'clip_outlier'">
              <p class="hint">同一节点可配置多组字段，每组有独立方法和上下限，不必再拆成多个裁剪节点。</p>
              <div v-for="(g, i) in (selectedNode.ranges || [])" :key="'clip'+i" class="clip-group">
                <div class="override-head">
                  <span>裁剪组 {{ i + 1 }}</span>
                  <el-button link type="danger" :disabled="(selectedNode.ranges || []).length <= 1" @click="removeClipRange(i)">删除本组</el-button>
                </div>
                <el-form-item label="字段">
                  <el-select v-model="g.columns" multiple filterable :collapse-tags="false" :max-collapse-tags="99" class="field-select" placeholder="选择要裁剪的字段">
                    <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                  </el-select>
                </el-form-item>
                <el-form-item label="方法">
                  <el-select v-model="g.method">
                    <el-option label="IQR" value="iqr" />
                    <el-option label="分位数" value="quantile" />
                    <el-option label="物理阈值" value="range" />
                  </el-select>
                </el-form-item>
                <template v-if="g.method === 'quantile' || g.method === 'range'">
                  <el-form-item :label="g.method === 'range' ? '下限' : '低分位'">
                    <el-input-number v-model="g.low" :step="g.method === 'range' ? 1 : 0.01" controls-position="right" />
                  </el-form-item>
                  <el-form-item :label="g.method === 'range' ? '上限' : '高分位'">
                    <el-input-number v-model="g.high" :step="g.method === 'range' ? 1 : 0.01" controls-position="right" />
                  </el-form-item>
                </template>
              </div>
              <el-button size="small" type="primary" plain @click="addClipRange">+ 添加一组字段</el-button>
            </template>

            <template v-else-if="selectedNode.op === 'parse_date'">
              <el-form-item label="日期列">
                <el-select v-model="selectedNode.column" filterable>
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
              <el-form-item label="拆出">
                <el-checkbox-group :model-value="selectedNode.extract || []" @update:model-value="setExtract">
                  <el-checkbox v-for="opt in extractOpts" :key="opt.value" :value="opt.value" :label="opt.value">{{ opt.label }}</el-checkbox>
                </el-checkbox-group>
              </el-form-item>
            </template>

            <template v-else-if="selectedNode.op === 'split_flags'">
              <el-form-item label="文本列">
                <el-select v-model="selectedNode.column" filterable>
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
              <el-form-item label="标记词">
                <div class="token-tools">
                  <el-button size="small" :loading="probing" @click="probeTokens">自动探查</el-button>
                  <span v-if="probeMeta" class="muted">发现 {{ probeMeta.n_unique }} 个原值</span>
                </div>
                <div v-if="(selectedNode.tokens || []).length" class="field-chips">
                  <el-tag v-for="t in selectedNode.tokens" :key="t" closable @close="removeToken(t)">{{ t }}</el-tag>
                </div>
                <el-select
                  v-model="selectedNode.tokens"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  :collapse-tags="false"
                  :max-collapse-tags="99"
                  class="field-select chips-outside"
                  placeholder="探查或手动输入后回车"
                >
                  <el-option
                    v-for="t in tokenOptions"
                    :key="t.token"
                    :label="t.count ? `${t.token}（${t.count}）` : t.token"
                    :value="t.token"
                  />
                </el-select>
                <p class="hint">会按逗号等分隔符切分文本列，把高频片段列为候选项；也可自己输入。</p>
              </el-form-item>
              <el-form-item label="前缀">
                <el-input v-model="selectedNode.prefix" placeholder="promo" />
              </el-form-item>
            </template>

            <template v-else-if="['drop_columns','drop_duplicates','drop_null_rows','log1p'].includes(selectedNode.op)">
              <el-form-item :label="selectedNode.op === 'drop_duplicates' || selectedNode.op === 'drop_null_rows' ? '列（可空=全部）' : '字段'">
                <el-select v-model="selectedNode.columns" multiple filterable :collapse-tags="false" :max-collapse-tags="99" class="field-select" placeholder="选择字段，名称会完整列出">
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
            </template>

            <template v-else-if="selectedNode.op === 'cast'">
              <el-form-item label="字段">
                <el-select v-model="selectedNode.columns" multiple filterable :collapse-tags="false" :max-collapse-tags="99" class="field-select">
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
              <el-form-item label="转为">
                <el-select v-model="selectedNode.to">
                  <el-option label="数值" value="numeric" />
                  <el-option label="字符串" value="string" />
                </el-select>
              </el-form-item>
            </template>

            <template v-else-if="selectedNode.op === 'label_encode'">
              <el-form-item label="模式">
                <el-switch v-model="selectedNode.auto_mode" active-text="自动类别列" inactive-text="指定列" />
              </el-form-item>
              <el-form-item v-if="!selectedNode.auto_mode" label="字段">
                <el-select v-model="selectedNode.columns" multiple filterable :collapse-tags="false" :max-collapse-tags="99" class="field-select">
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
            </template>

            <template v-else-if="selectedNode.op === 'scale'">
              <el-form-item label="模式">
                <el-switch v-model="selectedNode.auto_mode" active-text="自动数值列" inactive-text="指定列" />
              </el-form-item>
              <p class="muted" style="margin: -4px 0 10px">
                自动数值列会扫描表里的数值字段（不含负荷/电价等目标列）。指定列则只用你勾的字段。
                后面接到 DAG 训练时，实际标准化列 = 这里的列 ∩ 训练节点已选特征。
              </p>
              <el-form-item v-if="!selectedNode.auto_mode" label="字段">
                <el-select v-model="selectedNode.columns" multiple filterable :collapse-tags="false" :max-collapse-tags="99" class="field-select">
                  <template #label="{ value }">{{ colLabel(value) }}</template>
                  <el-option v-for="c in fieldOptions" :key="c" :label="colLabel(c)" :value="c" />
                </el-select>
              </el-form-item>
              <el-form-item label="方法">
                <el-select v-model="selectedNode.method">
                  <el-option label="StandardScaler" value="standard" />
                  <el-option label="MinMax" value="minmax" />
                </el-select>
              </el-form-item>
            </template>

            <p v-else class="muted">该组件无需额外参数，放入流水线即可。</p>
          </el-form>
        </div>
      </aside>
    </transition>
    </div>

    <div
      v-if="placing"
      class="place-ghost"
      :style="{ left: ghost.x + 'px', top: ghost.y + 'px' }"
    >
      <i :style="{ background: colorOf(placing.category) }" />
      <div>
        <span>{{ placing.label }}</span>
        <em>点击画布放下 · Esc 取消</em>
      </div>
    </div>

    <el-dialog
      v-model="previewOpen"
      title="试运行预览"
      width="86%"
      top="6vh"
      append-to-body
      class="preview-dialog"
    >
      <p v-if="logs.length" class="log">{{ logs.join(' ｜ ') }}</p>
      <el-empty v-if="!after.length && !previewing" description="点试运行后在这里看结果" :image-size="72" />
      <el-table v-else v-loading="previewing" :data="after" size="small" max-height="62vh" stripe border>
        <el-table-column v-for="c in afterCols" :key="c" :prop="c" :label="colLabel(c)" min-width="150" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="previewOpen = false">收起</el-button>
        <el-button type="success" :loading="previewing" @click="doPreview">重新试运行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import {
  listOps, getRule, saveRule, previewClean, getCleanSourceSchema, probeCleanTokens,
  listProjects, listDatasets, listBundles
} from '@/api'
import { columnHeader } from '@/utils/fieldLabels'
import { unwrapList } from '@/utils/paging'

const CAT_COLOR = { clean: '#14b8a6', feature: '#22c55e', encode: '#8b5cf6', normalize: '#f59e0b' }
const NODE_W = 210
const NODE_H = 68
const extractOpts = [
  { value: 'year', label: '年' },
  { value: 'month', label: '月' },
  { value: 'day', label: '日' },
  { value: 'hour', label: '时' },
  { value: 'minute', label: '分' },
  { value: 'second', label: '秒' },
  { value: 'weekday', label: '星期' },
  { value: 'week', label: '周' },
  { value: 'quarter', label: '季度' }
]
const fillStrategies = [
  { value: 'auto', label: '自动（数值均值 / 非数值众数）', short: '自动' },
  { value: 'mean', label: '均值', short: '均值' },
  { value: 'median', label: '中位数', short: '中位数' },
  { value: 'mode', label: '众数', short: '众数' },
  { value: 'zero', label: '填 0', short: '填 0' },
  { value: 'constant', label: '常数', short: '常数' }
]

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isNew = computed(() => route.name === 'CleanRuleNew' || !route.params.id || route.params.id === 'new')
const fromDag = computed(() => route.query.from === 'dag' && route.query.dagId)

const booting = ref(false)
const saving = ref(false)
const previewing = ref(false)
const projects = ref([])
const datasets = ref([])
const bundles = ref([])
const ops = ref([])
const categories = ref({})
const columns = ref([])
const nodes = ref([])
const edges = ref([])
const selected = ref('')
const previewOpen = ref(false)
const probing = ref(false)
const probedTokens = ref([])
const probeMeta = ref(null)
const after = ref([])
const afterCols = ref([])
const logs = ref([])
const placing = ref(null)
const ghost = reactive({ x: 0, y: 0 })
const canvas = { w: 2200, h: 640 }
const zoom = ref(1)
const stageRef = ref(null)
const panning = ref(false)
const didPan = ref(false)
const ZOOM_MIN = 0.4
const ZOOM_MAX = 2
const linking = reactive({ from: null, x: 0, y: 0 })
const draft = ref('')

const form = reactive({ id: null, name: '', description: '' })
const ctx = reactive({ projectId: null, targetType: 'bundle', targetId: null })
const operatorOptions = ['>', '>=', '<', '<=', '==', '!=', 'notnull']
const columnNames = computed(() => columns.value.map(c => c.name))
const sourceOptions = computed(() => ctx.targetType === 'bundle' ? bundles.value : datasets.value)
const zoomPct = computed(() => Math.round(zoom.value * 100))
const worldBox = computed(() => ({
  width: `${Math.round(canvas.w * zoom.value)}px`,
  height: `${Math.round(canvas.h * zoom.value)}px`
}))
const worldInner = computed(() => ({
  width: `${canvas.w}px`,
  height: `${canvas.h}px`,
  transform: `scale(${zoom.value})`,
  transformOrigin: '0 0'
}))

const categoryList = computed(() => {
  const order = ['clean', 'feature', 'encode', 'normalize']
  return order
    .filter(k => ops.value.some(o => o.category === k))
    .map(k => ({ key: k, label: categories.value[k] || k, ops: ops.value.filter(o => o.category === k) }))
})

const selectedNode = computed(() => nodes.value.find(n => n.id === selected.value) || null)
const fieldOptions = computed(() => {
  const live = columnsAt(selected.value)
  const n = selectedNode.value
  const extra = []
  if (n?.column) extra.push(n.column)
  if (Array.isArray(n?.columns)) extra.push(...n.columns)
  if (Array.isArray(n?.ranges)) extra.push(...n.ranges.flatMap(g => g.columns || []))
  if (Array.isArray(n?.overrides)) extra.push(...n.overrides.map(r => r.column).filter(Boolean))
  const seen = new Set(live)
  const out = [...live]
  for (const c of extra) {
    if (c && !seen.has(c)) {
      seen.add(c)
      out.push(c)
    }
  }
  return out
})
const liveOverrides = computed(() => {
  const n = selectedNode.value
  if (!n || n.op !== 'fill_missing') return []
  const live = new Set(fieldOptions.value)
  return (n.overrides || []).filter(r => r.column && live.has(r.column))
})

function nodeById(id) {
  return nodes.value.find(n => n.id === id)
}
function portPos(n, side) {
  return { x: n.x + (side === 'out' ? NODE_W : 0), y: n.y + NODE_H / 2 }
}
function bezier(a, b) {
  const dx = Math.max(40, (b.x - a.x) / 2)
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`
}
function edgePath(e) {
  const a = nodeById(e.from)
  const b = nodeById(e.to)
  if (!a || !b) return ''
  return bezier(portPos(a, 'out'), portPos(b, 'in'))
}
function sanitizeEdges(list) {
  const ids = new Set(nodes.value.map(n => n.id))
  const seen = new Set()
  const out = []
  for (const e of list || []) {
    if (!e || !ids.has(e.from) || !ids.has(e.to) || e.from === e.to) continue
    const k = `${e.from}>${e.to}`
    if (seen.has(k)) continue
    seen.add(k)
    out.push({ from: e.from, to: e.to })
  }
  return out
}
function wiredIds() {
  const used = new Set()
  for (const e of edges.value) {
    used.add(e.from)
    used.add(e.to)
  }
  return used
}
function isWired(id) {
  return wiredIds().has(id)
}
function ancestorsOf(nodeId) {
  const incoming = {}
  for (const e of edges.value) {
    if (!incoming[e.to]) incoming[e.to] = []
    incoming[e.to].push(e.from)
  }
  const seen = new Set()
  const stack = [...(incoming[nodeId] || [])]
  while (stack.length) {
    const id = stack.pop()
    if (seen.has(id)) continue
    seen.add(id)
    for (const p of incoming[id] || []) stack.push(p)
  }
  return [...seen].map(nodeById).filter(Boolean)
}
function topoNodes() {
  const ids = nodes.value.map(n => n.id)
  const indeg = Object.fromEntries(ids.map(id => [id, 0]))
  const outs = Object.fromEntries(ids.map(id => [id, []]))
  for (const e of edges.value) {
    if (!(e.from in outs) || !(e.to in indeg)) continue
    outs[e.from].push(e.to)
    indeg[e.to]++
  }
  const q = ids.filter(id => indeg[id] === 0)
  const order = []
  while (q.length) {
    const id = q.shift()
    order.push(id)
    for (const t of outs[id]) {
      indeg[t]--
      if (indeg[t] === 0) q.push(t)
    }
  }
  for (const id of ids) if (!order.includes(id)) order.push(id)
  return order.map(nodeById).filter(Boolean)
}
function executableNodes() {
  if (!nodes.value.length) return []
  if (nodes.value.length === 1) return nodes.value
  const used = wiredIds()
  if (!used.size) return []
  return topoNodes().filter(n => used.has(n.id))
}
function orderIndex(n) {
  const i = executableNodes().findIndex(x => x.id === n.id)
  return i >= 0 ? i + 1 : '·'
}
function wouldCycle(from, to) {
  const stack = [to]
  const seen = new Set()
  while (stack.length) {
    const cur = stack.pop()
    if (cur === from) return true
    if (seen.has(cur)) continue
    seen.add(cur)
    for (const e of edges.value) if (e.from === cur) stack.push(e.to)
  }
  return false
}
function priorNodes(nodeId) {
  if (!nodeId) return []
  const ranked = executableNodes()
  const idx = ranked.findIndex(n => n.id === nodeId)
  if (idx >= 0) return ranked.slice(0, idx)
  return ancestorsOf(nodeId)
}

function applyColumnOps(cols, n) {
  let next = cols
  if (n.op === 'drop_columns') {
    const drop = new Set(n.columns || [])
    next = next.filter(c => !drop.has(c))
  } else if (n.op === 'parse_date') {
    next = [...next]
    for (const e of n.extract || []) if (!next.includes(e)) next.push(e)
  } else if (n.op === 'split_flags') {
    next = [...next]
    const prefix = n.prefix || ''
    for (const t of n.tokens || []) {
      const name = `${prefix}${String(t).toLowerCase()}`
      if (!next.includes(name)) next.push(name)
    }
  }
  return next
}

function columnsAt(nodeId) {
  let cols = [...columnNames.value]
  if (!nodeId) return cols
  for (const n of priorNodes(nodeId)) cols = applyColumnOps(cols, n)
  return cols
}

const colorOf = (cat) => CAT_COLOR[cat] || '#64748b'
const metaOf = (op) => ops.value.find(o => o.op === op)
function nodeStyle(n) {
  return { left: n.x + 'px', top: n.y + 'px', width: NODE_W + 'px', height: NODE_H + 'px' }
}

function summarize(n) {
  if (n.op === 'filter') return `${n.column || ''} ${n.operator || ''} ${n.value ?? ''}`.trim()
  if (n.op === 'parse_date') {
    const bits = (n.extract || []).map(v => extractOpts.find(o => o.value === v)?.label || v)
    return `${n.column || ''} · ${bits.join('/') || '未勾选'}`
  }
  if (n.op === 'split_flags') return `${n.column || ''} · ${(n.tokens || []).length} 词`
  if (n.op === 'fill_missing') {
    const ov = (n.overrides || []).length
    return ov ? `${n.strategy || 'auto'} +${ov}覆盖` : (n.strategy || 'auto')
  }
  if (n.op === 'clip_outlier') {
    const groups = clipRangeOf(n)
    const cols = groups.flatMap(g => g.columns || [])
    if (cols.length) return `${groups.length} 组 · ${cols.slice(0, 3).join(', ')}`
    return `${groups.length} 组阈值`
  }
  if (n.columns?.length) return n.columns.slice(0, 3).join(', ')
  if (n.auto_mode) return '自动列'
  return n.strategy || n.method || '点击配置'
}

function makeStep(op) {
  const picked = [...columnNames.value].slice(0, 0)
  const base = { id: 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5), op, x: 80, y: 180 }
  if (op === 'filter') return { ...base, column: columnNames.value[0] || 'Sales', operator: '>', value: '0' }
  if (op === 'fill_missing') return { ...base, columns: picked, strategy: 'auto', value: 0, overrides: [] }
  if (op === 'clip_outlier') return { ...base, method: 'range', ranges: [{ columns: [], method: 'range', low: 0, high: 100 }] }
  if (op === 'parse_date') return {
    ...base,
    column: columnNames.value.find(c => /date|ts|time/i.test(c)) || 'Date',
    extract: ['year', 'month', 'day', 'weekday', 'hour', 'minute', 'second']
  }
  if (op === 'split_flags') {
    return { ...base, column: 'PromoInterval', tokens: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], prefix: 'promo' }
  }
  if (op === 'drop_columns' || op === 'log1p') return { ...base, columns: picked }
  if (op === 'drop_duplicates' || op === 'drop_null_rows') return { ...base, columns: picked }
  if (op === 'cast') return { ...base, columns: picked, to: 'numeric' }
  if (op === 'label_encode') return { ...base, columns: picked, auto_mode: true }
  if (op === 'scale') return { ...base, columns: picked, method: 'standard', auto_mode: true }
  return base
}

function layoutFromSteps(steps) {
  return (steps || []).map((s, i) => {
    const node = { ...s, id: s.id || ('s' + i + Date.now().toString(36)), x: 70 + i * 230, y: 190 }
    if ((s.op === 'label_encode' || s.op === 'scale') && s.auto_mode == null) {
      node.auto_mode = !s.columns || !s.columns.length || s.columns === 'auto_categorical' || s.columns === 'auto_numeric'
    }
    if (typeof node.columns === 'string') node.columns = []
    if (s.op === 'parse_date') {
      node.extract = Array.isArray(s.extract)
        ? [...s.extract]
        : ['year', 'month', 'day', 'weekday', 'hour', 'minute', 'second']
    }
    if (s.op === 'split_flags') node.tokens = Array.isArray(s.tokens) ? [...s.tokens] : []
    if (s.op === 'clip_outlier') node.ranges = clipRangeOf(s)
    if (s.op === 'fill_missing') {
      if (Array.isArray(s.overrides)) {
        node.overrides = s.overrides.map(r => ({ ...r }))
      } else if (s.column_strategies && typeof s.column_strategies === 'object' && !Array.isArray(s.column_strategies)) {
        node.overrides = Object.entries(s.column_strategies).map(([column, strategy]) => ({
          column, strategy, value: (s.column_values || {})[column]
        }))
      } else {
        node.overrides = []
      }
    }
    return node
  })
}

function openNode(id) {
  selected.value = id
  const n = nodes.value.find(x => x.id === id)
  if (n?.op === 'split_flags' && !Array.isArray(n.tokens)) n.tokens = []
  if (n?.op === 'parse_date' && !Array.isArray(n.extract)) {
    n.extract = ['year', 'month', 'day', 'weekday', 'hour', 'minute', 'second']
  }
  if (n?.op === 'fill_missing' && !Array.isArray(n.overrides)) n.overrides = []
  if (n?.op === 'clip_outlier') ensureClipRanges(n)
  pruneFields(n)
}

function configuredFields(n) {
  if (!n) return []
  const out = []
  if (n.column) out.push(n.column)
  if (Array.isArray(n.columns)) out.push(...n.columns)
  if (Array.isArray(n.ranges)) out.push(...n.ranges.flatMap(g => g.columns || []))
  if (Array.isArray(n.overrides)) out.push(...n.overrides.map(r => r.column).filter(Boolean))
  return out.filter(Boolean)
}

function pruneFields(n) {
  if (!n) return
  if (!columnNames.value.length) return
  const live = new Set(columnsAt(n.id))
  const configured = configuredFields(n)
  // 当前数据源字段对不上已配置列时，不要把裁剪组/字段属性清掉
  if (configured.length && !configured.some(c => live.has(c))) return
  if (Array.isArray(n.columns) && n.columns.length) {
    const next = n.columns.filter(c => live.has(c))
    if (next.length !== n.columns.length) n.columns = next
  }
  if (Array.isArray(n.overrides)) {
    const next = n.overrides.filter(r => r.column && live.has(r.column))
    if (next.length !== n.overrides.length) n.overrides = next
  }
  if (n.op === 'clip_outlier') return
  if (Array.isArray(n.ranges)) {
    n.ranges = n.ranges.map(g => ({
      ...g,
      columns: (g.columns || []).filter(c => live.has(c))
    }))
  }
}

function pruneAll() {
  for (const n of nodes.value) pruneFields(n)
}

function removeSelectedColumn(c) {
  const n = selectedNode.value
  if (!n || !Array.isArray(n.columns)) return
  n.columns = n.columns.filter(x => x !== c)
  pruneAll()
}

function removeToken(t) {
  const n = selectedNode.value
  if (!n || !Array.isArray(n.tokens)) return
  n.tokens = n.tokens.filter(x => x !== t)
}

function removeOverride(row) {
  const n = selectedNode.value
  if (!n || !Array.isArray(n.overrides)) return
  n.overrides = n.overrides.filter(r => r !== row)
}

function setExtract(vals) {
  const n = selectedNode.value
  if (!n) return
  n.extract = [...(vals || [])]
}

function pickOp(op, ev) {
  if (placing.value?.op === op.op) {
    cancelPlace()
    return
  }
  placing.value = op
  if (ev) {
    ghost.x = ev.clientX + 12
    ghost.y = ev.clientY + 12
  }
}

function cancelPlace() {
  placing.value = null
}

function stagePoint(ev, stageEl) {
  const stage = stageEl || stageRef.value || ev.currentTarget?.closest?.('.stage') || document.querySelector('.studio .stage')
  if (!stage) return { x: 70, y: 190, stage: null }
  const rect = stage.getBoundingClientRect()
  const z = zoom.value || 1
  return {
    x: (ev.clientX - rect.left + stage.scrollLeft) / z,
    y: (ev.clientY - rect.top + stage.scrollTop) / z,
    stage
  }
}

function onWheel(ev) {
  const stage = stageRef.value
  if (!stage) return
  const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom.value * Math.exp(-ev.deltaY * 0.0018)))
  if (Math.abs(next - zoom.value) < 0.001) return
  const rect = stage.getBoundingClientRect()
  const wx = (ev.clientX - rect.left + stage.scrollLeft) / zoom.value
  const wy = (ev.clientY - rect.top + stage.scrollTop) / zoom.value
  zoom.value = next
  requestAnimationFrame(() => {
    stage.scrollLeft = wx * next - (ev.clientX - rect.left)
    stage.scrollTop = wy * next - (ev.clientY - rect.top)
  })
}

function resetZoom() {
  zoom.value = 1
}

function onStageMouseDown(ev) {
  if (ev.button !== 0) return
  if (placing.value || linking.from) return
  if (ev.target?.closest?.('.node') || ev.target?.closest?.('.port') || ev.target?.closest?.('.zoom-badge')) return
  const stage = stageRef.value
  if (!stage) return
  panning.value = true
  didPan.value = false
  const sx = ev.clientX
  const sy = ev.clientY
  const sl = stage.scrollLeft
  const st = stage.scrollTop
  const move = (e) => {
    const dx = e.clientX - sx
    const dy = e.clientY - sy
    if (Math.hypot(dx, dy) > 3) didPan.value = true
    stage.scrollLeft = sl - dx
    stage.scrollTop = st - dy
  }
  const up = () => {
    panning.value = false
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
  ev.preventDefault()
}

function dropOp(ev) {
  const op = placing.value
  if (!op) return false
  const pt = stagePoint(ev)
  const node = makeStep(op.op)
  node.x = Math.max(16, pt.x - NODE_W / 2)
  node.y = Math.max(16, pt.y - NODE_H / 2)
  nodes.value.push(node)
  placing.value = null
  openNode(node.id)
  return true
}

function onStageClick(ev) {
  if (didPan.value) {
    didPan.value = false
    return
  }
  if (dropOp(ev)) return
  selected.value = ''
}

function onNodeClick(n, ev) {
  if (dropOp(ev)) return
  openNode(n.id)
}

function onGhostMove(ev) {
  ghost.x = ev.clientX + 12
  ghost.y = ev.clientY + 12
}

function onPlaceKey(ev) {
  if (ev.key === 'Escape') cancelPlace()
}

function startMove(n, ev) {
  if (ev.button !== 0) return
  if (ev.target?.closest?.('.port')) return
  if (linking.from || placing.value) return
  const start = stagePoint(ev)
  const startX = ev.clientX
  const startY = ev.clientY
  const ox = start.x - n.x
  const oy = start.y - n.y
  let dragging = false
  const move = (e) => {
    if (!dragging && Math.hypot(e.clientX - startX, e.clientY - startY) < 6) return
    dragging = true
    const pt = stagePoint(e)
    n.x = Math.max(8, pt.x - ox)
    n.y = Math.max(8, pt.y - oy)
  }
  const up = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    window.removeEventListener('pointercancel', up)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
  window.addEventListener('pointercancel', up)
  window.addEventListener('mouseup', up)
}

function startLink(n, ev) {
  ev.preventDefault()
  ev.stopPropagation()
  if (ev.button !== 0) return
  const p = portPos(n, 'out')
  linking.from = n.id
  linking.x = p.x
  linking.y = p.y
  const stage = stageRef.value || ev.currentTarget.closest('.stage')
  const move = (e) => {
    const pt = stagePoint(e, stage)
    draft.value = bezier(
      { x: linking.x, y: linking.y },
      { x: pt.x, y: pt.y }
    )
  }
  const up = (e) => {
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
    const el = (typeof document.elementFromPoint === 'function'
      ? document.elementFromPoint(e.clientX, e.clientY)
      : null) || e.target
    const nodeEl = el?.closest?.('.node')
    const toId = nodeEl?.getAttribute('data-id')
    if (toId) endLink(nodeById(toId))
    draft.value = ''
    linking.from = null
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

function endLink(n) {
  if (!n || !linking.from || linking.from === n.id) return
  if (wouldCycle(linking.from, n.id)) {
    ElMessage.warning('不能连成环')
    linking.from = null
    draft.value = ''
    return
  }
  if (!edges.value.some(e => e.from === linking.from && e.to === n.id)) {
    edges.value.push({ from: linking.from, to: n.id })
    pruneAll()
  }
  linking.from = null
  draft.value = ''
}

function removeEdge(i) {
  edges.value.splice(i, 1)
}

function removeNode() {
  const id = selected.value
  nodes.value = nodes.value.filter(n => n.id !== id)
  edges.value = edges.value.filter(e => e.from !== id && e.to !== id)
  selected.value = ''
}

function isNumericCol(name) {
  const meta = columns.value.find(c => c.name === name)
  const inferred = String(meta?.inferred || meta?.role || '').toLowerCase()
  if (/num|float|int|double/.test(inferred)) return true
  if (/cat|str|text|date|bool/.test(inferred)) return false
  return /distance|sales|customers|open|promo2?$|year|week|month|day|hour|competition/i.test(name)
}

const sourceDatasets = computed(() => {
  if (ctx.targetType === 'bundle') {
    const b = bundles.value.find(x => Number(x.id) === Number(ctx.targetId))
    if (!b) return datasets.value
    const ids = new Set((b.dataset_ids || []).map(Number))
    const picked = datasets.value.filter(d => ids.has(Number(d.id)))
    return picked.length ? picked : datasets.value
  }
  const ds = datasets.value.find(d => Number(d.id) === Number(ctx.targetId))
  return ds ? [ds] : datasets.value
})
const sourceFactId = computed(() => {
  if (ctx.targetType === 'bundle') {
    return bundles.value.find(x => Number(x.id) === Number(ctx.targetId))?.fact_dataset_id
  }
  return ctx.targetId
})
function colLabel(name) {
  const meta = columns.value.find(c => c.name === name)
  return columnHeader(name, sourceDatasets.value, { factId: sourceFactId.value, zh: meta?.label_zh })
}

function clipRangeOf(n) {
  if (!n) return []
  if (Array.isArray(n.ranges) && n.ranges.length) {
    return n.ranges.map(g => ({
      columns: Array.isArray(g.columns) ? [...g.columns] : [],
      method: g.method || n.method || 'iqr',
      low: g.low,
      high: g.high
    }))
  }
  return [{
    columns: Array.isArray(n.columns) ? [...n.columns] : [],
    method: n.method || 'iqr',
    low: n.low,
    high: n.high
  }]
}
function ensureClipRanges(n) {
  if (!n || n.op !== 'clip_outlier') return
  n.ranges = clipRangeOf(n)
}

function mergeSequentialClips(steps, edgeList) {
  const nodes = (steps || []).map(s => ({ ...s }))
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]))
  let links = (edgeList || []).map(e => ({ from: e.from, to: e.to }))
  const outs = (id) => links.filter(e => e.from === id).map(e => e.to)
  const ins = (id) => links.filter(e => e.to === id).map(e => e.from)

  if (!links.length) {
    const merged = []
    for (const n of nodes) {
      const prev = merged[merged.length - 1]
      if (n.op === 'clip_outlier' && prev?.op === 'clip_outlier') {
        prev.ranges = [...clipRangeOf(prev), ...clipRangeOf(n)]
        prev.columns = []
        continue
      }
      if (n.op === 'clip_outlier') n.ranges = clipRangeOf(n)
      merged.push(n)
    }
    return { steps: merged, edges: [] }
  }

  let changed = true
  while (changed) {
    changed = false
    for (const n of nodes) {
      if (n._gone || n.op !== 'clip_outlier') continue
      const nextIds = outs(n.id)
      if (nextIds.length !== 1) continue
      const nxt = byId[nextIds[0]]
      if (!nxt || nxt._gone || nxt.op !== 'clip_outlier' || ins(nxt.id).length !== 1) continue
      n.ranges = [...clipRangeOf(n), ...clipRangeOf(nxt)]
      n.columns = []
      const follow = outs(nxt.id)
      links = links.filter(e => e.from !== n.id && e.to !== nxt.id && e.from !== nxt.id)
      for (const to of follow) links.push({ from: n.id, to })
      nxt._gone = true
      changed = true
      break
    }
  }
  const kept = nodes.filter(n => !n._gone)
  const ids = new Set(kept.map(n => n.id))
  const nextEdges = []
  const seen = new Set()
  for (const e of links) {
    if (!ids.has(e.from) || !ids.has(e.to) || e.from === e.to) continue
    const k = `${e.from}>${e.to}`
    if (seen.has(k)) continue
    seen.add(k)
    nextEdges.push({ from: e.from, to: e.to })
  }
  return { steps: kept, edges: nextEdges }
}

function addClipRange() {
  const n = selectedNode.value
  if (!n || n.op !== 'clip_outlier') return
  ensureClipRanges(n)
  n.ranges.push({ columns: [], method: 'range', low: 0, high: 100 })
}
function removeClipRange(i) {
  const n = selectedNode.value
  if (!n || !Array.isArray(n.ranges) || n.ranges.length <= 1) return
  n.ranges.splice(i, 1)
}
function removeRangeCol(group, col) {
  if (!group || !Array.isArray(group.columns)) return
  group.columns = group.columns.filter(c => c !== col)
}

function addFillOverride() {
  const n = selectedNode.value
  if (!n) return
  if (!Array.isArray(n.overrides)) n.overrides = []
  const used = new Set(n.overrides.map(r => r.column))
  const next = fieldOptions.value.find(c => !used.has(c)) || fieldOptions.value[0] || ''
  n.overrides.push({ column: next, strategy: isNumericCol(next) ? 'mean' : 'mode', value: '' })
}

function suggestFillOverrides() {
  const n = selectedNode.value
  if (!n) return
  const live = fieldOptions.value
  const target = (n.columns && n.columns.length) ? n.columns.filter(c => live.includes(c)) : live
  n.overrides = target.map(column => ({
    column,
    strategy: isNumericCol(column) ? 'mean' : 'mode',
    value: ''
  }))
  ElMessage.success('已按类型填入：数值=均值，非数值=众数')
}

const tokenOptions = computed(() => {
  const n = selectedNode.value
  const map = new Map()
  for (const t of probedTokens.value) map.set(t.token, t)
  for (const tok of (n?.tokens || [])) {
    if (!map.has(tok)) map.set(tok, { token: tok, count: 0 })
  }
  return [...map.values()]
})

async function probeTokens() {
  const n = selectedNode.value
  if (!n?.column) return ElMessage.warning('请先选择文本列')
  if (!ctx.targetId) return ElMessage.warning('请先选择数据源')
  probing.value = true
  try {
    const before = stepsBefore(n.id)
    const res = await probeCleanTokens({
      target_type: ctx.targetType,
      target_id: ctx.targetId,
      column: n.column,
      steps: before
    })
    const tokens = res.data?.tokens || []
    probedTokens.value = tokens
    probeMeta.value = { n_unique: res.data?.n_unique, samples: res.data?.samples }
    const picked = tokens.map(t => t.token)
    const current = n.tokens || []
    n.tokens = [...new Set([...current, ...picked])]
    ElMessage.success(`探查到 ${tokens.length} 个标记词，可再增删`)
  } finally {
    probing.value = false
  }
}

const onProjectChange = async () => {
  ctx.targetId = null
  columns.value = []
  await loadSources()
}
const onSourceTypeChange = () => {
  ctx.targetId = sourceOptions.value[0]?.id || null
  loadSchema()
}
const loadSources = async () => {
  if (!ctx.projectId) {
    datasets.value = []
    bundles.value = []
    return
  }
  const [ds, bd] = await Promise.all([
    listDatasets({ project_id: ctx.projectId }),
    listBundles({ project_id: ctx.projectId })
  ])
  datasets.value = unwrapList(ds)
  bundles.value = unwrapList(bd)
  if (!ctx.targetId) ctx.targetId = sourceOptions.value[0]?.id || null
  await loadSchema()
}
const loadSchema = async () => {
  columns.value = []
  if (!ctx.targetId) return
  const res = await getCleanSourceSchema({ target_type: ctx.targetType, target_id: ctx.targetId })
  columns.value = res.data?.columns || []
  for (const n of nodes.value) pruneFields(n)
}

function stepsBefore(nodeId) {
  const ranked = topoNodes().filter(n => ancestorsOf(nodeId).some(p => p.id === n.id))
  return ranked.map(s => serializeStep(s))
}

function serializeStep(s) {
  const step = { ...s }
  if (step.op === 'parse_date') step.extract = Array.isArray(s.extract) ? [...s.extract] : []
  if (step.op === 'split_flags') step.tokens = Array.isArray(s.tokens) ? [...s.tokens] : []
  if (step.op === 'fill_missing') {
    const live = new Set(columnsAt(s.id))
    const raw = Array.isArray(s.overrides) ? s.overrides : []
    const overrides = live.size
      ? raw.filter(r => r.column && live.has(r.column))
      : raw.filter(r => r.column)
    step.column_strategies = overrides
    delete step.overrides
    if (Array.isArray(step.columns) && step.columns.length) {
      step.columns = live.size ? step.columns.filter(c => live.has(c)) : step.columns
      if (!step.columns.length) delete step.columns
    } else {
      delete step.columns
    }
  }
  if (step.op === 'clip_outlier') {
    step.ranges = clipRangeOf(s).map(g => ({
      columns: [...(g.columns || [])],
      method: g.method || s.method || 'iqr',
      low: g.low,
      high: g.high
    }))
    delete step.columns
    delete step.low
    delete step.high
  }
  if (step.auto_mode) step.columns = []
  if ((step.op === 'drop_duplicates' || step.op === 'drop_null_rows') && (!step.columns || !step.columns.length)) delete step.columns
  return step
}

function runSteps() {
  return executableNodes().map(serializeStep)
}

function canvasSteps() {
  return nodes.value.map(serializeStep)
}

const doPreview = async () => {
  if (!ctx.targetId) return ElMessage.warning('请先选择数据源')
  if (!nodes.value.length) return ElMessage.warning('请先拖入组件')
  if (nodes.value.length > 1 && !executableNodes().length) return ElMessage.warning('请先把节点拉线连起来')
  const skipped = nodes.value.length - executableNodes().length
  if (skipped > 0) ElMessage.info(`有 ${skipped} 个未连线组件，试运行已跳过`)
  previewing.value = true
  try {
    const res = await previewClean({
      target_type: ctx.targetType,
      target_id: ctx.targetId,
      steps: runSteps(),
      edges: edges.value
    })
    after.value = res.data?.after?.records || []
    afterCols.value = res.data?.after?.columns || []
    logs.value = res.data?.logs || []
    previewOpen.value = true
    if (!selected.value && executableNodes()[0]) openNode(executableNodes()[0].id)
  } finally {
    previewing.value = false
  }
}

const save = async () => {
  if (!form.name.trim()) return ElMessage.warning('请填写规则名称')
  if (!nodes.value.length) return ElMessage.warning('请至少拖入一个组件')
  if (nodes.value.length > 1 && !executableNodes().length) return ElMessage.warning('请先把节点拉线连起来')
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description || '',
      scenario_code: userStore.scenario || 'store_sales',
      steps: canvasSteps(),
      edges: edges.value,
      source: {
        project_id: ctx.projectId,
        target_type: ctx.targetType,
        target_id: ctx.targetId
      }
    }
    const res = await saveRule(payload, form.id)
    ElMessage.success(fromDag.value ? '规则已保存，可返回 DAG 编排' : '规则已保存')
    if (isNew.value && res.data?.id) {
      await router.replace({ path: `/clean/rule/${res.data.id}`, query: { ...route.query } })
      form.id = res.data.id
    } else {
      form.id = res.data?.id || form.id
    }
  } finally {
    saving.value = false
  }
}

function backToDag() {
  const dagId = route.query.dagId
  if (!dagId) return router.push('/dag')
  const query = {}
  if (route.query.nodeId) query.node = route.query.nodeId
  if (form.id) query.rule_id = String(form.id)
  router.push({ path: `/dag/${dagId}`, query })
}

const boot = async () => {
  booting.value = true
  try {
    const [opRes, pj] = await Promise.all([
      listOps(),
      listProjects()
    ])
    const data = opRes.data || {}
    ops.value = Array.isArray(data) ? data : (data.ops || [])
    categories.value = Array.isArray(data) ? {} : (data.categories || {})
    projects.value = unwrapList(pj)
    ctx.projectId = null
    ctx.targetType = 'bundle'
    ctx.targetId = null
    if (!isNew.value) {
      const res = await getRule(route.params.id)
      const rule = res.data
      if (!rule) {
        ElMessage.error('规则不存在')
        return fromDag.value ? backToDag() : router.push('/clean')
      }
      form.id = rule.id
      form.name = rule.name
      form.description = rule.description || ''
      const merged = mergeSequentialClips(rule.steps || [], Array.isArray(rule.edges) ? rule.edges : [])
      nodes.value = layoutFromSteps(merged.steps)
      edges.value = sanitizeEdges(merged.edges)
      const src = rule.source || {}
      if (src.project_id) ctx.projectId = Number(src.project_id)
      if (src.target_type) ctx.targetType = src.target_type
      if (src.target_id) ctx.targetId = Number(src.target_id)
    } else {
      form.name = ''
      form.description = ''
      nodes.value = []
      edges.value = []
    }
    if (!ctx.projectId) ctx.projectId = projects.value[0]?.id || null
    selected.value = ''
    await loadSources()
  } finally {
    booting.value = false
  }
}

watch(() => [selected.value, edges.value, nodes.value.map(n => [n.op, n.columns, n.extract, n.tokens, n.prefix])], () => {
  pruneAll()
}, { deep: true })
watch(() => route.fullPath, boot)
onMounted(() => {
  window.addEventListener('pointermove', onGhostMove)
  window.addEventListener('keydown', onPlaceKey)
  boot()
})
onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onGhostMove)
  window.removeEventListener('keydown', onPlaceKey)
})
</script>

<style scoped>
.studio {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 12px;
  min-height: calc(100vh - 120px);
}
.has-drawer .stage { padding-bottom: 260px; }
.palette {
  flex: 0 0 250px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  overflow: auto;
  box-shadow: var(--shadow);
  max-height: calc(100vh - 120px);
}
.palette h2 { font-size: 18px; margin: 6px 0 4px; }
.palette p { color: var(--muted); font-size: 12px; line-height: 1.5; }
.comp {
  display: flex;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  margin-bottom: 6px;
  cursor: pointer;
  background: var(--panel-soft);
}
.comp.picking {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.sec, .cat-name {
  margin: 14px 0 6px;
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--muted);
  font-weight: 700;
  text-transform: uppercase;
}
.comp i, .node i {
  width: 8px;
  border-radius: 99px;
  flex: 0 0 8px;
}
.comp b, .node b { display: block; font-size: 13px; }
.comp span, .node em, .muted { color: var(--muted); font-size: 12px; font-style: normal; }
.stage-wrap {
  position: relative;
  flex: 1 1 640px;
  min-width: 0;
  min-height: 560px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.stage-toolbar {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 8;
  display: flex;
  gap: 8px;
}
.studio.placing,
.stage.placing {
  cursor: copy;
}
.place-ghost {
  position: fixed;
  z-index: 40;
  pointer-events: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fff;
  border: 1px dashed var(--accent);
  border-radius: 10px;
  box-shadow: 0 8px 22px rgba(26, 36, 51, 0.16);
  min-width: 140px;
}
.place-ghost i {
  width: 8px;
  height: 28px;
  border-radius: 99px;
}
.place-ghost span { font-size: 13px; font-weight: 700; }
.place-ghost em {
  display: block;
  font-size: 11px;
  font-style: normal;
  color: var(--muted);
}
.stage {
  position: relative;
  overflow: auto;
  flex: 1;
  min-width: 0;
  width: 100%;
  min-height: 560px;
  background: #f7fafc;
  border: 1px solid var(--line);
  border-radius: 14px;
  cursor: grab;
}
.stage.placing { cursor: copy; }
.stage.panning,
.stage.panning * { cursor: grabbing !important; }
.world { position: relative; }
.world-inner {
  position: relative;
  background:
    radial-gradient(circle at 1px 1px, #d5dee8 1px, transparent 0) 0 0 / 22px 22px,
    #f7fafc;
}
.zoom-badge {
  position: absolute;
  left: 12px;
  top: 12px;
  z-index: 8;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.92);
  color: var(--text);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--shadow);
}
.zoom-badge:hover { border-color: var(--accent); color: var(--accent); }
.stage[data-linking]:not([data-linking='']) {
  cursor: crosshair;
}
.stage[data-linking]:not([data-linking='']) .node {
  cursor: crosshair;
}
.wires { position: absolute; inset: 0; pointer-events: none; z-index: 0; }
.wire { pointer-events: stroke; cursor: pointer; }
.node {
  position: absolute;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
  cursor: grab;
  user-select: none;
  padding: 0 14px 0 12px;
}
.node.on { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.node.orphan { border-style: dashed; opacity: 0.86; }
.port {
  position: absolute;
  top: 50%;
  width: 14px;
  height: 14px;
  margin-top: -7px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #1d6fd8;
  z-index: 4;
  cursor: crosshair;
  box-sizing: border-box;
}
.port::after {
  content: '';
  position: absolute;
  inset: -14px;
}
.port.in { left: -8px; border-color: #0f766e; }
.port.out { right: -8px; }
.ord {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: grid;
  place-items: center;
  flex: 0 0 22px;
}
.empty-hint {
  position: absolute;
  inset: 40% 0 auto;
  text-align: center;
  color: var(--muted);
  pointer-events: none;
}
.drawer {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 0;
  z-index: 6;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 16px 16px 12px 12px;
  box-shadow: 0 -12px 32px rgba(26, 36, 51, 0.14);
  max-height: 46%;
  min-height: 200px;
  display: flex;
  flex-direction: column;
}
.grabber {
  width: 42px;
  height: 4px;
  border-radius: 99px;
  background: #d4dce6;
  margin: 8px auto 0;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px 8px;
  border-bottom: 1px solid var(--line);
}
.drawer-head p { color: var(--muted); font-size: 12px; margin-top: 2px; }
.drawer-ops { display: flex; gap: 6px; flex-wrap: wrap; align-items: flex-start; }
.drawer-body {
  padding: 12px 16px 16px;
  overflow: auto;
}
.cfg :deep(.el-form-item) { margin-bottom: 10px; }
.cfg :deep(.el-select), .cfg :deep(.el-input) { width: 100%; }
.cfg :deep(.el-checkbox-group) { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.field-select :deep(.el-select__wrapper) {
  height: auto !important;
  min-height: 32px;
  align-items: flex-start;
}
.field-select :deep(.el-select__selection) {
  flex-wrap: wrap;
  height: auto;
}
.field-select :deep(.el-tag) {
  height: auto;
  white-space: normal;
  line-height: 1.4;
  max-width: 100%;
}
.field-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 8px;
}
.field-chips .el-tag {
  max-width: 100%;
  height: auto;
  white-space: normal;
  line-height: 1.4;
  padding: 4px 8px;
  word-break: break-all;
}
.hint { color: var(--muted); font-size: 12px; line-height: 1.5; margin: 0 0 8px; }
.token-tools { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.override-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  margin: 4px 0 8px;
}
.clip-group {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px 4px;
  margin-bottom: 10px;
  background: var(--panel-soft);
}
.override-row {
  display: grid;
  grid-template-columns: minmax(140px, 1.2fr) 120px minmax(80px, 0.8fr) auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.log { color: var(--muted); font-size: 12px; line-height: 1.5; margin-bottom: 8px; }
.sheet-enter-active, .sheet-leave-active { transition: transform 0.22s ease, opacity 0.22s ease; }
.sheet-enter-from, .sheet-leave-to { transform: translateY(24px); opacity: 0; }
@media (max-width: 1100px) {
  .override-row { grid-template-columns: 1fr; }
}
</style>
