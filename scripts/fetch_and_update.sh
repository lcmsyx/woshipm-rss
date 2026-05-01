#!/bin/bash
set -e

GH_TOKEN="${GH_TOKEN}"
REPO_OWNER="lcmsyx"
REPO_NAME="woshipm-rss"
BRANCH="main"
RSS_FILE="rss.xml"
DATA_DIR="data"

GH_API="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}"
NOW=$(date +"%Y-%m-%d %H:%M:%S")
TODAY=$(date +"%Y-%m-%d")
YESTERDAY=$(date -d "yesterday" +"%Y-%m-%d")
TODAY_SHORT=$(date +"%Y%m%d")

echo "[$NOW] 开始增量更新..."

get_file() {
    local path=$1
    local response=$(curl -s -H "Authorization: token ${GH_TOKEN}" \
        "${GH_API}/contents/${path}?ref=${BRANCH}")
    local sha=$(echo "$response" | jq -r '.sha' 2>/dev/null)
    local content=$(echo "$response" | jq -r '.content' 2>/dev/null)
    if [ "$content" != "null" ] && [ -n "$content" ]; then
        echo "$content" | base64 -d
    fi
    echo "___SHA___:${sha}"
}

save_file() {
    local path=$1
    local content=$2
    local message=$3
    local sha=$4
    local encoded=$(echo "$content" | base64 -w0)
    local payload="{\"message\":\"${message}\",\"content\":\"${encoded}\",\"branch\":\"${BRANCH}\"}"
    if [ -n "$sha" ] && [ "$sha" != "null" ]; then
        payload="{\"message\":\"${message}\",\"content\":\"${encoded}\",\"branch\":\"${BRANCH}\",\"sha\":\"${sha}\"}"
    fi
    curl -s -X PUT -H "Authorization: token ${GH_TOKEN}" \
        -H "Content-Type: application/json" -d "$payload" \
        "${GH_API}/contents/${path}" > /dev/null
    echo "已保存: $path"
}

format_rss_date() {
    date -d "$1" +"%a, %d %b %Y %H:%M:%S +0800" 2>/dev/null || echo "$1"
}

get_existing_guids() {
    echo "$1" | grep -oP '(?<=<guid[^>]*>)[^<]+' 2>/dev/null || echo ""
}

fetch_page() {
    curl -s -H "User-Agent: Mozilla/5.0" \
         -H "Accept: application/json" \
         "https://www.woshipm.com/tensorflow/digest/list?page=$1"
}

echo "获取现有RSS..."
rss_result=$(get_file "$RSS_FILE")
RSS_CONTENT=$(echo "$rss_result" | sed '/___SHA___:/d')
RSS_SHA=$(echo "$rss_result" | grep "___SHA___:" | tail -1 | sed 's/___SHA___://')

existing_guids=$(get_existing_guids "$RSS_CONTENT")
existing_count=$(echo "$existing_guids" | grep -c . 2>/dev/null || echo 0)
echo "当前RSS已有 ${existing_count} 条记录"

echo "抓取最近2天数据..."
target_dates="${TODAY}|${YESTERDAY}"
all_news=""
page=1
while [ $page -le 10 ]; do
    echo "  抓取第 ${page} 页..."
    response=$(fetch_page $page)
    items=$(echo "$response" | jq -r '.result[] | @json' 2>/dev/null)
    if [ -z "$items" ] || [ "$items" == "null" ]; then
        break
    fi
    has_target=0
    has_old=0
    while IFS= read -r item; do
        [ -z "$item" ] && continue
        create_time=$(echo "$item" | jq -r '.create_time // empty' 2>/dev/null)
        [ -z "$create_time" ] && continue
        date_str="${create_time:0:10}"
        if echo "$date_str" | grep -qE "^(${target_dates})$"; then
            has_target=1
            all_news="${all_news}${item}"$'\n'
        else
            has_old=1
        fi
    done <<< "$items"
    if [ $has_target -eq 1 ] && [ $has_old -eq 1 ]; then
        break
    fi
    if [ $has_target -eq 0 ] && [ $has_old -eq 1 ]; then
        break
    fi
    page=$((page + 1))
    sleep 0.5
done

