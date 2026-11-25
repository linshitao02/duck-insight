export function unwrapList(res) {
  const d = res?.data
  if (Array.isArray(d)) return d
  if (d && Array.isArray(d.items)) return d.items
  return []
}

export function unwrapPage(res, fallbackSize = 10) {
  const d = res?.data
  if (Array.isArray(d)) {
    return { items: d, total: d.length, page: 1, pageSize: d.length || fallbackSize }
  }
  return {
    items: d?.items || [],
    total: Number(d?.total || 0),
    page: Number(d?.page || 1),
    pageSize: Number(d?.page_size || fallbackSize)
  }
}

export function slicePage(rows, page, pageSize) {
  const list = rows || []
  const start = (Math.max(1, page) - 1) * pageSize
  return list.slice(start, start + pageSize)
}
