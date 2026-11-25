# -*- coding: utf-8 -*-
"""站点结构勘察：找出列表页规律与正文抽取规则（一次性脚本，不参与正式爬取）。"""
import re
import sys
from urllib.parse import urljoin

import requests
from lxml import html as LH

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# 正文容器候选（按优先级）
BODY_XPATHS = [
    "//div[contains(@class,'con_text')]",
    "//div[@class='article']",
    "//div[@id='text']",
    "//div[contains(@class,'article-content')]",
    "//div[contains(@class,'TRS_Editor')]",
    "//div[contains(@class,'cc-article')]",
    "//div[contains(@class,'content')]",
    "//div[contains(@class,'detail')]",
    "//article",
]


def get(url):
    r = requests.get(url, timeout=25, headers=UA)
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def extract_body(doc):
    best = ("", "")
    for xp in BODY_XPATHS:
        nodes = doc.xpath(xp)
        if not nodes:
            continue
        txt = "\n".join(
            "\n".join(n.text_content().split()) for n in nodes
        )
        txt = "\n".join(line for line in txt.splitlines() if line.strip())
        if len(txt) > len(best[0]):
            best = (txt, xp)
    return best


def probe_weather():
    print("=" * 70)
    print("A. weather.com.cn")
    print("=" * 70)
    t = get("http://news.weather.com.cn/index.shtml")
    doc = LH.fromstring(t)

    print("\n[A1] 文章正文抽取（取一篇 news 文章）")
        # 直接锁定一篇
    for a in doc.xpath("//a[@href]"):
        u = urljoin("http://news.weather.com.cn/index.shtml", a.get("href") or "")
        if re.match(r"http://news\.weather\.com\.cn/\d{4}/\d{2}/\d+\.shtml", u):
            art = get(u)
            adoc = LH.fromstring(art)
            tt = "".join(adoc.xpath("//h1//text()") or adoc.xpath("//title//text()")).strip()
            body, xp = extract_body(adoc)
            print("  样例:", u)
            print("  标题:", tt[:70])
            print("  命中规则:", xp)
            print("  正文字数:", len(body))
            print("  正文开头:", body[:160].replace("\n", " / "))
            break

    print("\n[A2] 列表页/分页链接候选")
    cand = set()
    for a in doc.xpath("//a[@href]"):
        u = urljoin("http://news.weather.com.cn/index.shtml", a.get("href") or "")
        if any(k in u for k in ("index_", "page", "list", "/news/")) and "weather.com.cn" in u:
            cand.add(u.split("#")[0])
    for u in sorted(cand)[:30]:
        print("   ", u)

    print("\n[A3] index.shtml 里 news 文章链接数量")
    arts = set()
    for a in doc.xpath("//a[@href]"):
        u = urljoin("http://news.weather.com.cn/index.shtml", a.get("href") or "")
        if re.match(r"http://news\.weather\.com\.cn/\d{4}/\d{2}/\d+\.shtml", u):
            arts.add(u)
    print("   ", len(arts))


def probe_bjx():
    print()
    print("=" * 70)
    print("B. bjx.com.cn")
    print("=" * 70)
    t = get("https://www.bjx.com.cn/")
    doc = LH.fromstring(t)
    arts = []
    for a in doc.xpath("//a[@href]"):
        u = urljoin("https://www.bjx.com.cn/", a.get("href") or "")
        if re.match(r"https?://news\.bjx\.com\.cn/html/\d{8}/\d+\.shtml", u):
            arts.append((a.text_content().strip(), u))
    print("\n[B1] 首页文章链接数:", len(arts))
    for t_, u in arts[:8]:
        print("   ", t_[:40], "->", u)

    if arts:
        u = arts[0][1]
        adoc = LH.fromstring(get(u))
        tt = "".join(adoc.xpath("//h1//text()") or adoc.xpath("//title//text()")).strip()
        body, xp = extract_body(adoc)
        print("\n[B2] 正文抽取样例:", u)
        print("  标题:", tt[:70])
        print("  命中规则:", xp)
        print("  正文字数:", len(body))
        print("  正文开头:", body[:160].replace("\n", " / "))

    print("\n[B3] 频道/列表链接候选")
    cand = set()
    for a in doc.xpath("//a[@href]"):
        u = urljoin("https://www.bjx.com.cn/", a.get("href") or "")
        if re.search(r"bjx\.com\.cn/(list|news|topic|zhuanti)", u):
            cand.add(u.split("#")[0])
    for u in sorted(cand)[:30]:
        print("   ", u)


if __name__ == "__main__":
    try:
        probe_weather()
    except Exception as e:
        print("weather 勘察失败:", type(e).__name__, e)
    try:
        probe_bjx()
    except Exception as e:
        print("bjx 勘察失败:", type(e).__name__, e)
