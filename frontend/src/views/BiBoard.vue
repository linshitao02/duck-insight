<template>
  <div>
    <div class="page-head">
      <div>
        <h2>BI 看板</h2>
        <p>FineBI 风格自助分析：导入数据、拖入图表模板、绑定维度与指标。发布后由 Plotly Dash 渲染交互看板。</p>
      </div>
      <div class="head-actions">
        <el-button @click="openImport">导入数据</el-button>
        <el-button type="primary" @click="openCreate">新建看板</el-button>
      </div>
    </div>

    <section class="tpl-row">
      <button
        v-for="tpl in templates"
        :key="tpl.key"
        class="tpl-card"
        @click="openCreate(tpl.key)"
      >
        <b>{{ tpl.label }}</b>
        <span>{{ tpl.desc }}</span>
      </button>
    </section>

    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>我的看板</span>
          <el-radio-group v-model="scope" size="small" @change="load">
            <el-radio-button label="scene">当前场景</el-radio-button>
            <el-radio-button label="all">全部</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <div v-if="boards.length" class="board-grid">
        <article
          v-for="row in boards"
          :key="row.id"
          class="board-card"
          @click="$router.push(`/bi/${row.id}`)"
        >
          <div class="cover" :style="{ background: row.cover_color || '#1d6fd8' }">
            <span>{{ row.widget_count || 0 }} 个组件</span>
          </div>
          <div class="body">
            <h3>{{ row.name }}</h3>
            <p>{{ row.description || '暂无说明' }}</p>
            <div class="meta">
              <el-tag size="small" type="info">{{ sceneText(row.scenario_code) }}</el-tag>
              <span>{{ fmtTime(row.update_time || row.create_time) }}</span>
            </div>
            <div class="ops" @click.stop>
              <el-button link type="primary" @click="$router.push(`/bi/${row.id}/view`)">Dash 预览</el-button>
              <el-button link type="primary" @click="$router.push(`/bi/${row.id}`)">编辑</el-button>
              <el-button link type="danger" @click="removeOne(row)">删除</el-button>
            </div>
          </div>
        </article>
      </div>
      <el-empty v-else description="还没有看板，点击右上角新建或选用上方模板" />
      <ListPager
        v-model:page="page"
        v-model:pageSize="pageSize"
        :total="total"
        @change="onPager"
      />
    </el-card>

    <el-dialog v-model="create.visible" title="新建看板" width="560px" destroy-on-close>
      <el-form label-width="96px">
        <el-form-item label="名称" required>
          <el-input v-model="create.name" placeholder="例如：气象-负荷-出力-电价监测看板" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="模板">
          <el-select v-model="create.template" style="width: 100%">
            <el-option v-for="tpl in templates" :key="tpl.key" :label="tpl.label" :value="tpl.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据">
          <el-select v-model="create.sourceKey" filterable style="width: 100%" placeholder="选择数据表或逻辑数据集">
              <el-option-group label="数据表 / 实时库表">
                <el-option
                  v-for="ds in sources.datasets"
                  :key="'d' + ds.id"
                  :label="`${ds.name}${ds.is_live ? '（直连库表）' : ''}（${ds.n_rows || 0} 行）`"
                  :value="`dataset:${ds.id}`"
                />
              </el-option-group>
            <el-option-group label="逻辑数据集">
              <el-option
                v-for="b in sources.bundles"
                :key="'b' + b.id"
                :label="`${b.name}（${b.n_rows || 0} 行）`"
                :value="`bundle:${b.id}`"
              />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="create.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="create.visible = false">取消</el-button>
        <el-button type="primary" :loading="create.loading" @click="confirmCreate">创建并设计</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="imp.visible" title="导入数据到数据空间" width="480px" destroy-on-close>
      <el-form label-width="96px">
        <el-form-item label="数据集配置" required>
          <el-select v-model="imp.projectId" style="width: 100%" placeholder="选择已有数据空间">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            drag
            multiple
            :auto-upload="false"
            :on-change="onFiles"
            :on-remove="onRemoveFile"
            accept=".csv,.xlsx,.xls,.txt"
          >
            <div class="el-upload__text">将 CSV / Excel 拖到此处，或点击上传</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="imp.visible = false">取消</el-button>
        <el-button type="primary" :loading="imp.loading" @click="confirmImport">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { biCatalog, biSources, listBoards, saveBoard, deleteBoard, listProjects, uploadDatasets } from '@/api'
import ListPager from '@/components/ListPager.vue'
import { unwrapList, unwrapPage } from '@/utils/paging'

const router = useRouter()
const userStore = useUserStore()
const boards = ref([])
const templates = ref([])
const sources = reactive({ datasets: [], bundles: [] })
const projects = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const scope = ref('all')
const create = reactive({
  visible: false, name: '', description: '', template: 'blank', sourceKey: '', loading: false
})
const imp = reactive({ visible: false, projectId: null, files: [], loading: false })

