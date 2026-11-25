# -*- coding: utf-8 -*-
"""判定 bjx 拦截性质：是「请求头不完整」还是「真实反爬系统」。"""
import requests

URL = "https://news.bjx.com.cn/html/20260920/1513574.shtml"

FULL = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.bjx.com.cn/",
    "Connection": "keep-alive",
}

MINIMAL = {"User-Agent": "curl/8.4.0"}


def check(label, headers):
    try:
        r = requests.get(URL, timeout=25, headers=headers)
        waf = "aliyun_waf_aa" in r.text or "AliyunCaptcha" in r.text
        print(f"  {label:28s} -> {r.status_code} bytes={len(r.text):7d} WAF={waf}")
        return not waf
    except Exception as e:
        print(f"  {label:28s} -> ERR {type(e).__name__} {str(e)[:70]}")
        return False


print("=" * 72)
print("bjx 文章页拦截性质判定")
print("=" * 72)
check("完整浏览器请求头", FULL)
check("最小 UA(curl)", MINIMAL)
check("无任何头", {})
print()
print("结论：如果以上全部 WAF=True，说明是服务端真实反爬系统，")
print("      与请求头完整度无关，属刻意拦截程序化访问。")
