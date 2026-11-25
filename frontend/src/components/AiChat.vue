<template>
  <div class="ai-chat">
    <!-- 悬浮入口：点击向上弹出会话面板 -->
    <button v-show="!open" class="ai-fab" @click="open = true">
      <el-icon class="fab-icon"><ChatDotRound /></el-icon>
      <span>智能问答</span>
    </button>

    <transition name="pop-up">
      <section v-if="open" class="ai-shell">
        <ChatWorkspace mode="panel" @close="open = false" />
      </section>
    </transition>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ChatWorkspace from '@/components/ChatWorkspace.vue'

const open = ref(false)
</script>

<style scoped>
.ai-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 2000;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 46px;
  padding: 0 18px;
  border: 0;
  border-radius: 999px;
  cursor: pointer;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: linear-gradient(135deg, #3b82f6, #1d6fd8 60%, #0f766e);
  box-shadow: 0 14px 34px rgba(29, 111, 216, 0.42);
  transition: transform 0.18s, box-shadow 0.18s;
}
.ai-fab:hover { transform: translateY(-2px); box-shadow: 0 18px 42px rgba(56, 189, 248, 0.5); }
.fab-icon { font-size: 18px; }

.ai-shell {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 2001;
  width: 760px;
  height: min(660px, 78vh);
  display: flex;
  border-radius: 16px;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: 0 26px 70px rgba(26, 36, 51, 0.28);
  transform-origin: bottom right;
}

.pop-up-enter-active, .pop-up-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.pop-up-enter-from, .pop-up-leave-to { opacity: 0; transform: translateY(16px) scale(0.96); }

@media (max-width: 820px) {
  .ai-fab { right: 14px; bottom: 14px; }
  .ai-shell {
    right: 0;
    bottom: 0;
    width: 100vw;
    height: 92vh;
    border-radius: 16px 16px 0 0;
  }
}
</style>
