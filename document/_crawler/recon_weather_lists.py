# -*- coding: utf-8 -*-
"""寻找 weather.com.cn 更多「近期」列表页，用于提升文章新鲜度与多样性。"""
import re
from urllib.parse import urljoin

import requests
from lxml import html as LH

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
      "Accept-Language": "zh-CN,zh;q=0.9"}

ART_RE = re.compile(r"^https?://(news|www)\.weather\.com\.cn/(\d{4})/(\d{2})/(\d+)\.shtml$")

seeds = [
    "http://www.weather.com.cn/",
    "http://news.weather.com.cn/index.shtml",
    "http://www.weather.com.cn/news/",
    "http://www.weather.com.cn/alarm/",
    "http://www.weather.com.cn/weather/",
]

seen_pages = set()
cand_pages = set()
article_months = {}

for s in seeds:
    try:
        r = requests.get(s, timeout=25, headers=UA)
        r.encoding = r.apparent_encoding or r.encoding
    except Exception as e:
        print("ERR", s, e)
        continue
    doc = LH.fromstring(r.text)
    n_art = 0
    for a in doc.xpath("//a[@href]"):
        u = urljoin(s, a.get("href") or "").split("#")[0]
        m = ART_RE.match(u)
        if m:
            n_art += 1
            ym = f"{m.group(2)}-{m.group(3)}"
            article_months[ym] = article_months.get(ym, 0) + 1
        # 收集可能是列表页的链接
        if re.search(r"weather\.com\.cn", u) and re.search(
                r"(index|list|news|zhuanti|topic|/gn/|/gj/|/sh/|more)", u):
            if not ART_RE.match(u) and not re.search(r"\.(jpg|png|css|js)$", u):
                cand_pages.add(u)
    print(f"[seed] {s} -> 文章 {n_art}")

print()
print("页面上出现的文章月份分布:")
for k in sorted(article_months):
    print("   ", k, article_months[k])

print()
print("候选列表页（前 40）:")
for u in sorted(cand_pages)[:40]:
    print("   ", u)
