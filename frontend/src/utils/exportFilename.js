const safePart = (value, fallback, max = 36) => String(value || fallback)
  .replace(/[\\/:*?"<>|]+/g, '_')
  .replace(/\s+/g, '_')
  .replace(/^_+|_+$/g, '')
  .slice(0, max)

const datePart = (value) => {
  const raw = String(value || '')
  const matched = raw.match(/\d{4}[-/]?\d{2}[-/]?\d{2}/)
  if (matched) return matched[0].replace(/\D/g, '')
  const now = new Date()
  return `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
}

export function insightExportFilename(report, fmt = 'md') {
  const train = safePart(report?.train_name || report?.name || report?.title, '未命名任务')
  const model = safePart(report?.model_type, 'model', 24)
  const target = safePart(report?.target_col, 'target', 24)
  const date = datePart(report?.create_time)
  const id = report?.id || report?.insight_id || 'new'
  return `洞察报告_${train}_${model}_${target}_${date}_#${id}.${fmt}`
}
