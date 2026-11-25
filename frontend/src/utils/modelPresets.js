const NAMED_PRESETS = ['fast', 'balanced', 'accurate']

export const PRESET_OPTIONS = [
  { value: 'fast', label: '快速试用' },
  { value: 'balanced', label: '均衡推荐' },
  { value: 'accurate', label: '高精度' },
  { value: 'custom', label: '自定义' }
]

function valuesEq(a, b) {
  if (a == null && b == null) return true
  const na = Number(a)
  const nb = Number(b)
  if (Number.isFinite(na) && Number.isFinite(nb)) return Math.abs(na - nb) < 1e-9
  return String(a) === String(b)
}

export function inferParamPreset(model, params) {
  const presets = model?.presets || {}
  const cur = params || {}
  for (const name of NAMED_PRESETS) {
    const preset = presets[name]
    if (!preset) continue
    const keys = Object.keys(preset)
    if (keys.length && keys.every(k => valuesEq(cur[k], preset[k]))) return name
  }
  return 'custom'
}

export function resolveParamPreset(model, params, saved) {
  if (saved === 'custom') return 'custom'
  if (NAMED_PRESETS.includes(saved)) {
    const inferred = inferParamPreset(model, params)
    if (inferred === saved || inferred === 'custom') return saved
  }
  return inferParamPreset(model, params)
}

export function allowedTasks(model) {
  const tasks = model?.tasks
  if (Array.isArray(tasks) && tasks.length) return tasks
  return ['regression', 'classification']
}

export function coerceTaskType(model, task) {
  const allowed = allowedTasks(model)
  if (allowed.includes(task)) return task
  return allowed[0]
}

export function fillParamDefaults(model, params) {
  const out = { ...(params || {}) }
  for (const p of model?.params || []) {
    if (p.default === undefined) continue
    const empty = out[p.key] === undefined || out[p.key] === '' || (p.type !== 'select' && out[p.key] === null)
    if (empty) out[p.key] = p.default
  }
  return out
}

export function presetParams(model, name) {
  if (!name || name === 'custom') return null
  const preset = model?.presets?.[name]
  if (!preset) return null
  return fillParamDefaults(model, { ...preset })
}
