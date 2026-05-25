"""抖音链接处理：采集 → 提炼 → 分类 → 存储 → 更新索引。"""
import os, sys, json, re, requests
from datetime import datetime, timezone, timedelta

tz = timezone(timedelta(hours=8))
today = datetime.now(tz).strftime("%Y-%m-%d")

# ── 1. 获取链接 ──────────────────────────────────────
douyin_url = os.environ.get("DOUYIN_URL", "")
issue_body = os.environ.get("ISSUE_BODY", "")

# 支持两种输入：workflow_dispatch 传 URL 或 GitHub Issue 包含链接
if not douyin_url and issue_body:
    urls = re.findall(r'https?://[^\s]+', issue_body)
    douyin_url = urls[0] if urls else ""

if not douyin_url:
    # 检查 raw-links/pending.md 中是否有待处理链接
    pending_file = "抖音素材库/raw-links/pending.md"
    if os.path.exists(pending_file):
        with open(pending_file, "r") as f:
            content = f.read()
        urls = re.findall(r'https?://[^\s]+', content)
        if urls:
            douyin_url = urls[0]
            # 标记为已处理
            content = re.sub(r'https?://[^\s]+', '~~\\g<0>~~ (已处理)', content, count=1)
            with open(pending_file, "w") as f:
                f.write(content)

if not douyin_url:
    print("没有待处理的抖音链接")
    sys.exit(0)

print(f"🔗 处理链接: {douyin_url}")

# ── 2. 提取页面信息 ──────────────────────────────────
# 抖音链接通常需要特殊处理，但我们可以尝试获取页面元数据
# 对于抖音视频，主要依赖 DeepSeek 对 URL 的理解来生成描述
# 如果能获取到页面标题/描述更好
page_info = ""
try:
    resp = requests.get(douyin_url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
    }, timeout=15, allow_redirects=True)
    # 尝试提取 meta 标签
    import re as regex
    titles = regex.findall(r'<title>(.*?)</title>', resp.text[:50000])
    if titles:
        page_info = f"页面标题: {titles[0]}\n"
    descs = regex.findall(r'<meta[^>]*description[^>]*content="([^"]*)"', resp.text[:50000], regex.IGNORECASE)
    if descs:
        page_info += f"页面描述: {descs[0]}\n"
except Exception as e:
    print(f"页面抓取备注: {e}")

# ── 3. DeepSeek 提炼 ─────────────────────────────────
SYSTEM_PROMPT = """你是信息提炼专家。从抖音视频/文章的标题和描述中提炼核心内容。

即使只有 URL 和少量元数据，也请基于你对相关主题的了解和 URL 中可能包含的标题信息，尽力生成结构化提炼。

输出严格 JSON：

{
  "title": "提炼标题（简洁有力，20字内）",
  "author": "作者名（未知填'待查'）",
  "one_liner": "一句话观点（这篇文章最核心的论断是什么）",
  "category": "商业|投资|技术|资讯|个人成长",
  "tags": ["标签1", "标签2", "标签3"],
  "key_points": ["要点1", "要点2", "要点3", "要点4", "要点5"],
  "related_projects": ["关联项目1", "关联项目2"],
  "key_quote": "如果有印象深刻的金句，摘录一句"
}

规则：
- one_liner 要尖锐，像跟朋友说"你知道这个视频在说什么吗？它说..."
- key_points 每条15-40字，不要空洞
- category 从5个选项中选最匹配的
- tags 至少3个，包含具体主题词
- 如果你不确定内容，标记 category 为 "资讯" 并写明不确定的部分"""

resp = requests.post(
    "https://api.deepseek.com/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
        "Content-Type": "application/json"
    },
    json={
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"""请提炼以下抖音视频的内容：

URL: {douyin_url}
{page_info}

请基于 URL 和元数据尽力提炼。如果信息不足，基于你对相关领域的了解做合理推断，并在 key_points 中注明哪些是推断的。"""}
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"}
    },
    timeout=120
)
resp.raise_for_status()
result = resp.json()["choices"][0]["message"]["content"]
data = json.loads(result)

# ── 4. 分类归档 ──────────────────────────────────────
category_map = {
    "商业": "商业",
    "投资": "投资",
    "技术": "技术",
    "资讯": "资讯",
    "个人成长": "个人成长"
}
cat = data.get("category", "资讯")
cat_dir = category_map.get(cat, "资讯")
base_dir = f"抖音素材库/已提炼/{cat_dir}"
os.makedirs(base_dir, exist_ok=True)

# 生成文件名
safe_title = re.sub(r'[\\/:*?"<>|]', '-', data.get("title", "untitled"))
safe_title = safe_title[:30]
filename = f"{safe_title}.md"
filepath = os.path.join(base_dir, filename)

# ── 5. 生成 Markdown ─────────────────────────────────
tags = data.get("tags", [])
tags_str = ", ".join(tags)

lines = [
    "---",
    f'source: "{douyin_url}"',
    f'author: "{data.get("author", "待查")}"',
    f"date: \"{today}\"",
    f"tags: [抖音提炼, {cat}, {tags_str}]",
    "status: 已提炼",
    "---",
    "",
    f"# {data.get('title', 'untitled')}",
    "",
    f"**一句话观点：** {data.get('one_liner', '')}",
    "",
    f"**标签：** #{' #'.join(tags)}",
    ""
]

for i, point in enumerate(data.get("key_points", []), 1):
    lines.append(f"{i}. {point}")

lines.append("")

if data.get("key_quote"):
    lines.append(f"> {data.get('key_quote')}")
    lines.append("")

lines.extend([
    "**关联项目：**",
    ", ".join(data.get("related_projects", ["待关联"])),
    "",
    f"*自动提炼于 {datetime.now(tz).strftime('%Y-%m-%d %H:%M')} 北京时间*"
])

with open(filepath, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"✅ 提炼笔记已保存: {filepath}")

# ── 6. 更新索引 ──────────────────────────────────────
index_path = "抖音素材库/00-索引.md"

# 读取现有索引
if os.path.exists(index_path):
    with open(index_path, "r") as f:
        index_content = f.read()
else:
    index_content = """# 抖音素材库索引

## 商业
| 标题 | 博主 | 日期 | 关联项目 |
|------|------|------|---------|

## 投资
| 标题 | 博主 | 日期 | 关联项目 |
|------|------|------|---------|

## 技术
| 标题 | 博主 | 日期 | 关联项目 |
|------|------|------|---------|

## 资讯
| 标题 | 博主 | 日期 | 关联项目 |
|------|------|------|---------|

## 个人成长
| 标题 | 博主 | 日期 | 关联项目 |
|------|------|------|---------|
"""

# 在对应分类表格中插入新条目
section_header = f"## {cat}"
new_entry = f"| [[已提炼/{cat_dir}/{filename}\|{data.get('title', 'untitled')}]] | {data.get('author', '待查')} | {today} | {', '.join(data.get('related_projects', ['待关联']))} |"

if section_header in index_content:
    # 找到表格第一行数据后面插入
    lines = index_content.split("\n")
    new_lines = []
    in_target_section = False
    inserted = False
    for i, line in enumerate(lines):
        new_lines.append(line)
        if line.startswith(section_header):
            in_target_section = True
            continue
        if in_target_section and line.startswith("|") and not inserted:
            # 在表头后面的第一行数据前插入
            if i+1 < len(lines) and lines[i+1].startswith("|"):
                new_lines.append(new_entry)
                inserted = True
    index_content = "\n".join(new_lines)

with open(index_path, "w", encoding="utf-8") as f:
    f.write(index_content)

print(f"✅ 索引已更新: {index_path}")
