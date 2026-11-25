<template>
  <div>
    <div class="page-head">
      <div>
        <h2>数据源配置</h2>
        <p>登记 MySQL 等数据库连接，测试通过后可在「新建数据表」里多选库、多选表导入。</p>
      </div>
      <el-button type="primary" @click="openEdit()">新建数据源</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="rows" stripe empty-text="还没有数据源，先新建一条 MySQL 连接">
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ engineLabel(row.engine) }}</template>
        </el-table-column>
        <el-table-column label="连接" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.host }}:{{ row.port }} / {{ row.username }}</template>
        </el-table-column>
        <el-table-column prop="database_name" label="默认库" min-width="130" show-overflow-tooltip />
        <el-table-column prop="remark" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button link type="success" :loading="row._testing" @click="testRow(row)">测试</el-button>
            <el-button link type="primary" @click="browse(row)">浏览库表</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <ListPager
        v-model:page="page"
        v-model:pageSize="pageSize"
        :total="total"
        @change="onPager"
      />
    </el-card>

    <el-dialog v-model="dialog.visible" :title="dialog.id ? '编辑数据源' : '新建数据源'" width="560px" destroy-on-close>
      <el-form label-width="96px" :model="dialog.form">
        <el-form-item label="名称" required>
          <el-input v-model="dialog.form.name" placeholder="例如：生产 MySQL / 本机分析库" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="dialog.form.engine" style="width: 100%">
            <el-option label="MySQL" value="mysql" />
            <el-option label="MariaDB" value="mariadb" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机" required>
          <el-input v-model="dialog.form.host" placeholder="127.0.0.1" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="dialog.form.port" :min="1" :max="65535" controls-position="right" style="width: 160px" />
        </el-form-item>
        <el-form-item label="账号">
          <el-input v-model="dialog.form.username" placeholder="root" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="dialog.form.password"
            type="password"
            show-password
            :placeholder="dialog.id ? '不修改请留空' : '数据库密码'"
          />
        </el-form-item>
        <el-form-item label="默认库">
          <el-input v-model="dialog.form.database_name" placeholder="可选，例如 insight_forge" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dialog.form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :loading="dialog.testing" @click="testForm">测试连接</el-button>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="viewer.visible" :title="'浏览 · ' + (viewer.row?.name || '')" size="52%">
      <el-form label-width="88px">
        <el-form-item label="数据库">
          <el-select
            v-model="viewer.dbs"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="可多选库"
            style="width: 100%"
            :loading="viewer.loadingDbs"
            @change="loadTables"
          >
            <el-option v-for="d in viewer.dbOptions" :key="d.name" :label="d.name" :value="d.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-table :data="pagedViewerTables" v-loading="viewer.loadingTables" height="520" size="small">
        <el-table-column prop="database" label="库" width="160" />
        <el-table-column prop="table" label="表" min-width="180" />
        <el-table-column prop="rows" label="约行数" width="100" />
        <el-table-column prop="comment" label="注释" min-width="160" show-overflow-tooltip />
      </el-table>
      <ListPager
        v-model:page="viewer.page"
        v-model:pageSize="viewer.pageSize"
        :total="viewer.total"
        @change="onViewerPager"
      />
      <p class="hint">在「数据集配置 → 新建数据表 → 从数据源导入」中勾选这些表即可写入平台。</p>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteDataSource, listDataSources, listSourceDatabases, listSourceTables, saveDataSource, testDataSource
} from '@/api'
import ListPager from '@/components/ListPager.vue'
import { slicePage, unwrapPage } from '@/utils/paging'

const rows = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const dialog = reactive({
  visible: false,
  saving: false,
  testing: false,
  id: null,
  form: blankForm()
})
const viewer = reactive({
  visible: false,
  row: null,
  dbs: [],
  dbOptions: [],
  tables: [],
  loadingDbs: false,
  loadingTables: false,
  page: 1,
  pageSize: 10,
  total: 0
})

const pagedViewerTables = computed(() => slicePage(viewer.tables, viewer.page, viewer.pageSize))

function blankForm() {
  return {
    name: '',
    engine: 'mysql',
    host: '127.0.0.1',
    port: 3306,
    username: 'root',
    password: '',
    database_name: '',
    remark: ''
  }
}

function engineLabel(e) {
  return ({ mysql: 'MySQL', mariadb: 'MariaDB' }[e] || e || 'MySQL')
}

const load = async () => {
  const packed = unwrapPage(await listDataSources({ page: page.value, page_size: pageSize.value }))
  rows.value = packed.items
  total.value = packed.total
  if (!rows.value.length && total.value > 0 && page.value > 1) {
    page.value -= 1
    return load()
  }
}

const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  load()
}

const onViewerPager = ({ page: p, pageSize: s }) => {
  viewer.page = p
  viewer.pageSize = s
}

const openEdit = (row) => {
  dialog.id = row?.id || null
  dialog.form = row
    ? {
        name: row.name,
        engine: row.engine || 'mysql',
        host: row.host,
        port: row.port || 3306,
        username: row.username || 'root',
        password: '',
        database_name: row.database_name || '',
        remark: row.remark || ''
      }
    : blankForm()
  dialog.visible = true
}

const testForm = async () => {
  if (!dialog.form.host) return ElMessage.warning('请填写主机地址')
  dialog.testing = true
  try {
    const res = await testDataSource({ ...dialog.form, id: dialog.id }, dialog.id)
    ElMessage.success(`连接成功 · ${res.data?.version || ''} · ${res.data?.database_count || 0} 个业务库`)
  } finally {
    dialog.testing = false
  }
}

const testRow = async (row) => {
  row._testing = true
  try {
    const res = await testDataSource({}, row.id)
    ElMessage.success(`${row.name} 连接成功 · ${res.data?.version || ''}`)
  } finally {
    row._testing = false
  }
}

const save = async () => {
  if (!dialog.form.name.trim()) return ElMessage.warning('请填写名称')
  if (!dialog.form.host.trim()) return ElMessage.warning('请填写主机')
  dialog.saving = true
  try {
    await saveDataSource(dialog.form, dialog.id)
    ElMessage.success('数据源已保存')
    dialog.visible = false
    await load()
  } finally {
    dialog.saving = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(`删除数据源「${row.name}」？不会删除已经导入的数据表。`, '确认', { type: 'warning' })
  await deleteDataSource(row.id)
  ElMessage.success('已删除')
  await load()
}

const browse = async (row) => {
  viewer.row = row
  viewer.visible = true
  viewer.dbs = []
  viewer.tables = []
  viewer.page = 1
  viewer.total = 0
  viewer.loadingDbs = true
  try {
    const res = await listSourceDatabases(row.id)
    viewer.dbOptions = res.data?.items || []
    const def = res.data?.default
    viewer.dbs = def && viewer.dbOptions.some(d => d.name === def) ? [def] : []
    if (viewer.dbs.length) await loadTables()
  } finally {
    viewer.loadingDbs = false
  }
}

const loadTables = async () => {
  if (!viewer.row || !viewer.dbs.length) {
    viewer.tables = []
    viewer.total = 0
    viewer.page = 1
    return
  }
  viewer.loadingTables = true
  try {
    const res = await listSourceTables(viewer.row.id, viewer.dbs)
    viewer.tables = res.data?.items || []
    viewer.total = viewer.tables.length
    viewer.page = 1
  } finally {
    viewer.loadingTables = false
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin-top: 12px; color: var(--muted); font-size: 13px; }
</style>
