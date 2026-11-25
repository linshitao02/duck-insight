# -*- coding: utf-8 -*-


def parse_page(args, default_size=10, max_size=100):
    """Return (page, page_size) when paging is requested, otherwise None."""
    if args is None:
        return None
    if args.get("page") is None and args.get("page_size") is None:
        return None
    try:
        page = int(args.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    try:
        size = int(args.get("page_size") or default_size)
    except (TypeError, ValueError):
        size = default_size
    page = max(page, 1)
    size = min(max(size, 1), max_size)
    return page, size


def paginate(items, paging):
    if not paging:
        return items
    page, size = paging
    rows = list(items or [])
    total = len(rows)
    start = (page - 1) * size
    return {
        "items": rows[start:start + size],
        "total": total,
        "page": page,
        "page_size": size,
    }


def paginate_args(items, args, default_size=10, max_size=100):
    return paginate(items, parse_page(args, default_size, max_size))
