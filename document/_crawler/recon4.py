# -*- coding: utf-8 -*-
"""策略勘察：bjx 反爬绕过尝试 + weather 列表页/分页发现。"""
import re
from urllib.parse import urljoin

import requests
from lxml import html as LH

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

WAF_MARK = "aliyun_waf_aa"


def looks_waf(text):
    return WAF_MARK in text or "AliyunCaptcha" in text or "访问验证" in text


def body_len(text):
    doc = LH.fromstring(text)
    n = doc.xpath("//div[@id='cc-article']") or doc.xpath("//div[contains(@class,'cc-article')]")
    if n:
        return len(n[0].text_content()), "cc-article"
    best = (0, "")
    for xp in ["//div[contains(@class,'article')]", "//div[contains(@class,'content')]",
               "//div[contains(@class,'detail')]", "//article"]:
        for el in doc.xpath(xp):
            L = len(el.text_content())
            if L > best[0]:
                best = (L, xp)
    return best


print("=" * 72)
print("1) bjx 文章：带 Session(先访问首页拿 cookie) 再取文章")
print("=" * 72)
s = requests.Session()
s.headers.update(UA)
try:
    r0 = s.get("https://www.bjx.com.cn/", timeout=25)
    print("  首页:", r0.status_code, "| cookies:", list(s.cookies.keys()))
except Exception as e:
    print("  首页失败", e)

for url in [
    "https://news.bjx.com.cn/html/20260920/1513574.shtml",
    "https://guangfu.bjx.com.cn/news/20260920/1513494.shtml",
    "https://news.bjx.com.cn/html/20260920/1513575.shtml",
]:
    try:
        r = s.get(url, timeout=25, headers={"Referer": "https://www.bjx.com.cn/"})
        r.encoding = r.apparent_encoding or r.encoding
        L, xp = body_len(r.text)
        print(f"  {url}")
        print(f"     -> {r.status_code} bytes={len(r.text)} waf={looks_waf(r.text)} body={L} ({xp})")
    except Exception as e:
        print(f"  {url} -> ERR {type(e).__name__} {e}")

print()
print("=" * 72)
print("2) bjx 列表页（news.bjx.com.cn 首页 / 频道页）是否可取标题+摘要")
print("=" * 72)
for url in ["https://news.bjx.com.cn/", "https://shupeidian.bjx.com.cn/",
            "https://chuneng.bjx.com.cn/", "https://fengdian.bjx.com.cn/"]:
    try:
        r = s.get(url, timeout=25, headers={"Referer": "https://www.bjx.com.cn/"})
        r.encoding = r.apparent_encoding or r.encoding
        doc = LH.fromstring(r.text)
        links = set()
        for a in doc.xpath("//a[@href]"):
            u = urljoin(url, a.get("href") or "")
            if re.match(r"https?://[\w.]+\.bjx\.com\.cn/(html|news)/\d{8}/\d+\.shtml", u):
                links.add(u)
        print(f"  {url} -> {r.status_code} waf={looks_waf(r.text)} 文章链接={len(links)}")
    except Exception as e:
        print(f"  {url} -> ERR {e}")

print()
print("=" * 72)
print("3) weather 列表页发现：找 index / 分页 / 频道")
print("=" * 72)
for url in [
    "http://news.weather.com.cn/index.shtml",
    "http://news.weather.com.cn/",
    "http://www.weather.com.cn/news/index.shtml",
    "http://news.weather.com.cn/index_1.shtml",
    "http://news.weather.com.cn/index_2.shtml",
]:
    try:
        r = requests.get(url, timeout=25, headers=UA)
        r.encoding = r.apparent_encoding or r.encoding
        doc = LH.fromstring(r.text)
        arts = set()
        for a in doc.xpath("//a[@href]"):
            u = urljoin(url, a.get("href") or "")
            if re.match(r"http://news\.weather\.com\.cn/\d{4}/\d{2}/\d+\.shtml", u):
                arts.add(u)
        pag = set()
        for a in doc.xpath("//a[@href]"):
            h = a.get("href") or ""
            if re.search(r"index_\d+|page=|/\d+\.shtml$", h) and "weather.com.cn" in urljoin(url, h):
                pag.add(urljoin(url, h).split("#")[0])
        print(f"  {url} -> {r.status_code} final={r.url} 文章={len(arts)}")
        for p in sorted(pag)[:10]:
            print("        分页候选:", p)
    except Exception as e:
        print(f"  {url} -> ERR {type(e).__name__} {e}")

print()
print("=" * 72)
print("4) weather 正文抽取验证（articleBody）")
print("=" * 72)
r = requests.get("http://news.weather.com.cn/2026/09/4797297.shtml", timeout=25, headers=UA)
r.encoding = r.apparent_encoding or r.encoding
doc = LH.fromstring(r.text)
for xp in ["//div[contains(@class,'articleBody')]", "//div[contains(@class,'articleBox')]"]:
    n = doc.xpath(xp)
    if n:
        t = "\n".join(l.strip() for l in n[0].text_content().splitlines() if l.strip())
        print(f"  {xp} -> len={len(t)} 段落={len(n[0].xpath('.//p'))}")
        print("     ", t[:150].replace("\n", " / "))
