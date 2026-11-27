import { createRouter, createWebHistory } from 'vue-router'
import Cookies from 'js-cookie'

const routes = [
  { path: '/login', name: 'Login', component: () => import('@/views/Login.vue'), meta: { title: '登录' } },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '工作台', icon: 'DataBoard', group: '决策运营' } },
      { path: 'power', name: 'PowerCockpit', component: () => import('@/views/PowerCockpit.vue'), meta: { title: '电力决策舱', icon: 'Lightning', hidden: true } },
      { path: 'bi', name: 'BiBoard', component: () => import('@/views/BiBoard.vue'), meta: { title: 'BI 看板', icon: 'DataAnalysis', group: '决策运营' } },
      { path: 'bi/new', name: 'BiNew', component: () => import('@/views/BiStudio.vue'), meta: { title: '新建看板', icon: 'DataAnalysis', hidden: true, flush: true } },
      { path: 'bi/:id/view', name: 'BiView', component: () => import('@/views/BiView.vue'), meta: { title: '预览看板', icon: 'DataAnalysis', hidden: true, flush: true } },
      { path: 'bi/:id', name: 'BiEdit', component: () => import('@/views/BiStudio.vue'), meta: { title: '编辑看板', icon: 'DataAnalysis', hidden: true, flush: true } },
      { path: 'dag', name: 'Dag', component: () => import('@/views/Dag.vue'), meta: { title: 'DAG 编排', icon: 'Share', group: '决策运营' } },
      { path: 'dag/new', name: 'DagNew', component: () => import('@/views/DagStudio.vue'), meta: { title: '新建编排', icon: 'Share', hidden: true } },
      { path: 'dag/:id', name: 'DagEdit', component: () => import('@/views/DagStudio.vue'), meta: { title: '编辑编排', icon: 'Share', hidden: true } },
      { path: 'datasource', name: 'DataSource', component: () => import('@/views/DataSource.vue'), meta: { title: '数据源配置', icon: 'Connection', group: '数据资产' } },
      { path: 'dataset', name: 'Dataset', component: () => import('@/views/Dataset.vue'), meta: { title: '数据集配置', icon: 'FolderOpened', group: '数据资产' } },
      { path: 'dataset/workspace/:projectId', name: 'ProjectWorkspace', component: () => import('@/views/ProjectWorkspace.vue'), meta: { title: '任务工作区', icon: 'FolderOpened', hidden: true } },
      { path: 'dataset/workspace/:projectId/bundle/new', name: 'BundleConfigNew', component: () => import('@/views/BundleConfig.vue'), meta: { title: '新建逻辑数据集', icon: 'FolderOpened', hidden: true } },
      { path: 'dataset/workspace/:projectId/bundle/:bundleId', name: 'BundleConfig', component: () => import('@/views/BundleConfig.vue'), meta: { title: '配置关联字段', icon: 'FolderOpened', hidden: true } },
      { path: 'dataset/workspace/:projectId/table/new', name: 'DatasetTaskNew', component: () => import('@/views/DatasetTask.vue'), meta: { title: '新建数据表', icon: 'FolderOpened', hidden: true } },
      { path: 'dataset/workspace/:projectId/table/:id', name: 'DatasetTask', component: () => import('@/views/DatasetTask.vue'), meta: { title: '数据表配置', icon: 'FolderOpened', hidden: true } },
      // 兼容旧链接
      { path: 'dataset/new', redirect: '/dataset' },
      { path: 'dataset/:id(\\d+)', redirect: (to) => `/dataset` },
      { path: 'clean', name: 'Clean', component: () => import('@/views/CleanRule.vue'), meta: { title: '清洗规则', icon: 'SetUp', group: '数据资产' } },
      { path: 'clean/rule/new', name: 'CleanRuleNew', component: () => import('@/views/CleanRuleEditor.vue'), meta: { title: '新建清洗规则', icon: 'SetUp', hidden: true } },
      { path: 'clean/rule/:id', name: 'CleanRuleEdit', component: () => import('@/views/CleanRuleEditor.vue'), meta: { title: '编辑清洗规则', icon: 'SetUp', hidden: true } },
      { path: 'realtime/tasks', name: 'RealtimeTasks', component: () => import('@/views/RealtimeTasks.vue'), meta: { title: '同步任务', icon: 'Switch', group: '实时同步' } },
      { path: 'realtime/tasks/new', name: 'RealtimeTaskNew', component: () => import('@/views/RealtimeTaskEditor.vue'), meta: { title: '新建同步任务', icon: 'Switch', hidden: true } },
      { path: 'realtime/tasks/:id', name: 'RealtimeTaskEdit', component: () => import('@/views/RealtimeTaskEditor.vue'), meta: { title: '同步任务配置', icon: 'Switch', hidden: true } },
      { path: 'realtime/ops', name: 'RealtimeOps', component: () => import('@/views/RealtimeOps.vue'), meta: { title: '运维中心', icon: 'Monitor', group: '实时同步' } },
      { path: 'realtime/topics', name: 'KafkaTopics', component: () => import('@/views/KafkaTopics.vue'), meta: { title: 'Kafka 主题', icon: 'MessageBox', group: '实时同步' } },
      { path: 'realtime/doris', name: 'DorisSync', component: () => import('@/views/DorisSync.vue'), meta: { title: 'Doris 实时入库', icon: 'Coin', group: '实时同步' } },
      { path: 'train', name: 'Train', component: () => import('@/views/Train.vue'), meta: { title: '模型训练', icon: 'Cpu', group: '模型实验' } },
      { path: 'train/new', name: 'TrainNew', component: () => import('@/views/TrainEditor.vue'), meta: { title: '新建训练任务', icon: 'Cpu', hidden: true } },
      { path: 'train/:id', name: 'TrainEdit', component: () => import('@/views/TrainEditor.vue'), meta: { title: '训练任务', icon: 'Cpu', hidden: true } },
      { path: 'experiment', redirect: '/train' },
      { path: 'predict', name: 'Predict', component: () => import('@/views/Predict.vue'), meta: { title: '数据预测', icon: 'Promotion', group: '模型实验' } },
      { path: 'predict/records', name: 'PredictRecords', component: () => import('@/views/PredictRecords.vue'), meta: { title: '模型预测记录', icon: 'Tickets', group: '模型实验' } },
      { path: 'insight', name: 'Insight', component: () => import('@/views/Insight.vue'), meta: { title: '洞察报告', icon: 'Notebook', group: '智能体' } },
      { path: 'insight/:id', name: 'InsightDetail', component: () => import('@/views/InsightDetail.vue'), meta: { title: '报告详情', icon: 'Notebook', hidden: true } },
      { path: 'knowledge', name: 'Knowledge', component: () => import('@/views/Knowledge.vue'), meta: { title: '知识库 RAG', icon: 'Collection', group: '智能体' } },
      { path: 'qa', name: 'QA', component: () => import('@/views/QA.vue'), meta: { title: '智能问答', icon: 'ChatDotRound', group: '智能体' } },
      { path: 'llm', name: 'LLM', component: () => import('@/views/LLMConfig.vue'), meta: { title: 'LLM / 提示词', icon: 'Setting', group: '系统' } },
      { path: 'user', name: 'User', component: () => import('@/views/User.vue'), meta: { title: '用户管理', icon: 'User', roles: ['admin'], group: '系统' } },
    ]
  }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  const token = Cookies.get('token')
  if (to.path === '/login') {
    next(token ? '/' : undefined)
  } else if (!token) {
    next('/login')
  } else {
    next()
  }
})

export default router
