<template>
  <div>
    <div class="page-head">
      <div>
        <h2>数据集配置</h2>
        <p>先创建数据集配置（例如「Rossmann 门店销量分析」或「极端天气负荷与风光出力」），再进入后上传数据表并配置多表关联。</p>
      </div>
      <el-button type="primary" @click="openCreate">新建数据集配置</el-button>
    </div>

    <section class="block-card panel">
      <div class="task-grid">
        <button type="button" class="task-square add-square" @click="openCreate">
          <span class="plus">+</span>
          <span class="add-title">新建数据集配置</span>
          <span class="add-desc">进入后上传表并关联</span>
        </button>

        <div
          v-for="row in projects"
          :key="row.id"
          class="task-square"
          @click="goWorkspace(row)"
        >
          <button type="button" class="del" title="删除" @click.stop="removeProject(row)">×</button>
          <div class="sq-icon">{{ (row.name || '任').slice(0, 1) }}</div>
          <div class="sq-name" :title="row.name">{{ row.name }}</div>
          <div class="sq-scene">{{ sceneName(row.scenario_code) }}</div>
          <div class="sq-meta">{{ row.description || '暂无描述' }}</div>
          <div class="sq-stats">
            <span>{{ row.dataset_count || 0 }} 张表</span>
            <span>{{ row.bundle_count || 0 }} 个关联</span>
          </div>
        </div>
      </div>
      <div v-if="!projects.length && !total" class="empty-hint">
        还没有数据集配置。创建一个后，再在其中上传数据表并做关联。
      </div>

      <ListPager
        v-model:page="page"
        v-model:pageSize="pageSize"
        :total="total"
        @change="onPager"
      />
    </section>

    <el-dialog v-model="create.visible" title="新建数据集配置" width="480px" destroy-on-close>
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="任务名称" required>
          <el-input
            v-model="create.name"
            placeholder="例如：Rossmann 门店销量分析"
            maxlength="64"
            show-word-limit
            @keyup.enter="confirmCreate"
          />
        </el-form-item>
        <el-form-item label="说明">
          <el-input
            v-model="create.description"
            type="textarea"
            :rows="3"
            placeholder="可选，说明本任务的分析目标"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="create.visible = false">取消</el-button>
        <el-button type="primary" :loading="create.loading" @click="confirmCreate">创建并进入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { listProjects, createProject, deleteProject } from '@/api'
import ListPager from '@/components/ListPager.vue'
import { unwrapPage } from '@/utils/paging'

const router = useRouter()
const userStore = useUserStore()
const projects = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const create = reactive({
  visible: false,
  name: '',
  description: '',
  loading: false
})

const load = async () => {
  const packed = unwrapPage(await listProjects({ page: page.value, page_size: pageSize.value }))
  projects.value = packed.items
  total.value = packed.total
  if (!projects.value.length && total.value > 0 && page.value > 1) {
    page.value -= 1
    return load()
  }
}

const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  load()
}

const sceneName = (code) => ({
  store_sales: '商店销售',
  ecommerce: '电商分析',
  power_trading: '电力交易',
  generic: '通用'
}[code] || code || '')

const openCreate = () => {
  create.name = ''
  create.description = ''
  create.visible = true
}

const confirmCreate = async () => {
  if (!create.name.trim()) return ElMessage.warning('请填写数据集配置名称')
  create.loading = true
  try {
    const res = await createProject({
      name: create.name.trim(),
      description: create.description || '',
      scenario_code: userStore.scenario || 'store_sales'
    })
    create.visible = false
    ElMessage.success('数据集配置已创建')
    if (res.data?.id) {
      router.push(`/dataset/workspace/${res.data.id}`)
    } else {
      await load()
    }
  } finally {
    create.loading = false
  }
}

const goWorkspace = (row) => router.push(`/dataset/workspace/${row.id}`)

const removeProject = async (row) => {
  await ElMessageBox.confirm(
    `确认删除数据集配置「${row.name}」？其下的数据表与逻辑数据集也会一并删除。`,
    '删除确认',
    { type: 'warning' }
  )
  await deleteProject(row.id)
  ElMessage.success('已删除')
  load()
}

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
.empty-hint { color: var(--muted); font-size: 13px; padding: 8px 0 4px; }

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
  margin-top: 8px;
  font-weight: 700;
  font-size: 14px;
  color: var(--text);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sq-scene {
  margin-top: 4px;
  font-size: 11px;
  color: var(--accent);
  font-weight: 600;
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
</style>
