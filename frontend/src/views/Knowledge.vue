<template>
  <div class="kb-page">
    <div class="page-head">
      <div>
        <h2>知识库 RAG</h2>
        <p>文档切片入库后供 DAG 报告召回。用户短问题检索分块，系统提示词控制报告文风。</p>
      </div>
      <el-upload :show-file-list="false" accept=".pdf,.md,.txt,.docx" :http-request="upload">
        <el-button type="primary">上传文档</el-button>
      </el-upload>
    </div>

    <div class="stat-grid">
      <article class="stat" :class="{ on: status.ready }">
        <span>索引状态</span>
        <strong>{{ status.ready ? '已就绪' : '未就绪' }}</strong>
        <small>{{ status.ready ? '可供 DAG / 问答召回' : (status.error || '等待重建索引') }}</small>
      </article>
      <article class="stat">
        <span>知识文档</span>
        <strong>{{ status.file_count ?? 0 }}</strong>
        <small>支持 PDF / Markdown / TXT / Word</small>
      </article>
      <article class="stat">
        <span>文本分块</span>
        <strong>{{ status.chunk_count ?? 0 }}</strong>
        <small>{{ status.chunker_label || 'Recursive Splitter' }} · {{ status.chunk_size || 480 }}/{{ status.chunk_overlap || 80 }}</small>
      </article>
      <article class="stat">
        <span>向量库</span>
        <strong>FAISS</strong>
        <small>{{ status.index_label || 'IndexFlatIP' }} · {{ status.embedder_label || '哈希 384 维' }}</small>
      </article>
    </div>
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>文档列表</span>
          <div class="head-ops">
            <el-input v-model="keyword" placeholder="按文件名筛选" clearable style="width: 220px" @keyup.enter="load(1)" />
            <el-button size="small" @click="load(1)">查询</el-button>
            <el-button size="small" @click="rebuild">重建索引</el-button>
          </div>
        </div>
      </template>
      <el-table :data="docs" stripe highlight-current-row @row-click="openDoc">
        <el-table-column prop="name" label="文件" min-width="240" show-overflow-tooltip />
        <el-table-column prop="chunk_count" label="分块" width="80" />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="mtime" label="更新时间" min-width="180" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDoc(row)">详情</el-button>
            <el-button link type="danger" @click.stop="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <ListPager
        v-model:page="page"
        v-model:pageSize="pageSize"
        :total="total"
        :page-sizes="[5, 10, 20]"
        @change="onDocPager"
      />
    </el-card>

    <el-drawer v-model="detail.visible" :title="detail.name || '文档详情'" size="62%" destroy-on-close>
      <div v-if="detail.loading" class="muted">加载中…</div>
      <template v-else>
        <el-descriptions :column="3" border size="small" class="meta">
          <el-descriptions-item label="分块数">{{ detail.chunk_count }}</el-descriptions-item>
          <el-descriptions-item label="大小">{{ formatSize(detail.size) }}</el-descriptions-item>
          <el-descriptions-item label="更新">{{ detail.mtime }}</el-descriptions-item>
        </el-descriptions>
        <h4>原文</h4>
        <pre class="doc-text">{{ detail.text || '（空文档）' }}</pre>
        <h4>分块详情（{{ detail.chunks?.length || 0 }}）</h4>
        <el-table :data="pagedChunks" stripe max-height="360">
          <el-table-column prop="idx" label="#" width="64" />
          <el-table-column prop="char_len" label="字数" width="80" />
          <el-table-column prop="text" label="切片文本" min-width="360" show-overflow-tooltip />
          <el-table-column label="操作" width="88">
            <template #default="{ row }">
              <el-button link type="primary" @click="chunkView = row">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
        <ListPager
          v-model:page="chunkPage"
          v-model:pageSize="chunkPageSize"
          :total="detail.chunks?.length || 0"
          :page-sizes="[5, 10, 20]"
          @change="onChunkPager"
        />
      </template>
    </el-drawer>

    <el-dialog v-model="chunkVisible" title="分块全文" width="640px" destroy-on-close>
      <p class="muted">{{ chunkView?.source }} · 第 {{ chunkView?.idx }} 块 · {{ chunkView?.char_len }} 字</p>
      <pre class="doc-text">{{ chunkView?.text }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ragStatus, ragDocs, ragDocDetail, ragUpload, ragDelete, ragRebuild } from '@/api'
import ListPager from '@/components/ListPager.vue'
import { slicePage } from '@/utils/paging'

const status = ref({})
const docs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const keyword = ref('')
const chunkPage = ref(1)
const chunkPageSize = ref(10)
const detail = ref({ visible: false, loading: false, name: '', text: '', chunks: [], chunk_count: 0, size: 0, mtime: '' })
const chunkView = ref(null)
const chunkVisible = computed({
  get: () => !!chunkView.value,
  set: (v) => { if (!v) chunkView.value = null }
})
const pagedChunks = computed(() => slicePage(detail.value.chunks, chunkPage.value, chunkPageSize.value))

const formatSize = (n) => {
  const v = Number(n) || 0
  if (v < 1024) return `${v} B`
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`
  return `${(v / 1024 / 1024).toFixed(1)} MB`
}

const load = async (p) => {
  if (typeof p === 'number') page.value = p
  const [s, d] = await Promise.all([
    ragStatus(),
    ragDocs({ page: page.value, page_size: pageSize.value, keyword: keyword.value || undefined })
  ])
  status.value = s.data || {}
  const payload = d.data || {}
  docs.value = payload.items || (Array.isArray(payload) ? payload : [])
  total.value = payload.total ?? docs.value.length
  page.value = payload.page || page.value
  pageSize.value = payload.page_size || pageSize.value
}

const onDocPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  load()
}

const onChunkPager = ({ page: p, pageSize: s }) => {
  chunkPage.value = p
  chunkPageSize.value = s
}

const openDoc = async (row) => {
  if (!row?.name) return
  chunkPage.value = 1
  detail.value = { visible: true, loading: true, name: row.name, text: '', chunks: [], chunk_count: 0 }
  const res = await ragDocDetail(row.name)
  detail.value = { visible: true, loading: false, ...(res.data || {}) }
}

const upload = async ({ file }) => {
  const fd = new FormData()
  fd.append('file', file)
  await ragUpload(fd)
  ElMessage.success('已入库并重建索引')
  load(1)
}
const remove = async (row) => {
  await ragDelete(row.name)
  load(page.value)
}
const rebuild = async () => {
  await ragRebuild()
  ElMessage.success('已重建')
  load(1)
}
onMounted(() => load(1))
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}
.stat {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px 18px;
  box-shadow: var(--shadow);
  min-height: 108px;
}
.stat.on {
  border-color: rgba(29, 111, 216, 0.28);
  background:
    linear-gradient(180deg, rgba(29, 111, 216, 0.08) 0%, transparent 56%),
    var(--panel);
}
.stat span {
  display: block;
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 0.04em;
}
.stat strong {
  display: block;
  margin: 8px 0 6px;
  font-size: 24px;
  letter-spacing: -0.03em;
  color: var(--text);
}
.stat small {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.head-ops { display: flex; gap: 8px; align-items: center; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.muted { color: var(--muted); font-size: 13px; }
.meta { margin-bottom: 12px; }
h4 { margin: 16px 0 8px; font-size: 14px; }
.doc-text {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
  background: var(--panel-soft);
  padding: 12px;
  border-radius: 8px;
  max-height: 280px;
  overflow: auto;
}
@media (max-width: 1100px) {
  .stat-grid { grid-template-columns: 1fr 1fr; }
}
</style>
