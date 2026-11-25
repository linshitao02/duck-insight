# -*- coding: utf-8 -*-
"""
爬取中国天气网 气象/极端天气 文章 -> Markdown（供 RAG 导入）。

改进点：
  1. 多源列表（首页/新闻频道/预警/旅游/专题），优先「近期」文章
  2. 按 (年,月,文章ID) 倒序，保证新鲜度
  3. 标题相似度去重，避免同一事件刷屏（如某台风 14 篇）
  4. 礼貌抓取：随机间隔 + 退避重试

用法:
    python crawl_weather.py --limit 50
"""
import argparse
import csv
import json
import os
import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from lxml import html as LH

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.abspath(os.path.join(HERE, "..", "weather"))

# 近期内容为主的列表页（越靠前权重越高，仅影响同日期时的顺序）
LIST_PAGES = [
    "http://www.weather.com.cn/",
    "http://news.weather.com.cn/index.shtml",
    "http://news.weather.com.cn/",
    "http://www.weather.com.cn/news/",
    "http://www.weather.com.cn/alarm/alarm_list.shtml",
    "http://www.weather.com.cn/trip/index.shtml",
    "http://www.weather.com.cn/zt/index.shtml",
    "http://www.weather.com.cn/life/index.shtml",
    "http://www.weather.com.cn/weather1d/index.shtml",
] + [
    # 历史归档分页：仅作为数量补足（按日期倒序后自然排在末尾）
    f"http://news.weather.com.cn/index_{i}.shtml" for i in range(2, 10)
]

ARTICLE_RE = re.compile(r"^https?://news\.weather\.com\.cn/(\d{4})/(\d{2})/(\d+)\.shtml$")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "http://news.weather.com.cn/",
}

MIN_BODY = 260
DELAY = (1.0, 1.8)
TITLE_SIM = 0.62        # 相似度阈值，超过视为同一事件重复

session = requests.Session()
session.headers.update(HEADERS)


def polite_sleep():
    time.sleep(random.uniform(*DELAY))


def fetch(url, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, timeout=25)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or r.encoding
                return r.text
            if r.status_code in (403, 404):
                return ""
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return ""


def bigrams(text):
    t = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", text)
    return {t[i:i + 2] for i in range(max(len(t) - 1, 0))}


def similar(a, b):
    """标题二元组 Jaccard 相似度，用于剔除同一事件的高度重复报道。"""
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return False
    return len(ba & bb) / len(ba | bb) >= TITLE_SIM


def discover():
    """收集候选文章 URL，按新鲜度倒序返回。"""
    seen, cands = set(), []
    for page in LIST_PAGES:
        txt = fetch(page)
        if not txt:
            print(f"  [列表失败] {page}")
            continue
        try:
            doc = LH.fromstring(txt)
        except Exception:
            print(f"  [列表解析失败] {page}")
            continue
        got = 0
        for a in doc.xpath("//a[@href]"):
            u = urljoin(page, a.get("href") or "").split("#")[0]
            m = ARTICLE_RE.match(u)
            if m and u not in seen:
                seen.add(u)
                # 用 年月 + 文章ID 作为时间序（同日 ID 递增）
                cands.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), u))
                got += 1
        print(f"  [列表] {page} -> 新增 {got}，累计 {len(cands)}")
        polite_sleep()

    # 近期优先
    cands.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [c[3] for c in cands]


def clean_body(node):
    parts = []
    for el in node.xpath(".//p"):
        t = " ".join(el.text_content().split())
        if len(t) >= 8:
            parts.append(t)
    if not parts:
        parts = [l.strip() for l in node.text_content().splitlines() if len(l.strip()) >= 8]
    out = []
    for p in parts:
        if p in ("分享到", "字号", "大", "中", "小", "原创未经授权不得转载", "来源："):
            continue
        if not out or out[-1] != p:
            out.append(p)
    return "\n\n".join(out)


NOISE_TITLE = re.compile(r"(高清图集|组图|图片集|视频|直播)")


def parse_article(url, txt):
    doc = LH.fromstring(txt)

    def first(xp):
        v = doc.xpath(xp)
        return " ".join(v[0].split()) if v else ""

    title = first("//h1//text()") or first("//title//text()")
    title = re.sub(r"[-_—|]\s*(资讯|中国天气网|新闻|天气网).*$", "", title).strip()
    if not title or NOISE_TITLE.search(title):
        return None

    node = doc.xpath("//div[contains(@class,'articleBody')]") or \
        doc.xpath("//div[contains(@class,'articleBox')]")
    if not node:
        return None
    body = clean_body(node[0])
    if len(body) < MIN_BODY:
        return None

    m = re.search(r"(20\d{2}-\d{2}-\d{2} \d{2}:\d{2})", txt)
    date = m.group(1) if m else ""
    if not date:
        mm = ARTICLE_RE.match(url)
        if mm:
            date = f"{mm.group(1)}-{mm.group(2)}"

    sm = re.search(r"来源[：:]\s*([^\s<]{2,20})", txt)
    return {"title": title, "body": body, "date": date,
            "source": sm.group(1) if sm else "中国天气网", "url": url}


def safe_name(idx, date, title):
    t = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title).strip()
    t = re.sub(r"\s+", " ", t)[:58]
    return f"{idx:03d}_{(date or '')[:10]}_{t}.md"


def write_md(path, art):
    fm = {"title": art["title"], "date": art["date"], "source": art["source"],
          "url": art["url"], "category": "气象/极端天气",
          "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n")
        for k, v in fm.items():
            f.write(f"{k}: {json.dumps(v, ensure_ascii=False)}\n")
        f.write("---\n\n")
        f.write(f"# {art['title']}\n\n")
        f.write(f"> 来源：{art['source']}　发布时间：{art['date']}\n\n")
        f.write(art["body"])
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.endswith(".md"):
            os.remove(os.path.join(OUT_DIR, f))

    print(f"输出目录: {OUT_DIR}\n目标篇数: {args.limit}\n" + "-" * 64)
    print("[1/2] 收集候选 URL（按新鲜度排序）")
    urls = discover()
    print(f"  候选合计 {len(urls)} 条\n" + "-" * 64)

    print("[2/2] 抓取正文")
    kept_titles, manifest, ok, skip = [], [], 0, 0
    for u in urls:
        if ok >= args.limit:
            break
        txt = fetch(u)
        if not txt:
            skip += 1
            continue
        art = parse_article(u, txt)
        if not art:
            skip += 1
            polite_sleep()
            continue
        if any(similar(art["title"], k) for k in kept_titles):
            skip += 1
            print(f"  [去重] {art['title'][:36]}")
            polite_sleep()
            continue

        kept_titles.append(art["title"])
        ok += 1
        name = safe_name(ok, art["date"], art["title"])
        write_md(os.path.join(OUT_DIR, name), art)
        manifest.append({"file": name, "title": art["title"], "date": art["date"],
                         "source": art["source"], "chars": len(art["body"]), "url": u})
        print(f"  [{ok:02d}] {art['date']}  {len(art['body']):5d}字  {art['title'][:38]}")
        polite_sleep()

    mf = os.path.join(HERE, "manifest_weather.csv")
    with open(mf, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "title", "date", "source", "chars", "url"])
        w.writeheader()
        w.writerows(manifest)

    print("-" * 64)
    print(f"完成: 成功 {ok} 篇, 跳过 {skip} 篇（含去重）")
    print(f"清单: {mf}")


if __name__ == "__main__":
    main()
