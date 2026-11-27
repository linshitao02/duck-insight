<template>
  <div class="tp-page">
    <div class="tp-head">
      <div>
        <h2>Kafka 主题</h2>
        <p class="sub">同步任务勾表后会自动在此登记主题；也可以手工补建。命名建议使用下划线，例如 <code>cdc_ecommerce_oms_order_item</code>。</p>
      </div>
      <div class="tp-actions">
        <el-button @click="loadTopics" :loading="loading">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建主题</el-button>
      </div>
    </div>

    <el-card shadow="never" class="table-card">
      <el-table :data="topics" v-loading="loading" empty-text="还没有 Kafka 主题">
        <el-table-column prop="name" label="主题名称" min-width="240">
          <template #default="{ row }">
            <code>{{ row.name }}</code>
            <el-tag v-if="row.cluster_only" size="small" type="info" style="margin-left: 8px">集群发现</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="partitions" label="分区数" width="90" />
        <el-table-column prop="replication_factor" label="副本数" width="90" />
        <el-table-column label="保留时长" width="110">
          <template #default="{ row }">
            {{ Math.round((row.retention_ms || 604800000) / 86400000) }} 天
          </template>
        </el-table-column>
        <el-table-column label="来源任务" width="120">
          <template #default="{ row }">
            <el-link v-if="row.source_task_id" type="primary" @click="router.push(`/realtime/tasks/${row.source_task_id}`)">
              任务 #{{ row.source_task_id }}
            </el-link>
            <span v-else class="muted">手工创建</span>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="200" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-popconfirm v-if="!row.cluster_only" title="确定移除该主题记录？" @confirm="onDelete(row)">
              <template #reference>
                <el-button link type="danger">移除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogOpen" title="新建 Kafka 主题" width="460px">
      <el-form label-width="96px">
        <el-form-item label="主题名称" required>
          <el-input v-model="form.name" placeholder="例如：cdc_ecommerce_oms_order" />
        </el-form-item>
        <el-form-item label="分区数">
          <el-input-number v-model="form.partitions" :min="1" :max="32" />
        </el-form-item>
        <el-form-item label="副本数">
          <el-input-number v-model="form.replication_factor" :min="1" :max="3" />
        </el-form-item>
        <el-form-item label="保留天数">
          <el-input-number v-model="form.retention_days" :min="1" :max="90" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" placeholder="用途说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createKafkaTopic, deleteKafkaTopic, listKafkaTopics } from '@/api'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const dialogOpen = ref(false)
const topics = ref([])
const form = reactive({
  name: '',
  partitions: 1,
  replication_factor: 1,
  retention_days: 7,
  remark: ''
})

async function loadTopics() {
  loading.value = true
  try {
    const res = await listKafkaTopics()
    topics.value = res.data || []
  } catch (e) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = ''
  form.partitions = 1
  form.replication_factor = 1
  form.retention_days = 7
  form.remark = ''
  dialogOpen.value = true
}

async function onCreate() {
  if (!form.name.trim()) return ElMessage.warning('请填写主题名称')
  saving.value = true
  try {
    const res = await createKafkaTopic({ ...form })
    ElMessage.success(res.data?.cluster_synced ? '主题已在 Kafka 创建' : '主题已登记到目录')
    dialogOpen.value = false
    loadTopics()
  } catch (e) {
    ElMessage.error(e?.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await deleteKafkaTopic(row.name)
    ElMessage.success('已移除')
    loadTopics()
  } catch (e) {
    ElMessage.error(e?.message || '移除失败')
  }
}

onMounted(loadTopics)
</script>

<style scoped>
.tp-page { display: flex; flex-direction: column; gap: 14px; }
.tp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.tp-head h2 { margin: 0 0 4px; font-size: 20px; color: #0f172a; }
.sub { margin: 0; font-size: 13px; color: #64748b; }
.tp-actions { display: flex; gap: 8px; }
.table-card { border-radius: 10px; }
.muted { font-size: 12px; color: #94a3b8; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; color: #0f172a; }
</style>
