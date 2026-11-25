<template>
  <div>
    <div class="page-head">
      <div>
        <h2>用户管理</h2>
        <p>仅管理员可见。</p>
      </div>
    </div>
    <el-card shadow="never">
      <el-table :data="list">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="nickname" label="昵称" />
        <el-table-column prop="role" label="角色" width="100" />
        <el-table-column prop="status" label="状态" width="80" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <ListPager
        v-model:page="page"
        v-model:pageSize="pageSize"
        :total="total"
        @change="onPager"
      />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getUserList, deleteUser } from '@/api/user'
import ListPager from '@/components/ListPager.vue'
import { unwrapPage } from '@/utils/paging'

const list = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const load = async () => {
  const packed = unwrapPage(await getUserList({ page: page.value, page_size: pageSize.value }))
  list.value = packed.items
  total.value = packed.total
  if (!list.value.length && total.value > 0 && page.value > 1) {
    page.value -= 1
    return load()
  }
}
const onPager = ({ page: p, pageSize: s }) => {
  page.value = p
  pageSize.value = s
  load()
}
const remove = async (row) => {
  await ElMessageBox.confirm('删除该用户？')
  await deleteUser(row.id)
  load()
}
onMounted(load)
</script>
