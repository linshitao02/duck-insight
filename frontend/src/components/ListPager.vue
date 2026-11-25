<template>
  <div class="list-pager">
    <el-pagination
      background
      layout="total, prev, pager, next, sizes"
      :total="total"
      :page-size="pageSize"
      :current-page="page"
      :page-sizes="pageSizes"
      @current-change="onPage"
      @size-change="onSize"
    />
  </div>
</template>

<script setup>
const props = defineProps({
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  pageSizes: { type: Array, default: () => [10, 20, 50] }
})

const emit = defineEmits(['update:page', 'update:pageSize', 'change'])

const onPage = (p) => {
  emit('update:page', p)
  emit('change', { page: p, pageSize: props.pageSize })
}

const onSize = (s) => {
  emit('update:pageSize', s)
  emit('update:page', 1)
  emit('change', { page: 1, pageSize: s })
}
</script>

<style scoped>
.list-pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 0 2px;
}
</style>
