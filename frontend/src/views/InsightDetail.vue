<template>
  <div v-loading="booting">
    <div class="page-head">
      <div>
        <el-button link type="primary" @click="$router.push('/insight')">← 返回报告列表</el-button>
        <h2>{{ report.title || '洞察报告' }}</h2>
        <p>本地 LLM 根据训练指标、特征重要性与知识库生成，可改写入论文讨论节或作为企业附件。</p>
      </div>
      <div class="head-actions">
        <el-button v-if="report.train_job_id" @click="$router.push(`/train/${report.train_job_id}`)">查看训练任务</el-button>
        <el-button :loading="exporting === 'md'" @click="download('md')">导出 Markdown</el-button>
        <el-button type="primary" :loading="exporting === 'docx'" @click="download('docx')">导出 Word</el-button>
        <el-button type="danger" plain :loading="removing" @click="removeReport">删除</el-button>
      </div>
    </div>

    <div v-if="report.id" class="article-wrap">
      <aside class="meta-panel">
        <h4>报告信息</h4>
        <dl>
          <div><dt>关联训练</dt><dd>{{ report.train_name || (report.train_job_id ? `#${report.train_job_id}` : '—') }}</dd></div>
          <div><dt>目标列</dt><dd>{{ targetLabel }}</dd></div>
          <div><dt>算法</dt><dd>{{ report.model_type || '—' }}</dd></div>
          <div><dt>生成时间</dt><dd>{{ fmtTime(report.create_time) }}</dd></div>
          <div><dt>作者</dt><dd>{{ report.username || '—' }}</dd></div>
        </dl>
        <div v-if="metricItems.length" class="metrics">
          <h4>评估指标</h4>
          <div v-for="m in metricItems" :key="m.k" class="metric">
            <span>{{ m.k }}</span>
            <b>{{ m.v }}</b>
          </div>
        </div>
      </aside>
      <article class="paper">
        <header class="paper-head">
          <el-tag size="small" effect="plain">洞察报告</el-tag>
          <h1>{{ report.title }}</h1>
          <p class="byline">
            {{ targetLabel }}
            <template v-if="report.train_name"> · {{ report.train_name }}</template>
            <template v-if="report.create_time"> · {{ fmtTime(report.create_time) }}</template>
          </p>
        </header>
        <div class="report-prose" v-html="html"></div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getInsight, exportInsightById, deleteInsight } from '@/api'
import { insightExportFilename } from '@/utils/exportFilename'
import { axisCaption } from '@/utils/fieldLabels'

const route = useRoute()
const router = useRouter()
const booting = ref(true)
const exporting = ref('')
const removing = ref(false)
const report = ref({})

const targetLabel = computed(() => {
  const col = report.value.target_col
  if (!col) return '—'
  return axisCaption(col)
})
const html = computed(() => marked.parse(report.value.content || ''))
const metricItems = computed(() => {
  const m = report.value.metrics || {}
  return Object.entries(m)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => ({
      k,
      v: typeof v === 'number' ? (Math.abs(v) >= 10 ? v.toFixed(2) : v.toFixed(4)) : String(v)
    }))
})

const fmtTime = (t) => {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 19)
}

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const download = async (fmt) => {
  if (!report.value.id) return
  exporting.value = fmt
  try {
    const res = await exportInsightById(report.value.id, fmt)
    saveBlob(res.data, insightExportFilename(report.value, fmt))
    ElMessage.success(fmt === 'docx' ? '已导出 Word' : '已导出 Markdown')
  } finally {
    exporting.value = ''
  }
}

const removeReport = async () => {
  if (!report.value.id) return
  try {
    await ElMessageBox.confirm(`确定删除「${report.value.title || '未命名报告'}」？删除后不可恢复。`, '删除洞察报告', { type: 'warning' })
  } catch {
    return
  }
  removing.value = true
  try {
    await deleteInsight(report.value.id)
    ElMessage.success('已删除')
    router.push('/insight')
  } finally {
    removing.value = false
  }
}

const load = async () => {
  booting.value = true
  try {
    const res = await getInsight(route.params.id)
    if (!res.data) {
      ElMessage.error('洞察报告不存在')
      router.push('/insight')
      return
    }
    report.value = res.data
  } catch {
    router.push('/insight')
  } finally {
    booting.value = false
  }
}

watch(() => route.params.id, (id) => { if (id) load() })
onMounted(load)
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.article-wrap {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}
.meta-panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px;
  box-shadow: var(--shadow);
  position: sticky;
  top: 12px;
}
.meta-panel h4 {
  font-size: 12px;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 10px;
  text-transform: uppercase;
}
.meta-panel dl > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 12px;
}
.meta-panel dt { font-size: 11px; color: var(--muted); }
.meta-panel dd { font-size: 13px; color: var(--text); word-break: break-all; }
.metrics { margin-top: 8px; padding-top: 12px; border-top: 1px solid var(--line); }
.metric {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--line);
}
.metric span { color: var(--muted); }
.metric b { font-variant-numeric: tabular-nums; }
.paper {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 32px 40px 40px;
  box-shadow: var(--shadow);
  min-height: 480px;
}
.paper-head { margin-bottom: 24px; }
.paper-head h1 {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin: 10px 0 8px;
  line-height: 1.3;
}
.byline { color: var(--muted); font-size: 13px; }
.report-prose {
  white-space: normal;
  font-size: 15px;
  line-height: 1.85;
  color: var(--text);
}
.report-prose :deep(h1),
.report-prose :deep(h2),
.report-prose :deep(h3) {
  margin: 28px 0 10px;
  font-weight: 650;
  letter-spacing: -0.02em;
}
.report-prose :deep(h2) {
  font-size: 18px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.report-prose :deep(p) { margin: 0 0 14px; white-space: normal; }
.report-prose :deep(ul),
.report-prose :deep(ol) { padding-left: 22px; margin: 0 0 14px; }
.report-prose :deep(li) { margin: 6px 0; }
.report-prose :deep(code) {
  background: var(--panel-soft);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.report-prose :deep(blockquote) {
  margin: 0 0 14px;
  padding: 8px 14px;
  border-left: 3px solid var(--accent);
  background: var(--accent-soft);
  color: var(--text);
}
@media (max-width: 960px) {
  .article-wrap { grid-template-columns: 1fr; }
  .meta-panel { position: static; }
  .paper { padding: 22px; }
}
</style>
