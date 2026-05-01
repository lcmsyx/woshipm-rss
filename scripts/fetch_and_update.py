#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import json
import base64
import requests
import time
from datetime import datetime, timedelta

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

RSS_FILE = "rss.xml"
DATA_DIR = "data"


def get_file_content(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=HEADERS_GH)
    if r.status_code == 200:
        content = r.json()["content"]
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


def fetch_today_news():
    today = datetime.now().strftime("%Y-%m-%d")
    all_news = []
    page = 1

    while page <= 10:
        data = fetch_page(page)
        items = data.get("result", []) if isinstance(data, dict) else []
        
        if not items:
            break

        page_has_today = False
        page_has_old = False

        for item in items:
            created = item.get("create_time", "")
            if not created:
                continue

            if created[:10] == today:
                if not any(n.get("id") == item.get("id") for n in all_news):
                    all_news.append(item)
                page_has_today = True
            else:
                page_has_old = True

        if page_has_today and page_has_old:
            break
        if not page_has_today and page_has_old:
            break

        page += 1
        time.sleep(0.5)

    return all_news


def get_existing_guids():
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
    created = item.get("create_time", item.get("created_time", ""))
    description = item.get("content", item.get("description", ""))
    guid = str(item.get("id", "") or hash(description) % 100000000)
    title = description[:60].replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;") + ("..." if len(description) > 60 else "")
    
    return f'''    <item>
      <title><![CDATA[{title}]]></title>
      <link>https://www.woshipm.com/digest</link>
      <guid isPermaLink="false">{guid}</guid>
      <description><![CDATA[{description}]]></description>
      <pubDate>{format_pubdate(created)}</pubDate>
    </item>'''


def build_rss_header():
    now_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>人人都是产品经理快讯</title>
    <link>https://www.woshipm.com/digest</link>
    <description>人人都是产品经理每日快讯聚合，每2小时增量更新</description>
    <language>zh-cn</language>
    <lastBuildDate>{now_str}</lastBuildDate>
    <atom:link href="https://lcmsyx.github.io/woshipm-rss/rss.xml" rel="self" type="application/rss+xml"/>
'''


def build_rss_footer():
    return '''
  </channel>
</rss>
'''


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始增量更新...")

    existing_guids = get_existing_guids()
    print(f"当前RSS已有 {len(existing_guids)} 条记录")

    new_items = fetch_today_news()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"当天({today})获取到: {len(new_items)} 条")

    if not new_items:
        print("当天无新数据，检查是否需要更新lastBuildDate...")
        current_content, sha = get_file_content(RSS_FILE)
        if current_content:
            now_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
            new_rss = re.sub(r"<lastBuildDate>.*?</lastBuildDate>", f"<lastBuildDate>{now_str}</lastBuildDate>", current_content)
            save_file(RSS_FILE, new_rss, f"更新时间戳: {now_str}")
            print("已更新时间戳")
        return

    new_unique = [item for item in new_items if str(item.get("id", "")) not in existing_guids]
    
    seen_content = set()
    truly_new = []
    for item in new_unique:
        desc = item.get("content", item.get("description", ""))
        h = hash(desc) % 1000000000
        if h not in seen_content:
            seen_content.add(h)
            truly_new.append(item)

    print(f"去重后新增: {len(truly_new)} 条")

    if not truly_new:
        print("没有真正的新数据，更新lastBuildDate...")
        current_content, sha = get_file_content(RSS_FILE)
        if current_content:
            now_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
            new_rss = re.sub(r"<lastBuildDate>.*?</lastBuildDate>", f"<lastBuildDate>{now_str}</lastBuildDate>", current_content)
            save_file(RSS_FILE, new_rss, f"更新时间戳: {now_str}")
        return

    current_content, sha = get_file_content(RSS_FILE)
    if current_content:
        channel_end = current_content.rfind("  </channel>")
        if channel_end == -1:
            channel_end = current_content.rfind("</channel>")
    else:
        current_content = None

    new_items_xml = "
".join(make_rss_item(item) for item in truly_new)

    if current_content and channel_end > 0:
        new_rss = current_content[:channel_end] + "
" + new_items_xml + "
" + current_content[channel_end:]
        now_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
        new_rss = re.sub(r"<lastBuildDate>.*?</lastBuildDate>", f"<lastBuildDate>{now_str}</lastBuildDate>", new_rss)
    else:
        new_rss = build_rss_header() + new_items_xml + build_rss_footer()

    save_file(RSS_FILE, new_rss, f"增量更新RSS: +{len(truly_new)}条")

    today_str = datetime.now().strftime("%Y%m%d")
    data_file = f"{DATA_DIR}/woshipm_{today_str}.xml"
    save_file(data_file, new_rss, f"存档: {today_str}")

    print(f"完成！RSS现共有 {len(existing_guids) + len(truly_new)} 条记录")


if __name__ == "__main__":
    main()