const sceneText = (code) => ({
  store_sales: '商店销售',
  power_trading: '电力交易',
  generic: '通用'
}[code] || code || '通用')

const fmtTime = (t) => {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(0, 16)
}

const parseSource = (key) => {
  if (!key) return null
  const [kind, id] = String(key).split(':')
  return { kind, id: Number(id) }
}

const load = async () => {
  const packed = unwrapPage(await listBoards({
    page: page.value,
    page_size: pageSize.value,
    scenario: scope.value === 'scene' ? userStore.scenario : undefined
  }))
  boards.value = packed.items
  total.value = packed.total
}

const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  load()
}

const loadMeta = async () => {
  const [cat, src, pro] = await Promise.all([biCatalog(), biSources({}), listProjects()])
  templates.value = cat.data?.templates || []
  sources.datasets = src.data?.datasets || []
  sources.bundles = src.data?.bundles || []
  projects.value = unwrapList(pro)
}

const openCreate = (tpl) => {
  const key = typeof tpl === 'string' ? tpl : 'blank'
  create.name = key === 'power_monitor'
    ? '气象-负荷-出力-电价监测看板'
    : (key === 'realtime' ? '电力实时监测看板（实时库表）' : '')
  create.description = ''
  create.template = key
  const live = sources.datasets.find(d => d.is_live)
  const wide = sources.datasets.find(d => d.name && d.name.includes('负荷风光'))
  const pick = key === 'realtime' ? (live || wide) : (wide || live)
  create.sourceKey = pick ? `dataset:${pick.id}` : (sources.datasets[0] ? `dataset:${sources.datasets[0].id}` : '')
  create.visible = true
}

const confirmCreate = async () => {
  if (!create.name.trim()) return ElMessage.warning('请填写看板名称')
  const source = parseSource(create.sourceKey)
  if (!source?.id) return ElMessage.warning('请选择数据')
  create.loading = true
  try {
    const res = await saveBoard({
      name: create.name.trim(),
      description: create.description,
      template: create.template,
      source,
      scenario_code: create.template === 'power_monitor' ? 'power_trading' : (userStore.scenario || 'generic'),
      project_id: (sources.datasets.find(d => d.id === source.id) || {}).project_id
    })
    create.visible = false
    ElMessage.success('看板已创建')
    if (res.data?.id) router.push(`/bi/${res.data.id}`)
    else load()
  } finally {
    create.loading = false
  }
}

const openImport = () => {
  imp.projectId = projects.value[0]?.id || null
  imp.files = []
  imp.visible = true
}

const onFiles = (_file, fileList) => { imp.files = fileList }
const onRemoveFile = (_file, fileList) => { imp.files = fileList }

const confirmImport = async () => {
  if (!imp.projectId) return ElMessage.warning('请选择数据集配置')
  const raw = (imp.files || []).map(f => f.raw).filter(Boolean)
  if (!raw.length) return ElMessage.warning('请选择文件')
  const form = new FormData()
  raw.forEach(f => form.append('files', f))
  form.append('project_id', imp.projectId)
  form.append('scenario', userStore.scenario || 'generic')
  imp.loading = true
  try {
    await uploadDatasets(form)
    ElMessage.success('已导入，可在新建看板时选择该表')
    imp.visible = false
    await loadMeta()
  } finally {
    imp.loading = false
  }
}

const removeOne = async (row) => {
  await ElMessageBox.confirm(`确认删除看板「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteBoard(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(async () => {
  await loadMeta()
  await load()
})
</script>

<style scoped>
.head-actions { display: flex; gap: 8px; }
.tpl-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.tpl-card {
  text-align: left;
  border: 1px dashed var(--line);
  background: var(--panel);
  border-radius: 12px;
  padding: 14px 16px;
  cursor: pointer;
}
.tpl-card:hover { border-color: var(--accent); }
.tpl-card b { display: block; font-size: 14px; }
.tpl-card span { display: block; margin-top: 6px; color: var(--muted); font-size: 12px; line-height: 1.45; }
.board-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.board-card {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  background: var(--panel);
}
.board-card:hover { border-color: var(--accent); }
.cover {
  height: 88px;
  color: #fff;
  display: flex;
  align-items: flex-end;
  padding: 10px 12px;
  font-size: 12px;
  opacity: 0.95;
}
.body { padding: 12px 14px 8px; }
.body h3 { font-size: 15px; }
.body p {
  margin-top: 6px;
  color: var(--muted);
  font-size: 12px;
  min-height: 34px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; color: var(--muted); font-size: 12px; }
.ops { display: flex; gap: 4px; margin-top: 4px; }
@media (max-width: 960px) {
  .tpl-row { grid-template-columns: 1fr 1fr; }
}
</style>
