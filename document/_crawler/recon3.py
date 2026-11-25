# -*- coding: utf-8 -*-
"""查看 bjx 文章页原始 HTML，判断正文是服务端渲染还是 JS 异步加载。"""
import re

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.bjx.com.cn/",
}

URL = "https://news.bjx.com.cn/html/20260920/1513574.shtml"

r = requests.get(URL, timeout=25, headers=UA)
r.encoding = r.apparent_encoding or r.encoding
html = r.text
print("HTTP", r.status_code, "| bytes", len(html), "| encoding", r.encoding)
print()

# 1) 关键标识
for k in ["cc-article", "article", "content", "正文", "ajax", "shtml", "iframe", "<script"]:
    print(f"  count {k!r}:", html.count(k))
print()

# 2) 找出所有 script src 与内联 script 里的 URL
print("--- script src ---")
for m in re.findall(r'<script[^>]+src=["\']([^"\']+)', html)[:20]:
    print("   ", m)
print()

print("--- 内联 script 中出现的 .shtml / api / json 线索 ---")
for m in set(re.findall(r'["\']([^"\']*?(?:\.shtml|/api/|\.json|ajax)[^"\']*)["\']', html)):
    if len(m) < 160:
        print("   ", m)
print()

# 3) 打印 body 结构骨架（标签+class）
print("--- HTML 骨架（前 60 个带 class 的标签） ---")
for m in re.findall(r'<(\w+)([^>]*)>', html):
    tag, attrs = m
    cls = re.search(r'class=["\']([^"\']+)', attrs)
    if cls and tag in ("div", "section", "article", "main", "p"):
        print(f"   <{tag} class={cls.group(1)[:60]!r}>")
print()

# 4) 保存原文以便人工查看
with open("_bjx_article_raw.html", "w", encoding="utf-8") as f:
    f.write(html)
print("原始 HTML 已保存到 _bjx_article_raw.html")
