"""每周改写：批量读取本周全部提炼笔记 → 选3篇精华 → 改写为公众号/小红书初稿。"""
import os, sys, json, glob, re, requests
from datetime import datetime, timezone, timedelta

tz = timezone(timedelta(hours=8))
now = datetime.now(tz)
week_start = (now - timedelta(days=now.weekday() + 7)).strftime("%Y-%m-%d")

# ── 1. 读取本周所有提炼笔记 ──────────────────────────
notes = []
for cat_dir in glob.glob("抖音素材库/已提炼/*/"):
    for md_file in glob.glob(os.path.join(cat_dir, "*.md")):
        with open(md_file, "r") as f:
            content = f.read()
        # 检查日期是否在本周内
        dates = re.findall(r'date:\s*"(\d{4}-\d{2}-\d{2})"', content)
        if dates and dates[0] >= week_start:
            notes.append({"file": md_file, "content": content[:3000], "date": dates[0]})

if not notes:
    print("本周无新增笔记")
    sys.exit(0)

print(f"📚 本周共 {len(notes)} 篇新笔记")

# 合并所有笔记内容（截取关键部分）
combined = "\n\n---\n\n".join([
    f"## [{n['date']}] {n['file']}\n{n['content'][:2000]}"
    for n in notes
])

# ── 2. DeepSeek 选精华 ───────────────────────────────
SELECT_PROMPT = """你是内容编辑。从本周的提炼笔记中选出3篇最有公众号价值的。

选择标准：
1. 话题热度（大家关心吗？）
2. 观点新鲜度（有人说过吗？）
3. 与你定位的匹配度（AI × 商业 × 定制家居 × 一人公司）

输出 JSON：
{
  "top3": [
    {
      "file": "文件名",
      "reason": "为什么选它（一句话）",
      "angle": "公众号文章建议切入角度"
    }
  ]
}"""

resp = requests.post(
    "https://api.deepseek.com/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
        "Content-Type": "application/json"
    },
    json={
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SELECT_PROMPT},
            {"role": "user", "content": combined[:10000]}
        ],
        "temperature": 0.5,
        "response_format": {"type": "json_object"}
    },
    timeout=120
)
resp.raise_for_status()
selection = json.loads(resp.json()["choices"][0]["message"]["content"])

# ── 3. 对每篇精选改写 ────────────────────────────────
REWRITE_PROMPT = """你是专业财经/科技写手。把笔记改写为公众号文章和小红书帖子。

公众号风格：
- 1500-2500字
- 开头hook要抓人
- 3-5个小标题
- 数据要有来源
- 结尾有CTA（引导关注/评论）
- 像"盗坤"或"老talk消息"的风格——有观点、有数据、有态度

小红书风格：
- 300-500字
- 标题公式：数字 + 痛点 + 解决方案
- emoji点缀但不泛滥
- 结尾引导互动

输出 JSON：
{
  "gzh": {
    "title": "公众号标题（<25字，有吸引力）",
    "body": "公众号正文（Markdown格式）"
  },
  "xhs": {
    "title": "小红书标题",
    "body": "小红书正文"
  }
}"""

for item in selection.get("top3", []):
    # 读取源笔记
    src_file = item.get("file", "")
    src_content = ""
    # 尝试在目录中找到该文件
    for cat_dir in glob.glob("抖音素材库/已提炼/*/"):
        for md_file in glob.glob(os.path.join(cat_dir, "*.md")):
            if os.path.basename(md_file) == os.path.basename(src_file):
                with open(md_file, "r") as f:
                    src_content = f.read()
                break

    if not src_content:
        print(f"⚠️ 找不到源文件: {src_file}")
        continue

    print(f"✍️ 改写中: {src_file} → 角度: {item.get('angle', '')}")

    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": REWRITE_PROMPT},
                {"role": "user", "content": f"""请基于以下笔记改写：

切入角度：{item.get('angle', '')}

笔记内容：
{src_content[:5000]}"""}
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        },
        timeout=180
    )
    resp.raise_for_status()
    result = json.loads(resp.json()["choices"][0]["message"]["content"])

    # ── 4. 保存 ────────────────────────────────────────
    today_str = now.strftime("%Y-%m-%d")
    safe_name = re.sub(r'[\\/:*?"<>|]', '-', item.get("angle", src_file)[:30])

    # 公众号
    gzh_dir = "内容发布/公众号/queue"
    os.makedirs(gzh_dir, exist_ok=True)
    gzh_path = os.path.join(gzh_dir, f"{today_str}_{safe_name}_公众号.md")
    with open(gzh_path, "w", encoding="utf-8") as f:
        f.write(f"# {result['gzh']['title']}\n\n")
        f.write(f"> 源笔记: {src_file}\n")
        f.write(f"> 改写角度: {item.get('angle', '')}\n")
        f.write(f"> 状态: ⏳ 待审核\n\n")
        f.write("---\n\n")
        f.write(result['gzh']['body'])
        f.write("\n\n---\n*🤖 AI改写 · 待人工审核发布*")
    print(f"✅ 公众号 → {gzh_path}")

    # 小红书
    xhs_dir = "内容发布/小红书/queue"
    os.makedirs(xhs_dir, exist_ok=True)
    xhs_path = os.path.join(xhs_dir, f"{today_str}_{safe_name}_小红书.md")
    with open(xhs_path, "w", encoding="utf-8") as f:
        f.write(f"# {result['xhs']['title']}\n\n")
        f.write(f"> 状态: ⏳ 待审核\n\n")
        f.write("---\n\n")
        f.write(result['xhs']['body'])
        f.write("\n\n---\n*🤖 AI改写 · 待人工审核发布*")
    print(f"✅ 小红书 → {xhs_path}")

print(f"\n🎉 本周改写完成！共生成内容，请审核后发布。")
