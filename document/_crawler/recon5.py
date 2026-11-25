# -*- coding: utf-8 -*-
"""bjx 正文来源勘察：列表页摘要 / RSS / 移动端 / 其他端点。"""
import re
from urllib.parse import urljoin

import requests
from lxml import html as LH

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def looks_waf(t):
    return "aliyun_waf_aa" in t or "AliyunCaptcha" in t or "访问验证" in t


def probe(label, url):
    try:
        r = requests.get(url, timeout=25, headers=UA)
        r.encoding = r.apparent_encoding or r.encoding
        t = r.text
        print(f"  [{label}] {r.status_code} bytes={len(t)} waf={looks_waf(t)} ct={r.headers.get('Content-Type','')[:40]}")
        return r
    except Exception as e:
        print(f"  [{label}] ERR {type(e).__name__} {str(e)[:90]}")
        return None


print("=" * 72)
print("1) 列表页是否带摘要（以 chuneng 频道为例）")
print("=" * 72)
r = probe("chuneng", "https://chuneng.bjx.com.cn/")
if r:
    doc = LH.fromstring(r.text)
    # 找标题链接的父节点，看是否有摘要
    arts = []
    for a in doc.xpath("//a[@href]"):
        u = urljoin("https://chuneng.bjx.com.cn/", a.get("href") or "")
        if re.match(r"https?://[\w.]+\.bjx\.com\.cn/(html|news)/\d{8}/\d+\.shtml", u):
            title = a.text_content().strip()
            if len(title) > 8:
                arts.append((title, u, a))
    seen, uniq = set(), []
    for t_, u, a in arts:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((t_, u, a))
    print("  唯一文章链接:", len(uniq))
    for t_, u, a in uniq[:3]:
        parent = a.getparent()
        # 向上找 3 层，看能拿到多少文本
        for lvl in range(1, 4):
            if parent is None:
                break
            txt = " ".join(parent.text_content().split())
            if len(txt) > len(t_) + 30:
                print(f"    L{lvl} 摘要候选 (len={len(txt)}): {txt[:200]}")
                break
            parent = parent.getparent()

print()
print("=" * 72)
print("2) RSS / feed 端点")
print("=" * 72)
for u in [
    "https://news.bjx.com.cn/rss.shtml",
    "https://news.bjx.com.cn/rss/",
    "https://www.bjx.com.cn/rss.xml",
    "https://chuneng.bjx.com.cn/rss.xml",
    "https://ex.bjx.com.cn/news.aspx",
]:
    probe("rss", u)

print()
print("=" * 72)
print("3) 移动端")
print("=" * 72)
for u in ["https://m.bjx.com.cn/", "https://m.bjx.com.cn/news/20260920/1513574.shtml",
          "https://news.bjx.com.cn/m/20260920/1513574.shtml"]:
    probe("m", u)

print()
print("=" * 72)
print("4) 列表页里的“摘要型”块（cc-list 之类）")
print("=" * 72)
# 直接在首页 HTML 里找同时包含标题和较长描述的块
if r:
    doc = LH.fromstring(r.text)
    cnt = 0
    for el in doc.xpath("//li | //div[contains(@class,'list')] | //div[contains(@class,'item')]"):
        txt = " ".join(el.text_content().split())
        a = el.xpath(".//a[@href]")
        if not a:
            continue
        u = urljoin("https://chuneng.bjx.com.cn/", a[0].get("href") or "")
        if not re.match(r"https?://[\w.]+\.bjx\.com\.cn/(html|news)/\d{8}/\d+\.shtml", u):
            continue
        if 60 < len(txt) < 600:
            print(f"    len={len(txt)} :: {txt[:180]}")
            cnt += 1
            if cnt >= 5:
                break
    print("  命中摘要块数:", cnt)
