/** 前端轻量重推断：配合任务页「重新自动推断」 */
const ID_HINT = /(^id$|_id$|id$|code$|key$|编号|编码|store$)/i
const DATE_HINT = /(date|time|day|日期|时间)/i
const TARGET_HINT = /(sales|amount|target|label|^y$|销量|销售额|目标)/i
const LEAKAGE = new Set(['customers', 'customer'])

export function inferClientSide(col) {
  const name = String(col.name || '')
  const sample = (col.sample || []).filter(v => v !== null && v !== undefined && v !== '')
  let inferred = col.inferred || 'unknown'

  if (DATE_HINT.test(name)) inferred = 'datetime'
  else if (ID_HINT.test(name)) inferred = 'id'
  else if (sample.length) {
    const nums = sample.filter(v => !Number.isNaN(Number(v))).length
    if (nums / sample.length > 0.8) inferred = 'numeric'
    else if (sample.every(v => String(v).length < 24)) inferred = 'categorical'
    else inferred = 'text'
  }

  let role = 'feature'
  if (TARGET_HINT.test(name)) role = 'target'
  else if (LEAKAGE.has(name.toLowerCase())) role = 'leakage'
  else if (inferred === 'id' || ID_HINT.test(name)) role = 'key'
  else if (inferred === 'datetime') role = 'time'

  return { inferred, role }
}
