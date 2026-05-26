"""P11 日报自动生成 — 三报架构。
每天 3 个时段，从多个国际权威 RSS 源采集，DeepSeek 提炼合成。

架构:
  08:00 BJT → 🤖 AI 日报 (TechCrunch + MIT Tech Review + VentureBeat + AIHOT)
  16:00 BJT → 📈 美股简报 (CNBC + MarketWatch + Eastmoney A股收盘)
  20:00 BJT → 🌍 全球市场收评 (CNBC + MarketWatch + 东方财富夜报)
"""
import os, sys, json, re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET
from urllib.request import urlopen, Request

# ── 配置 ──────────────────────────────────────────────
TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TZ).strftime("%Y-%m-%d")
NOW = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

REPORT_TYPE = os.environ.get("REPORT_TYPE", "ai")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# 三报数据源配置
SOURCES = {
    "ai": {
        "title_template": "🤖 AI 日报 | {date}",
        "source_name": "TechCrunch / MIT Tech Review / VentureBeat / AIHOT",
        "rss": [
            ("https://techcrunch.com/feed/", "TechCrunch"),
            ("https://www.technologyreview.com/feed/", "MIT Tech Review"),
            ("https://venturebeat.com/category/ai/feed/", "VentureBeat"),
        ],
        "html": [
            ("https://aihot.virxact.com/", "AIHOT"),  # 中文 AI 聚合
        ],
        "sections": ["产品发布与更新", "行业动态与融资", "研究与论文突破", "观点与深度分析"],
    },
    "us_market": {
        "title_template": "📈 美股简报 | {date}",
        "source_name": "CNBC / MarketWatch / 东方财富",
        "rss": [
            ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC"),
            ("https://feeds.marketwatch.com/marketwatch/topstories", "MarketWatch"),
        ],
        "html": [
            ("https://finance.eastmoney.com/a/czqyw.html", "东方财富"),
        ],
        "sections": ["盘前风向", "板块轮动", "关键个股与财报", "A股收盘回顾", "风险提示"],
    },
    "global": {
        "title_template": "🌍 全球市场收评 | {date}",
        "source_name": "CNBC / MarketWatch / 东方财富",
        "rss": [
            ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC"),
            ("https://feeds.marketwatch.com/marketwatch/topstories", "MarketWatch"),
        ],
        "html": [
            ("https://finance.eastmoney.com/a/czqyw.html", "东方财富"),
        ],
        "sections": ["美股收盘", "欧洲与亚太", "大宗商品与外汇", "宏观与政策", "次日关注"],
    },
}

cfg = SOURCES.get(REPORT_TYPE, SOURCES["ai"])
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# ── 1. 多源采集 ────────────────────────────────────────
def fetch_rss(url, name):
    """抓取 RSS feed，返回条目列表"""
    try:
        req = Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml,application/xml"})
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        root = ET.fromstring(raw)
        items = []
        for item in root.findall(".//item")[:10]:  # 每个源最多取 10 条
            title = item.find("title")
            desc = item.find("description")
            link = item.find("link")
            pubdate = item.find("pubDate")
            items.append({
                "title": title.text.strip() if title is not None and title.text else "",
                "summary": _clean_html(desc.text[:300]) if desc is not None and desc.text else "",
                "url": link.text.strip() if link is not None and link.text else "",
                "date": pubdate.text.strip() if pubdate is not None and pubdate.text else "",
                "source": name,
            })
        print(f"  ✅ {name}: {len(items)} 条")
        return items
    except Exception as e:
        print(f"  ⚠️ {name}: {e}", file=sys.stderr)
        return []


def fetch_html(url, name):
    """抓取 HTML 页面，提取纯文本"""
    try:
        req = Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{3,}', '  ', text)
        lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 20]
        result = '\n'.join(lines[:80])
        print(f"  ✅ {name}: {len(result)} chars")
        return result[:6000]
    except Exception as e:
        print(f"  ⚠️ {name}: {e}", file=sys.stderr)
        return ""


def _clean_html(text):
    return re.sub(r'<[^>]+>', '', text or "").strip()


def collect_all():
    """从所有源采集并合并"""
    all_items = []
    html_texts = []

    for url, name in cfg.get("rss", []):
        items = fetch_rss(url, name)
        all_items.extend(items)

    for url, name in cfg.get("html", []):
        text = fetch_html(url, name)
        if text:
            html_texts.append(f"【来源：{name}】\n{text}")

    # 构建发给 DeepSeek 的文本
    parts = []

    # RSS 条目列表
    if all_items:
        rss_text = "\n\n".join(
            f"[{item['source']}] {item['title']}\n  {item['summary']}\n  {item['url']}"
            for item in all_items
        )
        parts.append(f"=== RSS 快讯 ({len(all_items)} 条) ===\n\n{rss_text}")

    # HTML 页面内容
    if html_texts:
        parts.append("\n\n=== 网页全文 ===\n\n" + "\n\n---\n\n".join(html_texts))

    combined = "\n".join(parts)
    print(f"\n📦 总采集: {len(all_items)} 条 RSS + {len([t for t in html_texts if t])} 个网页, {len(combined)} chars")
    return combined[:18000]  # DeepSeek context limit 安全边界


