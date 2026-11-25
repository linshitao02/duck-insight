<template>
  <div>
    <el-tabs v-model="tab">
      <el-tab-pane label="提示词模板" name="prompt">
        <div class="prompt-toolbar">
          <el-button type="primary" @click="openPrompt()">新建模板</el-button>
          <el-radio-group v-model="promptFilter" size="small" @change="onPromptFilter">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="question">用户短问题</el-radio-button>
            <el-radio-button label="system">系统提示词</el-radio-button>
          </el-radio-group>
        </div>
        <el-table :data="prompts">
          <el-table-column prop="name" label="名称" />
          <el-table-column label="分类" width="120">
            <template #default="{ row }">{{ kindText(row.prompt_kind) }}</template>
          </el-table-column>
          <el-table-column prop="scene" label="场景" width="140" />
          <el-table-column prop="content" label="内容" show-overflow-tooltip />
          <el-table-column label="默认" width="80">
            <template #default="{ row }"><el-tag v-if="row.is_default" type="success" size="small">默认</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link type="primary" @click="openPrompt(row)">编辑</el-button>
              <el-button link type="danger" @click="delPrompt(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <ListPager
          v-model:page="promptPage"
          v-model:pageSize="promptPageSize"
          :total="promptTotal"
          @change="onPromptPager"
        />
      </el-tab-pane>
      <el-tab-pane label="LLM 配置" name="llm">
        <el-button type="primary" style="margin-bottom: 12px" @click="openLLM()">新建配置</el-button>
        <el-table :data="llms">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="model_name" label="模型" />
          <el-table-column prop="base_url" label="Base URL" show-overflow-tooltip />
          <el-table-column label="本地" width="80">
            <template #default="{ row }">{{ row.is_local_llm ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button link type="primary" @click="openLLM(row)">编辑</el-button>
              <el-button link type="success" @click="test(row)">测试</el-button>
              <el-button link type="danger" @click="delLLM(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <ListPager
          v-model:page="llmPage"
          v-model:pageSize="llmPageSize"
          :total="llmTotal"
          @change="onLlmPager"
        />
        <el-drawer v-model="tester.visible" :title="'测试 · ' + tester.name" size="40%">
          <el-input v-model="tester.input" type="textarea" :rows="3" />
          <el-button type="primary" style="margin: 10px 0" :loading="tester.loading" @click="doTest">发送</el-button>
          <pre class="out">{{ tester.out }}</pre>
        </el-drawer>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="pDialog.visible" title="提示词" width="640px">
      <el-form label-width="100px" :model="pDialog.form">
        <el-form-item label="名称"><el-input v-model="pDialog.form.name" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="pDialog.form.prompt_kind" style="width: 100%">
            <el-option label="用户短问题" value="question" />
            <el-option label="系统提示词" value="system" />
          </el-select>
        </el-form-item>
        <el-form-item label="场景">
          <el-select v-model="pDialog.form.scene" style="width: 100%">
            <el-option label="洞察 insight" value="insight" />
            <el-option label="预测 predict" value="predict" />
            <el-option label="问答 qa" value="qa" />
            <el-option label="电价预测 price_forecast" value="price_forecast" />
            <el-option label="风险预警 predict_risk" value="predict_risk" />
            <el-option label="电力决策 power_decision" value="power_decision" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="pDialog.form.content" type="textarea" :rows="10" placeholder="可用 {metrics} {importance} {predictions} {context} {question}" />
        </el-form-item>
        <el-form-item label="仅问答"><el-switch v-model="pDialog.form.qa_only" :active-value="1" :inactive-value="0" /></el-form-item>
        <el-form-item label="默认"><el-switch v-model="pDialog.form.is_default" :active-value="1" :inactive-value="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pDialog.visible=false">取消</el-button>
        <el-button type="primary" @click="saveP">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="lDialog.visible" title="LLM 配置" width="640px">
      <el-form label-width="110px" :model="lDialog.form">
        <el-form-item label="名称"><el-input v-model="lDialog.form.name" /></el-form-item>
        <el-form-item label="模型名"><el-input v-model="lDialog.form.model" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="lDialog.form.api_key" show-password /></el-form-item>
        <el-form-item label="Base URL"><el-input v-model="lDialog.form.base_url" /></el-form-item>
        <el-form-item label="温度"><el-input-number v-model="lDialog.form.temperature" :step="0.1" :min="0" :max="2" /></el-form-item>
        <el-form-item label="最大 Token"><el-input-number v-model="lDialog.form.max_tokens" :step="100" /></el-form-item>
        <el-form-item label="本地 LLM"><el-switch v-model="lDialog.form.is_local_llm" :active-value="1" :inactive-value="0" /></el-form-item>
        <el-form-item label="默认"><el-switch v-model="lDialog.form.is_default" :active-value="1" :inactive-value="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="lDialog.visible=false">取消</el-button>
        <el-button type="primary" @click="saveL">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import Cookies from 'js-cookie'
