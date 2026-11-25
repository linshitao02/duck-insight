# -*- coding: utf-8 -*-
"""深入勘察正文结构：把候选容器按文本量排序打印出来。"""
import re

import requests
from lxml import html as LH
from urllib.parse import urljoin

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def get(url):
    r = requests.get(url, timeout=25, headers=UA)
    r.encoding = r.apparent_encoding or r.encoding
    return r.text, r.status_code


def rank_containers(doc, limit=14):
    """按文本长度排出 div/article/section，帮助找正文容器。"""
    rows = []
    for el in doc.xpath("//div | //article | //section"):
        cls = " ".join(el.get("class") or "").split()
        eid = el.get("id") or ""
        txt = "\n".join(line for line in (l.strip() for l in el.text_content().splitlines()) if line)
        if len(txt) < 150:
            continue
        # 段落密度：段落越多越可能是正文
        ps = el.xpath(".//p")
        rows.append((len(txt), len(ps), el.tag, ".".join(cls)[:44], eid[:20]))
    rows.sort(reverse=True)
    for r in rows[:limit]:
        print(f"    len={r[0]:6d} p={r[1]:3d} <{r[2]}> class={r[3]!r} id={r[4]!r}")
    return rows


def show(url, label):
    print("=" * 72)
    print(label, url)
    print("=" * 72)
    txt, code = get(url)
    print("  HTTP", code, "bytes", len(txt))
    doc = LH.fromstring(txt)
    for xp in ["//h1//text()", "//title//text()"]:
        t = "".join(doc.xpath(xp)).strip()
        if t:
            print("  title[" + xp + "]:", t[:80])
    print("  --- 候选正文容器（按文本量） ---")
    rank_containers(doc)
    # 打印最长容器前 300 字
    print("  --- 是否含 __NEXT_DATA__ / 正文可用性 ---")
    for k in ["__NEXT_DATA__", "articleContent", "TRS_Editor", "con_text", "id=\"text\""]:
        print(f"    contains {k!r}:", k in txt)
    print()


if __name__ == "__main__":
    show("https://www.bjx.com.cn/", "B0 首页(对照)")
    show("https://news.bjx.com.cn/html/20260920/1513574.shtml", "B1 bjx 文章")
    show("http://news.weather.com.cn/2026/09/4797297.shtml", "W1 weather 文章")
