export const FIELD_UNIT = {
  price_da: '元/MWh',
  price_rt: '元/MWh',
  load_mw: 'MW',
  wind_mw: 'MW',
  solar_mw: 'MW',
  renewable_mw: 'MW',
  residual_mw: 'MW',
  temp_c: '°C',
  humidity: '%',
  precip_mm: 'mm',
  wind_10m: 'm/s',
  wind_100m: 'm/s',
  wind_gust: 'm/s',
  radiation: 'W/m²',
  Sales: '元',
  Customers: '人',
  congestion: '0–1'
}

export function axisCaption(name) {
  const raw = String(name || '')
  const zh = defaultZh(raw) || raw || '数值'
  const unit = FIELD_UNIT[raw]
  return unit ? `${zh}（${unit}）` : zh
}

export const FIELD_ZH = {
  row_key: '行关联键',
  ts: '时间',
  site: '站点编码',
  site_name: '站点名称',
  lat: '纬度',
  lon: '经度',
  temp_c: '气温',
  humidity: '相对湿度',
  precip_mm: '降水量',
  wind_10m: '10米风速',
  wind_100m: '100米风速',
  wind_gust: '阵风',
  radiation: '短波辐射',
  weather_code: '天气代码',
  is_cold_wave: '寒潮标记',
  is_heat_wave: '热浪标记',
  is_typhoon: '台风标记',
  is_convection: '强对流标记',
  event_type: '极端事件类型',
  weather_source: '气象来源',
  load_mw: '用电负荷',
  wind_mw: '风电出力',
  solar_mw: '光伏出力',
  renewable_mw: '风光出力',
  residual_mw: '残余负荷',
  congestion: '阻塞指数',
  price_da: '日前电价',
  price_rt: '实时电价',
  year: '年',
  month: '月',
  day: '日',
  hour: '小时',
  minute: '分钟',
  second: '秒',
  weekday: '星期',
  order_date: '下单日期',
  order_id: '订单号',
  store: '门店',
  city: '城市',
  category: '品类',
  channel: '渠道',
  promo: '促销',
  member: '会员',
  visitors: '客流',
  unit_price: '客单价',
  discount_rate: '折扣率',
  sales_amount: '销售额',
  week: '周序号',
  quarter: '季度',
  Store: '门店',
  DayOfWeek: '星期',
  Date: '日期',
  Sales: '销售额',
  Customers: '客流量',
  Open: '是否营业',
  Promo: '促销',
  StateHoliday: '法定假日',
  SchoolHoliday: '学校假期',
  StoreType: '门店类型',
  Assortment: '商品组合',
  CompetitionDistance: '竞品距离',
  CompetitionOpenSinceMonth: '竞品开业月',
  CompetitionOpenSinceYear: '竞品开业年',
  Promo2: '持续促销',
  Promo2SinceWeek: '持续促销起始周',
  Promo2SinceYear: '持续促销起始年',
  PromoInterval: '促销间隔'
}

export function generatedColumnsFromSteps(steps = []) {
  const out = []
  for (const step of steps || []) {
    if (step?.op === 'parse_date') {
      const extracts = Array.isArray(step.extract)
        ? step.extract
        : ['year', 'month', 'day', 'weekday', 'hour', 'minute', 'second']
      for (const name of extracts) if (name && !out.includes(name)) out.push(name)
    }
    if (step?.op === 'split_flags') {
      const prefix = step.prefix || String(step.column || '').toLowerCase()
      for (const token of step.tokens || []) {
        const name = `${prefix}${String(token).toLowerCase()}`
        if (name && !out.includes(name)) out.push(name)
      }
    }
  }
  return out
}

export function defaultZh(name) {
  const raw = String(name || '')
  if (FIELD_ZH[raw]) return FIELD_ZH[raw]
  const base = raw.split('__')[0]
  return FIELD_ZH[base] || ''
}

export function headerLabel(name, zh) {
  const raw = String(name || '')
  const text = (zh || defaultZh(raw) || '').trim()
  return text ? `${raw}（${text}）` : raw
}

export function featureTick(name) {
  const raw = String(name || '').trim()
  if (!raw) return ''
  const zh = (defaultZh(raw) || defaultZh(raw.split('__')[0]) || '').trim()
  return zh ? `${raw}(${zh})` : raw
}

export const POWER_LABELS = ['load_mw', 'renewable_mw', 'wind_mw', 'solar_mw', 'price_da', 'price_rt']
export const POWER_ID_COLS = ['ts', 'row_key', 'site_name', 'weather_source', 'event_type', 'residual_mw', 'congestion']

export function featureColsForTarget(columns, target) {
  const skip = new Set([...POWER_LABELS, ...POWER_ID_COLS, target])
  if (target === 'price_da') {
    skip.delete('load_mw')
    skip.delete('wind_mw')
    skip.delete('solar_mw')
  }
  return (columns || []).filter(c => c && !skip.has(c))
}

export function parseJoinCol(col) {
  const raw = String(col || '')
  const m = raw.match(/^(.*)__d(\d+)$/)
  if (m) return { name: m[1], datasetId: Number(m[2]) }
  return { name: raw, datasetId: null }
}

function datasetCols(ds) {
  if (!ds) return []
  if (Array.isArray(ds.schema) && ds.schema.length) {
    return ds.schema.map(c => (typeof c === 'string' ? c : c?.name)).filter(Boolean)
  }
  return ((ds.profile && ds.profile.columns) || []).map(c => c.name).filter(Boolean)
}

function schemaZh(col, datasets = []) {
  const { name } = parseJoinCol(col)
  for (const ds of datasets || []) {
    const schema = ds?.schema || []
    for (const item of schema) {
      const n = typeof item === 'string' ? item : item?.name
      if (n === col || n === name) {
        const zh = String((item && item.label_zh) || '').trim()
        if (zh) return zh
      }
    }
    const cols = (ds?.profile && ds.profile.columns) || []
    for (const item of cols) {
      if (item?.name === col || item?.name === name) {
        const zh = String(item.label_zh || '').trim()
        if (zh) return zh
      }
    }
  }
  return ''
}

export function columnHeader(col, datasets = [], extra = {}) {
  const { name, datasetId } = parseJoinCol(col)
  const zh = (extra.zh || schemaZh(col, datasets) || defaultZh(name) || '').trim()
  const list = datasets || []
  let table = extra.table || ''
  const owners = list.filter(d => datasetCols(d).includes(name))
  if (!table && datasetId) {
    table = list.find(d => Number(d.id) === datasetId)?.name || ''
  }
  if (!table && extra.factId != null) {
    const fact = list.find(d => Number(d.id) === Number(extra.factId))
    if (fact && datasetCols(fact).includes(name)) table = fact.name
  }
  if (!table && owners.length === 1) table = owners[0].name || ''
  const needTable = !!datasetId || owners.length > 1
  const tableBit = needTable ? table : ''
  if (!zh) return name
  const uniq = [...new Set([zh, tableBit].filter(Boolean))]
  return `${name}（${uniq.join(' · ')}）`
}