import { ElMessage } from 'element-plus'
import { listPrompts, savePrompt, deletePrompt, listLLM, saveLLM, deleteLLM } from '@/api'
import ListPager from '@/components/ListPager.vue'
import { unwrapPage } from '@/utils/paging'

const tab = ref('prompt')
const prompts = ref([])
const promptFilter = ref('')
const promptPage = ref(1)
const promptPageSize = ref(10)
const promptTotal = ref(0)
const llms = ref([])
const llmPage = ref(1)
const llmPageSize = ref(10)
const llmTotal = ref(0)
const pDialog = reactive({ visible: false, form: {} })
const lDialog = reactive({ visible: false, form: {} })
const tester = reactive({ visible: false, name: '', id: null, input: '用一句话介绍你自己', out: '', loading: false })

const loadPrompts = async () => {
  const packed = unwrapPage(await listPrompts({
    prompt_kind: promptFilter.value || undefined,
    page: promptPage.value,
    page_size: promptPageSize.value
  }))
  prompts.value = packed.items
  promptTotal.value = packed.total
}

const loadLlms = async () => {
  const packed = unwrapPage(await listLLM({ page: llmPage.value, page_size: llmPageSize.value }))
  llms.value = packed.items
  llmTotal.value = packed.total
}

const load = async () => {
  await Promise.all([loadPrompts(), loadLlms()])
}

const onPromptFilter = () => {
  promptPage.value = 1
  loadPrompts()
}

const onPromptPager = ({ page: p, pageSize: s }) => {
  promptPage.value = p
  promptPageSize.value = s
  loadPrompts()
}

const onLlmPager = ({ page: p, pageSize: s }) => {
  llmPage.value = p
  llmPageSize.value = s
  loadLlms()
}
function kindText(k) {
  return k === 'question' ? '用户短问题' : '系统提示词'
}
const openPrompt = (row) => {
  pDialog.form = row ? { ...row } : { scene: 'predict_risk', prompt_kind: 'question', qa_only: 0, is_default: 0, content: '' }
  pDialog.visible = true
}
const openLLM = (row) => {
  lDialog.form = row ? { ...row, model: row.model_name || row.model } : { temperature: 0.5, max_tokens: 2000, is_local_llm: 0, is_default: 0 }
  lDialog.visible = true
}
const saveP = async () => { await savePrompt(pDialog.form, pDialog.form.id); pDialog.visible = false; load() }
const saveL = async () => {
  // 系统提示词不再在「LLM 配置」里维护：不提交该字段，避免覆盖库中已有值
  const { system_prompt, ...form } = lDialog.form
  await saveLLM(form, form.id)
  lDialog.visible = false
  load()
}
const delPrompt = async (row) => { await deletePrompt(row.id); load() }
const delLLM = async (row) => { await deleteLLM(row.id); load() }
const test = (row) => { tester.id = row.id; tester.name = row.name; tester.out = ''; tester.visible = true }
const doTest = async () => {
  tester.loading = true
  tester.out = ''
  try {
    const token = Cookies.get('token')
    const resp = await fetch(`/api/llm/${tester.id}/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
      body: JSON.stringify({ message: tester.input })
    })
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value)
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data:')) continue
        const body = line.slice(5).trim()
        if (!body) continue
        try {
          const data = JSON.parse(body)
          if (data.content) tester.out += data.content
          if (data.error) tester.out += '\n' + data.error
        } catch {}
      }
    }
  } finally {
    tester.loading = false
  }
}
onMounted(load)
</script>

<style scoped>
.out {
  white-space: pre-wrap;
  background: var(--panel-soft);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  min-height: 160px;
  color: var(--text);
}
.prompt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
</style>