new_count=$(echo -e "$all_news" | grep -c '{' 2>/dev/null || echo 0)
echo "最近2天获取到: ${new_count} 条"

if [ "$new_count" == "0" ]; then
    echo "最近2天无新数据，更新lastBuildDate..."
    if [ -n "$RSS_CONTENT" ]; then
        new_rss=$(echo "$RSS_CONTENT" | sed "s|<lastBuildDate>[^<]*</lastBuildDate>|<lastBuildDate>$(format_rss_date "$NOW")</lastBuildDate>|")
        save_file "$RSS_FILE" "$new_rss" "更新时间戳: $NOW" "$RSS_SHA"
        echo "已更新时间戳"
    fi
    exit 0
fi

truly_new=""
while IFS= read -r item; do
    [ -z "$item" ] && continue
    guid=$(echo "$item" | jq -r '.id // empty' 2>/dev/null)
    if ! echo "$existing_guids" | grep -qF "$guid"; then
        truly_new="${truly_new}${item}"$'\n'
    fi
done <<< "$all_news"

truly_new_count=$(echo -e "$truly_new" | grep -c '{' 2>/dev/null || echo 0)
echo "去重后新增: ${truly_new_count} 条"

if [ "$truly_new_count" == "0" ]; then
    echo "没有真正的新数据，更新lastBuildDate..."
    if [ -n "$RSS_CONTENT" ]; then
        new_rss=$(echo "$RSS_CONTENT" | sed "s|<lastBuildDate>[^<]*</lastBuildDate>|<lastBuildDate>$(format_rss_date "$NOW")</lastBuildDate>|")
        save_file "$RSS_FILE" "$new_rss" "更新时间戳: $NOW" "$RSS_SHA"
    fi
    exit 0
fi

new_items_xml=""
while IFS= read -r item; do
    [ -z "$item" ] && continue
    guid=$(echo "$item" | jq -r '.id // empty' 2>/dev/null)
    content=$(echo "$item" | jq -r '.content // empty' 2>/dev/null)
    create_time=$(echo "$item" | jq -r '.create_time // empty' 2>/dev/null)
    title=$(echo "$content" | cut -c1-60 | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
    [ ${#content} -gt 60 ] && title="${title}..."
    content_escaped=$(echo "$content" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
    pubdate=$(format_rss_date "$create_time")
    new_items_xml="${new_items_xml}    <item>
      <title><![CDATA[${title}]]></title>
      <link>https://www.woshipm.com/digest</link>
      <guid isPermaLink=\"false\">${guid}</guid>
      <description><![CDATA[${content_escaped}]]></description>
      <pubDate>${pubdate}</pubDate>
    </item>
"
done <<< "$truly_new"

if [ -n "$RSS_CONTENT" ]; then
    new_rss=$(echo "$RSS_CONTENT" | sed "s|<lastBuildDate>[^<]*</lastBuildDate>|<lastBuildDate>$(format_rss_date "$NOW")</lastBuildDate>|")
    new_rss=$(echo "$new_rss" | sed "s|</channel>|${new_items_xml}  </channel>|")
else
    new_rss="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<rss version=\"2.0\" xmlns:atom=\"http://www.w3.org/2005/Atom\">
  <channel>
    <title>人人都是产品经理快讯</title>
    <link>https://www.woshipm.com/digest</link>
    <description>人人都是产品经理每日快讯聚合，每2小时增量更新</description>
    <language>zh-cn</language>
    <lastBuildDate>$(format_rss_date "$NOW")</lastBuildDate>
    <atom:link href=\"https://lcmsyx.github.io/woshipm-rss/rss.xml\" rel=\"self\" type=\"application/rss+xml\"/>
${new_items_xml}  </channel>
</rss>"
fi

save_file "$RSS_FILE" "$new_rss" "增量更新RSS: +${truly_new_count}条" "$RSS_SHA"

data_result=$(get_file "${DATA_DIR}/woshipm_${TODAY_SHORT}.xml")
data_sha=$(echo "$data_result" | grep "___SHA___:" | sed "s/___SHA___://")
save_file "${DATA_DIR}/woshipm_${TODAY_SHORT}.xml" "$new_rss" "存档: ${TODAY_SHORT}" "$data_sha"

echo "完成！RSS现共有 $((existing_count + truly_new_count)) 条记录"
