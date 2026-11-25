<template>
  <div class="viewer">
    <header class="bar">
      <div>
        <strong>{{ board.name || 'BI 看板' }}</strong>
        <span>Plotly Dash 交互预览 · 可筛选站点与时间粒度</span>
      </div>
      <div class="ops">
        <el-button @click="$router.push('/bi')">返回列表</el-button>
        <el-button type="primary" @click="$router.push(`/bi/${route.params.id}`)">进入设计器</el-button>
      </div>
    </header>
    <iframe v-if="src" class="frame" :src="src" title="Plotly Dash 看板" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { getBoard } from '@/api'

const route = useRoute()
const userStore = useUserStore()
const board = ref({})

const src = computed(() => {
  const id = route.params.id
  const token = userStore.token
  if (!id || !token) return ''
  return `/bi-dash/?board=${id}&token=${encodeURIComponent(token)}`
})

onMounted(async () => {
  try {
    const res = await getBoard(route.params.id)
    board.value = res.data || {}
  } catch {
    board.value = {}
  }
})
</script>

<style scoped>
.viewer { height: 100vh; display: flex; flex-direction: column; background: #e8eef5; }
.bar {
  height: 52px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid var(--line);
}
.bar strong { font-size: 15px; margin-right: 10px; }
.bar span { color: var(--muted); font-size: 12px; }
.ops { display: flex; gap: 8px; }
.frame { flex: 1; width: 100%; border: 0; background: #e8eef5; }
</style>
