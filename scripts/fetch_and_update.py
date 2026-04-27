#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天自动获取最新的人人都是产品经理快讯，更新RSS文件
"""

import os
import json
import base64
import requests
import time
from datetime import datetime

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO_OWNER = "lcmsyx"
REPO_NAME = "woshipm-rss"
BRANCH = "main"

HEADERS = {
    "Authorization": f"token {GH_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>人人都是产品经理快讯</title>
    <link>https://www.woshipm.com/digest</link>
    <description>人人都是产品经理每日快讯聚合，每日自动更新</description>
    <language>zh-cn</language>
    <lastBuildDate>{last_build_date}</lastBuildDate>
    <atom:link href="https://lcmsyx.github.io/woshipm-rss/rss.xml" rel="self" type="application/rss+xml"/>
{items}
  </channel>
</rss>
"""

ITEM_TEMPLATE = """    <item>
      <title><![CDATA[{title}]]></title>
      <link>{link}</link>
      <guid isPermaLink="false">{guid}</guid>
      <description><![CDATA[{description}]]></description>
      <pubDate>{pubdate}</pubDate>
    </item>"""

def get_sha(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        return r.json()["sha"]
    return None

def fetch_page(page):
    url = f"https://www.woshipm.com/tensorflow/digest/list?page={page}"
    resp = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()

def fetch_latest_news():
    all_news = []
    page = 1
    today = datetime.now().strftime("%Y-%m-%d")
    
    while page <= 10:
        data = fetch_page(page)
        items = data.get("data", {}).get("list", []) if isinstance(data, dict) else data
        
        if not items:
            break
        
        for item in items:
            created = item.get("created_time", "")
            if created.startswith(today):
                all_news.append(item)
            else:
                return all_news
        
        page += 1
        time.sleep(0.5)
    
    return all_news

def format_pubdate(dt_str):
    try:
        dt = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M:%S")
        weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]
        month = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][dt.month-1]
        return f"{weekday}, {dt.day:02d} {month} {dt.year} {dt.strftime('%H:%M:%S')} +0800"
    except:
        return dt_str

def generate_rss(news_items):
    items_xml = []
    today_str = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
    
    for item in news_items:
        created = item.get("created_time", "")
        description = item.get("description", item.get("content", ""))
        title = description[:50] + "..." if len(description) > 50 else description
        
        items_xml.append(ITEM_TEMPLATE.format(
            title=title,
            link="https://www.woshipm.com/digest",
            guid=item.get("id", hash(description) % 100000000),
            description=description,
            pubdate=format_pubdate(created)
        ))
    
    return RSS_TEMPLATE.format(
        last_build_date=today_str,
        items="\n".join(items_xml)
    )

def update_file(path, content, message):
    sha = get_sha(path)
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha
    
    r = requests.put(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    print(f"Updated {path}")

def main():
    print("Fetching latest news...")
    news = fetch_latest_news()
    print(f"Got {len(news)} items")
    
    today = datetime.now().strftime("%Y%m%d")
    rss = generate_rss(news)
    
    update_file(f"data/woshipm_{today}.xml", rss, f"Update RSS: {today}")
    update_file("rss.xml", rss, f"Update latest RSS: {today}")
    
    print("Done!")

if __name__ == "__main__":
    main()
