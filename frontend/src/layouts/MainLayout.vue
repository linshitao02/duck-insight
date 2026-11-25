<template>
  <el-container class="shell">
    <el-aside v-if="!flush" width="240px" class="aside">
      <div class="brand">
        <img class="logo" src="/duck.png?v=insight" alt="Duck Insight" />
        <div>
          <strong>Duck Insight</strong>
          <em>数据分析工作台</em>
        </div>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="side-menu"
        background-color="transparent"
        text-color="#475569"
        active-text-color="#1d6fd8"
      >
        <template v-for="group in menuGroups" :key="group.name">
          <div class="menu-group">{{ group.name }}</div>
          <el-menu-item v-for="item in group.items" :key="item.path" :index="'/' + item.path">
            <el-icon><component :is="item.meta.icon" /></el-icon>
            <span>{{ item.meta.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container class="workspace">
      <el-header v-if="!flush" class="header">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
          <el-breadcrumb-item>{{ route.meta.title }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="right">
          <el-dropdown @command="onCmd">
            <span class="who">
              <span class="avatar">{{ (userStore.user.nickname || userStore.user.username || 'U').slice(0, 1) }}</span>
              {{ userStore.user.nickname || userStore.user.username }}
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main" :class="{ flush: route.meta.flush }">
        <router-view />
      </el-main>
    </el-container>
    <!-- 全局右下角智能问答悬浮入口 -->
    <AiChat v-if="!flush" />
  </el-container>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { getScenarios } from '@/api/user'
import AiChat from '@/components/AiChat.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const flush = computed(() => !!route.meta.flush)
const activeMenu = computed(() => {
  const p = route.path
  if (p.startsWith('/insight')) return '/insight'
  if (p.startsWith('/train')) return '/train'
  if (p.startsWith('/clean')) return '/clean'
  if (p.startsWith('/datasource')) return '/datasource'
  if (p.startsWith('/dataset')) return '/dataset'
  if (p.startsWith('/dag')) return '/dag'
  if (p.startsWith('/bi')) return '/bi'
  return p
})

const GROUP_ORDER = ['决策运营', '数据资产', '模型实验', '智能体', '系统']

const menus = computed(() => {
  const root = router.getRoutes().find(r => r.path === '/')
  return (root?.children || []).filter(r => {
    if (!r.meta?.title) return false
    if (r.meta.hidden) return false
    if (r.meta.roles && !r.meta.roles.includes(userStore.user.role)) return false
    return true
  })
})

const menuGroups = computed(() => {
  const buckets = {}
  for (const item of menus.value) {
    const name = item.meta?.group || '其他'
    if (!buckets[name]) buckets[name] = []
    buckets[name].push(item)
  }
  const ordered = GROUP_ORDER.filter(n => buckets[n]).map(n => ({ name: n, items: buckets[n] }))
  for (const name of Object.keys(buckets)) {
    if (!GROUP_ORDER.includes(name)) ordered.push({ name, items: buckets[name] })
  }
  return ordered
})

const onCmd = (cmd) => {
  if (cmd === 'logout') {
    userStore.logout()
    ElMessage.success('已退出')
    router.push('/login')
  }
}

onMounted(async () => {
  const res = await getScenarios()
  userStore.setScenarios(res.data || [])
})
</script>

<style scoped>
.shell { height: 100vh; background: var(--bg); }

.aside {
  background: var(--panel);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
}

.brand {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 20px 18px 16px;
  border-bottom: 1px solid var(--line);
}

.logo {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  object-fit: cover;
  flex: none;
}

.brand strong {
  display: block;
  font-size: 15px;
  color: var(--text);
  letter-spacing: -0.02em;
}

.brand em {
  font-style: normal;
  color: var(--muted);
  font-size: 12px;
}

.side-menu {
  flex: 1;
  padding: 10px 8px 18px;
  border-right: none !important;
  overflow: auto;
}

.menu-group {
  margin: 12px 10px 4px;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: #94a3b8;
  font-weight: 600;
}

.side-menu :deep(.el-menu-item) {
  border-radius: 8px;
  margin: 2px 0;
  height: 44px;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: var(--accent-soft) !important;
  font-weight: 600;
}

.side-menu :deep(.el-menu-item:hover) {
  background: var(--bg-2) !important;
}

.workspace { background: var(--bg); }

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 56px !important;
  padding: 0 22px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}

.right { display: flex; gap: 14px; align-items: center; }

.who {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent-soft);
  color: var(--accent);
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
}

.main {
  background:
    radial-gradient(900px 420px at 100% 0%, rgba(29, 111, 216, 0.07), transparent 55%),
    radial-gradient(700px 360px at 0% 100%, rgba(15, 118, 110, 0.05), transparent 50%),
    var(--bg);
  padding: 20px 22px 28px;
}

.main.flush {
  padding: 0;
  overflow: hidden;
  height: 100vh;
}
</style>
