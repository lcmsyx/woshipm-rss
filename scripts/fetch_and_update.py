#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量更新RSS：每次运行抓取最近3小时内新增的快讯，追加到RSS中
"""

import os
import re
import json
import base64
import requests
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO_OWNER = "lcmsyx"
REPO_NAME = "woshipm-rss"
BRANCH = "main"

HEADERS_REQ = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.woshipm.com/digest"
}
HEADERS_GH = {
    "Authorization": f"token {GH_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

STATE_FILE = "last_check.json"
RSS_FILE = "rss.xml"
DATA_DIR = "data"


def get_file_sha(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=HEADERS_GH)
    if r.status_code == 200:
        return r.json()["sha"]
    return None


def get_file_content(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=HEADERS_GH)
    if r.status_code == 200:
        import base64
        content = r.json()["content"]
        # 去除可能的换行符和末尾的=
        content = content.replace("\n", "")
        return base64.b64decode(content).decode("utf-8"), r.json()["sha"]
    return None, None


def save_file(path, content, message, sha=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=HEADERS_GH, json=payload)
    r.raise_for_status()
    print(f"Saved: {path}")


def fetch_page(page):
    url = f"https://www.woshipm.com/tensorflow/digest/list?page={page}"
    resp = requests.get(url, headers=HEADERS_REQ, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_recent_news(hours=3):
    """
    获取最近 N 小时内的新数据
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_date = cutoff.strftime("%Y-%m-%d")
    all_news = []
    page = 1
    seen_new = False  # 开始遇到新数据后，不再跨页

    while page <= 5:
        data = fetch_page(page)
        items = data.get("data", {}).get("list", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        if not items:
            break

        page_has_new = False
        page_has_old = False

        for item in items:
            created = item.get("created_time", "")
            if not created:
                continue

            created_dt = None
            try:
                created_dt = datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    created_dt = datetime.strptime(created[:10], "%Y-%m-%d")
                except ValueError:
                    continue

            if created_dt >= cutoff:
                if not any(n.get("id") == item.get("id") for n in all_news):
                    all_news.append(item)
                page_has_new = True
            else:
                page_has_old = True

        # 如果该页同时包含新旧数据，说明已经翻到了旧数据区域，停止
        if page_has_new and page_has_old:
            break
        # 如果整页都是旧数据，停止
        if not page_has_new and page_has_old and seen_new:
            break
        # 如果还没有遇到新数据，整页都是旧数据，停止（说明最近N小时没有新数据）
        if not page_has_new and not seen_new:
            break

        if page_has_new:
            seen_new = True

        page += 1
        time.sleep(0.5)

    return all_news


def get_existing_guids():
    """从当前RSS中提取已有的guid列表"""
    content, _ = get_file_content(RSS_FILE)
    if not content:
        return []
    guids = re.findall(r"<guid[^>]*>(.*?)</guid>", content, re.DOTALL)
    return [g.strip() for g in guids]


def format_pubdate(dt_str):
    try:
        dt = datetime.strptime(dt_str.strip()[:19], "%Y-%m-%d %H:%M:%S")
        weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]
        month = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][dt.month-1]
        return f"{weekday}, {dt.day:02d} {month} {dt.year} {dt.strftime('%H:%M:%S')} +0800"
    except:
        return dt_str


def make_rss_item(item):
    """生成单个RSS item XML"""
    created = item.get("created_time", "")
    description = item.get("description", item.get("content", ""))
    guid = str(item.get("id", "") or hash(description) % 100000000)
    title = description[:60].replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;") + ("..." if len(description) > 60 else "")
    
    desc_esc = (description
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;"))

    return f"""    <item>
      <title><![CDATA[{title}]]></title>
      <link>https://www.woshipm.com/digest</link>
      <guid isPermaLink="false">{guid}</guid>
      <description><![CDATA[{description}]]></description>
      <pubDate>{format_pubdate(created)}</pubDate>
    </item>"""


def build_rss_header():
    now_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>人人都是产品经理快讯</title>
    <link>https://www.woshipm.com/digest</link>
    <description>人人都是产品经理每日快讯聚合，每2小时增量更新</description>
    <language>zh-cn</language>
    <lastBuildDate>{now_str}</lastBuildDate>
    <atom:link href="https://lcmsyx.github.io/woshipm-rss/rss.xml" rel="self" type="application/rss+xml"/>
"""


def build_rss_footer():
    return """
  </channel>
</rss>
"""


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始增量更新...")

    # 1. 读取当前RSS中已有的guid
    existing_guids = get_existing_guids()
    print(f"当前RSS已有 {len(existing_guids)} 条记录")

    # 2. 抓取最近3小时的新数据
    new_items = fetch_recent_news(hours=3)
    print(f"最近3小时新增: {len(new_items)} 条")

    if not new_items:
        print("无新数据，退出")
        return

    # 3. 去重：只保留不在现有RSS中的
    new_unique = [item for item in new_items if str(item.get("id", "")) not in existing_guids]
    # 也按内容hash去重
    seen_content = set()
    truly_new = []
    for item in new_unique:
        desc = item.get("description", "")
        h = hash(desc) % 1000000000
        if h not in seen_content:
            seen_content.add(h)
            truly_new.append(item)

    print(f"去重后新增: {len(truly_new)} 条")
    if not truly_new:
        print("没有真正的新数据，退出")
        return

    # 4. 读取当前RSS内容
    current_content, sha = get_file_content(RSS_FILE)
    if current_content:
        # 找到 </channel> 的位置，在其前面插入新items
        channel_end = current_content.rfind("  </channel>")
        if channel_end == -1:
            channel_end = current_content.rfind("</channel>")
    else:
        current_content = None

    # 5. 构建新items XML
    new_items_xml = "\n".join(make_rss_item(item) for item in truly_new)

    # 6. 合并RSS
    if current_content and channel_end > 0:
        new_rss = current_content[:channel_end] + "\n" + new_items_xml + "\n" + current_content[channel_end:]
        # 更新时间戳
        now_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
        new_rss = re.sub(r"<lastBuildDate>.*?</lastBuildDate>", f"<lastBuildDate>{now_str}</lastBuildDate>", new_rss)
    else:
        new_rss = build_rss_header() + new_items_xml + build_rss_footer()

    # 7. 保存更新后的RSS
    save_file(RSS_FILE, new_rss, f"增量更新RSS: +{len(truly_new)}条")

    # 8. 同时存档今天的文件
    today = datetime.now().strftime("%Y%m%d")
    data_file = f"{DATA_DIR}/woshipm_{today}.xml"
    save_file(data_file, new_rss, f"存档: {today}")

    print(f"完成！RSS现共有 {len(existing_guids) + len(truly_new)} 条记录")


if __name__ == "__main__":
    main()