# ── 2. DeepSeek 炼油 ───────────────────────────────────
SYSTEM_PROMPTS = {
    "ai": """你是 AI 科技日报主编。从多源 RSS 和网页中提炼当日 AI 行业最重要的 8-16 条动态。

输出格式（严格 JSON）：
{
  "title": "🤖 AI 日报 | {date}",
  "headline": "一句话总结今日 AI 圈最重要的事",
  "sections": {
    "产品发布与更新": [
      {"title": "...", "summary": "1-2句话（简洁尖锐）", "url": "原文链接", "source": "TechCrunch/MIT Tech Review/..."}
    ],
    "行业动态与融资": [...],
    "研究与论文突破": [...],
    "观点与深度分析": [...]
  }
}

规则：
- 跨源去重：同一事件被多个源报道只保留一次，标注最权威的来源
- 每个分区最多 5 条，宁缺毋滥
- 只收录有实质信息的条目，跳过纯营销/PR 稿
- summary 要像跟朋友说话："今天 AI 圈发生了什么"
- 没有的板块返回空数组""",

    "us_market": """你是美股研究员。从多源财经 RSS 和 A 股收盘数据中提炼当日最重要的市场动态。

输出格式（严格 JSON）：
{
  "title": "📈 美股简报 | {date}",
  "headline": "一句话总结今日市场核心矛盾",
  "sections": {
    "盘前风向": [
      {"title": "...", "summary": "1-2句话", "url": "", "source": ""}
    ],
    "板块轮动": [
      {"title": "...", "summary": "...", "url": "", "source": ""}
    ],
    "关键个股与财报": [...],
    "A股收盘回顾": [...],
    "风险提示": [...]
  }
}

规则：
- 每个分区最多 4 条
- 数据要准确，不编造任何数字
- 明确标注每条信息的来源（CNBC/MarketWatch/东方财富）
- "风险提示"板块只列真正可能影响市场的事件""",

    "global": """你是全球宏观研究员。从多源财经 RSS 提炼当日全球市场收盘动态。

输出格式（严格 JSON）：
{
  "title": "🌍 全球市场收评 | {date}",
  "headline": "一句话总结今日全球市场主线",
  "sections": {
    "美股收盘": [
      {"title": "...", "summary": "点明涨跌幅+驱动因素", "url": "", "source": ""}
    ],
    "欧洲与亚太": [...],
    "大宗商品与外汇": [...],
    "宏观与政策": [...],
    "次日关注": [...]
  }
}

规则：
- 每个分区最多 4 条
- 美股收盘必须包含 S&P 500 涨跌幅
- 大宗商品包含 Brent/WTI 原油、黄金、铜
- "次日关注"列出下一个交易日最重要的 3-5 个事件
- 只收录当日最新动态"""
}


def refine(content):
    """DeepSeek API 调用"""
    import requests as req

    if not DEEPSEEK_KEY:
        print("❌ DEEPSEEK_API_KEY 未设置", file=sys.stderr)
        sys.exit(1)

    system_prompt = SYSTEM_PROMPTS.get(REPORT_TYPE, SYSTEM_PROMPTS["ai"]).replace("{date}", TODAY)

    resp = req.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"以下是 {TODAY} 从多个信息源采集的原始内容，请提炼为日报：\n\n{content}"},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


# ── 3. 生成 Markdown ──────────────────────────────────
def build_markdown(data, report_type):
    lines = [
        "---",
        f"type: daily-report",
        f"report_type: {report_type}",
        f"date: \"{TODAY}\"",
        f"tags: [{report_type}, 日报, 自动生成, 多源RSS]",
        f"sources: \"{cfg['source_name']}\"",
        "---",
        "",
        f"# {data.get('title', cfg['title_template'].format(date=TODAY))}",
        "",
    ]

    if data.get("headline"):
        lines.append(f"> {data['headline']}")
        lines.append("")

    lines.append(f"> 📡 来源：{cfg['source_name']} · 自动采集+DeepSeek 提炼")
    lines.append(f"> ⏰ 生成时间：{NOW} (北京时间)")
    lines.append("")

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

            meta = []
            if src:
                meta.append(f"📍 {src}")
            if meta:
                lines.append(f"> {' · '.join(meta)}")
            lines.append("")
            lines.append(summary)
            lines.append("")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"🤖 由 [AI 情报工厂](https://github.com/Daniel421-luo/content-factory) 自动生成 · {len(data.get('sections', {}))} 个板块")
    return "\n".join(lines)


# ── 4. 保存 ──────────────────────────────────────────
def save(md, data, report_type):
    prefix_map = {"ai": "AI日报", "us_market": "美股简报", "global": "全球市场"}
    prefix = prefix_map.get(report_type, "日报")
    out_dir = "日报"
    os.makedirs(out_dir, exist_ok=True)

    filepath = os.path.join(out_dir, f"{prefix}-{TODAY}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✅ {prefix} Markdown: {filepath}")

    jsonpath = os.path.join(out_dir, f"{prefix}-{TODAY}.json")
    with open(jsonpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {prefix} JSON: {jsonpath}")


# ── main ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🔄 P11 日报引擎启动 · {REPORT_TYPE} · {NOW}")
    print(f"📡 数据源: {cfg['source_name']}")

    print("\n── 1. 多源采集 ──")
    content = collect_all()
    if not content or len(content) < 200:
        print("❌ 采集内容不足，退出")
        sys.exit(0)

    print("\n── 2. DeepSeek 炼油 ──")
    data = refine(content)

    print("\n── 3. 生成 Markdown ──")
    md = build_markdown(data, REPORT_TYPE)

    print("\n── 4. 保存 ──")
    save(md, data, REPORT_TYPE)

    print(f"\n🎉 {cfg['title_template'].format(date=TODAY)} 生成完成")
