<template>
  <div class="qa">
    <div class="page-head">
      <div>
        <h2>智能问答</h2>
        <p>
          多会话管理 · 流式输出 · 短期与会话摘要记忆 · 跨会话长期记忆。
          未命中知识库片段时直接由大模型作答。
        </p>
      </div>
      <div class="head-tags">
        <el-tag size="small" type="success" effect="plain">流式输出</el-tag>
        <el-tag size="small" type="info" effect="plain">短期记忆 · 最近 4 轮</el-tag>
        <el-tag size="small" type="warning" effect="plain">长期记忆 · 跨会话</el-tag>
      </div>
    </div>
    <el-card shadow="never" class="qa-card">
      <ChatWorkspace mode="page" />
    </el-card>
  </div>
</template>

<script setup>
import ChatWorkspace from '@/components/ChatWorkspace.vue'
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.page-head h2 { margin-bottom: 6px; }
.page-head p { font-size: 13px; line-height: 1.7; color: var(--muted); max-width: 720px; }
.head-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.qa-card {
  height: calc(100vh - 226px);
  min-height: 460px;
}

.qa-card :deep(.el-card__body) {
  padding: 0;
  height: 100%;
}
</style>
