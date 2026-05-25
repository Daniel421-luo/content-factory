"""日报自动生成脚本。按时间段判断生成 AI 日报或财经日报。"""
import os, sys, json, requests
from datetime import datetime, timezone, timedelta

tz = timezone(timedelta(hours=8))  # 北京时间
today = datetime.now(tz).strftime("%Y-%m-%d")
report_type = os.environ.get("REPORT_TYPE", "ai")
source_url = os.environ.get("SOURCE_URL", "")

# ── 1. 采集 ──────────────────────────────────────────
def fetch_source(url):
    """抓取网页内容，返回纯文本。先尝试 GET，失败则用 POST + JSON"""
    import re
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    for method in ["GET", "POST"]:
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=30)
            else:
                resp = requests.post(url, headers=headers, timeout=30)
            if resp.status_code == 405:
                continue  # 方法不允许，试下一个
            resp.raise_for_status()
            text = re.sub(r'<[^>]+>', '\n', resp.text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = re.sub(r'[ \t]{3,}', '  ', text)
            return text[:15000]
        except Exception as e:
            last_err = e
            continue
    print(f"采集失败: {last_err}", file=sys.stderr)
    return ""

raw = fetch_source(source_url)
if not raw:
    print("无内容可处理，退出")
    sys.exit(0)

# ── 2. DeepSeek 炼油 ─────────────────────────────────
SYSTEM_PROMPTS = {
    "ai": """你是 AI 科技日报主编。从原始内容中提炼当日 AI 行业最重要的动态。

输出格式（严格 JSON）：
{
  "title": "🤖 AI 日报 | {日期}",
  "source": "来源URL或名称",
  "sections": {
    "产品发布更新": [
      {"title": "条目标题", "summary": "1-2句话摘要", "url": "原文链接(如果有)", "source": "出处"}
    ],
    "行业动态": [
      {"title": "...", "summary": "...", "url": "...", "source": "..."}
    ],
    "论文研究": [
      {"title": "...", "summary": "...", "url": "...", "source": "..."}
    ],
    "技巧与观点": [
      {"title": "...", "summary": "...", "url": "...", "source": "..."}
    ]
  }
}

规则：
- 每个分区最多6条，宁缺毋滥
- 只收录有实质信息的条目，跳过纯营销/宣传内容
- summary 简洁尖锐，像跟朋友说"今天AI圈发生了什么"
- 没有的板块返回空数组""",

    "finance": """你是财经日报主编。从原始内容提炼当日最重要的财经动态。

输出格式（严格 JSON）：
{
  "title": "📊 财经日报 | {日期}",
  "source": "财联社/雪球等",
  "sections": {
    "宏观要闻": [
      {"title": "...", "summary": "1-2句话", "url": "", "source": ""}
    ],
    "A股市场": [
      {"title": "...", "summary": "...", "url": "", "source": ""}
    ],
    "行业板块": [
      {"title": "...", "summary": "...", "url": "", "source": ""}
    ],
    "全球市场": [
      {"title": "...", "summary": "...", "url": "", "source": ""}
    ]
  }
}

规则：
- 每个分区最多5条
- 数据要准确，不要编造数字
- 只收录当日最新动态"""
}

resp = requests.post(
    "https://api.deepseek.com/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
        "Content-Type": "application/json"
    },
    json={
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPTS.get(report_type, SYSTEM_PROMPTS["ai"])},
            {"role": "user", "content": f"以下是 {today} 的原始信息，请提炼为日报：\n\n{raw[:12000]}"}
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    },
    timeout=120
)
resp.raise_for_status()
result = resp.json()["choices"][0]["message"]["content"]
data = json.loads(result)

# ── 3. 生成 Markdown ─────────────────────────────────
def build_markdown(data, report_type, today, source_url):
    lines = [
        "---",
        f'source: "{source_url}"',
        f"date: \"{today}\"",
        f"tags: [{report_type}, 日报, 自动生成]",
        "type: daily-report",
        "---",
        "",
        f"# {data['title']}",
        "",
        f"> 来源：[{data.get('source', source_url)}]({source_url}) · 自动采集+DeepSeek提炼",
        f"> 生成时间：{datetime.now(tz).strftime('%Y-%m-%d %H:%M')} (北京时间)",
        ""
    ]

    sections = data.get("sections", {})
    for section_name, entries in sections.items():
        if not entries:
            continue
        lines.append(f"## {section_name}")
        lines.append("")
        for entry in entries:
            title = entry.get("title", "")
            url = entry.get("url", "")
            summary = entry.get("summary", "")
            src = entry.get("source", "")

            if url:
                lines.append(f"### [{title}]({url})")
            else:
                lines.append(f"### {title}")
            if src:
                lines.append(f"> 📍 {src}")
                lines.append("")
            lines.append(summary)
            lines.append("")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("🤖 本文由 [AI情报工厂](https://github.com/Daniel421-luo/content-factory) 自动生成。")
    return "\n".join(lines)

# ── 4. 保存 ──────────────────────────────────────────
filename_map = {"ai": "AI日报", "finance": "财经日报"}
prefix = filename_map.get(report_type, "日报")
out_dir = "日报"
os.makedirs(out_dir, exist_ok=True)

filepath = os.path.join(out_dir, f"{prefix}-{today}.md")
with open(filepath, "w", encoding="utf-8") as f:
    f.write(build_markdown(data, report_type, today, source_url))

# 同时保存为 JSON（方便后续解析）
jsonpath = os.path.join(out_dir, f"{prefix}-{today}.json")
with open(jsonpath, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ {prefix} 已生成: {filepath}")
