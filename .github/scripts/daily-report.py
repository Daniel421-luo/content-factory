"""P11 日报引擎 v3 — 全国际主流数据源，三报架构。

每天 3 个时段，每报 5-8 个 RSS/Atom 源，DeepSeek 跨源合成。
所有源均为国际主流媒体（BBC/Reuters/CNBC/AP/TechCrunch 等）。
GitHub Actions runner 在美国机房，全源可达。

三报:
  08:00 BJT → 🤖 AI Daily (科技 RSS × 7)
  16:00 BJT → 📈 Wall Street Brief (财经 RSS × 6)
  20:00 BJT → 🌍 Global Brief (世界新闻 RSS × 8)
"""
import os, sys, json, re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET
from urllib.request import urlopen, Request

TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TZ).strftime("%Y-%m-%d")
NOW = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
REPORT_TYPE = os.environ.get("REPORT_TYPE", "ai")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ── 数据源配置 ──────────────────────────────────────────
# 每个源: (url, name, format)
# format: "rss" | "atom"
# 标记 [GA] = 仅 GitHub Actions 可达（被墙但美国机房能通）

SOURCES = {
    "ai": {
        "title": "🤖 AI Daily",
        "source_label": "AIHOT (中文168信源) / TechCrunch / MIT Tech Review / VentureBeat / Wired / Ars Technica / ZDNet / The Verge",
        "feeds": [
            ("https://techcrunch.com/feed/",                     "TechCrunch",     "rss"),
            ("https://www.technologyreview.com/feed/",           "MIT Tech Review", "rss"),
            ("https://venturebeat.com/category/ai/feed/",        "VentureBeat",     "rss"),
            ("https://www.wired.com/feed/rss",                   "Wired",           "rss"),
            ("https://feeds.arstechnica.com/arstechnica/index",  "Ars Technica",    "rss"),
            ("https://www.zdnet.com/news/rss.xml",               "ZDNet",           "rss"),
            ("https://www.theverge.com/rss/index.xml",           "The Verge",       "atom"),
        ],
        "sections": [
            "产品发布与更新",
            "行业动态与融资",
            "研究论文",
            "观点与深度分析",
        ],
        "system_prompt": """你是一家 AI 科技媒体的主编，负责撰写每日 AI 行业简报。
从多个国际科技媒体来源综合今天最重要的 AI 动态。

输出严格的 JSON（字段名保持英文，内容全部中文）：
{
  "title": "🤖 AI 日报 | YYYY-MM-DD",
  "headline": "今日 AI 领域最重要事件的一句话概括（中文）",
  "sections": {
    "产品发布与更新": [
      {"title": "中文标题", "summary": "1-2 句精炼摘要（中文）", "url": "", "source": ""}
    ],
    "行业动态与融资": [...],
    "研究论文": [...],
    "观点与深度分析": [...]
  }
}

规则：
- 跨源去重：同一事件多家报道 → 只保留一条，标注最权威的来源
- 每 section 最多 5 条，质量优先于数量
- summary：像跟朋友聊天一样精炼，说清楚"发生了什么、为什么重要"
- 跳过纯 PR/营销软文
- 空 section → 空数组
- 所有 title 和 summary 必须用简体中文输出""",
    },

    "us_market": {
        "title": "📈 美股简报",
        "source_label": "CNBC / MarketWatch / WSJ / Reuters / BBC Business / Seeking Alpha",
        "feeds": [
            ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC",         "rss"),
            ("https://www.cnbc.com/id/100727362/device/rss/rss.html",                             "CNBC World",   "rss"),
            ("https://feeds.marketwatch.com/marketwatch/topstories",                              "MarketWatch",  "rss"),
            ("https://feeds.marketwatch.com/marketwatch/marketpulse",                              "MW Pulse",     "rss"),
            ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml",                                     "WSJ Markets",  "rss"),
            ("https://feeds.bbci.co.uk/news/business/rss.xml",                                    "BBC Business", "rss"),  # [GA]
            ("https://seekingalpha.com/feed.xml",                                                 "Seeking Alpha","rss"),  # 个股催化剂（评级/目标价/事件）
            ("https://www.cbsnews.com/latest/rss/moneywatch",                            "CBS MoneyWatch","rss"),  # 商业/财经
        ],
        "sections": [
	    "盘前信号",
            "板块轮动",
            "财报与重点个股",
            "半导体观察",
            "宏观与政策",
            "风险雷达",
        ],
        "system_prompt": """你是一名美股分析师，负责撰写盘前简报。
从多个财经新闻来源综合今天最重要的市场信息。

输出严格的 JSON（字段名保持英文，内容全部中文）：
{
  "title": "📈 美股简报 | YYYY-MM-DD",
  "headline": "今日市场主线的一句话概括（中文）",
  "sections": {
    "盘前信号": [
      {"title": "中文标题", "summary": "1-2 句含关键数据（中文）", "url": "", "source": ""}
    ],
    "板块轮动": [...],
    "财报与重点个股": [...],
    "半导体观察": [...],
    "宏观与政策": [...],
    "风险雷达": [...]
  },
  "signal_matrix": [
    {
      "signal": "简洁的事件描述（中文）",
      "direction": "看多 | 看空 | 中性",
      "asset_impact": "NVDA, SOXX 等",
      "confidence": 4,
      "timeframe": "今日 | 本周 | 持续",
      "catalyst_type": "宏观 | 财报 | 地缘 | 政策 | 技术面"
    }
  ]
}

规则：
- 每 section 最多 4 条
- 绝不编造数字。来源给了具体价格/百分比，必须原样引用
- 必须标注来源（CNBC/MarketWatch/WSJ 等）
- "风险雷达"：只列可能真正影响今日/明日市场的风险事件
- "盘前信号"：如有期货方向必须注明
- "半导体观察"：必须扫描这些标的 — MU (美光), NVDA, AMD, INTC, SOXX, AVGO, TSM。包括分析师评级变化、目标价调整、产品发布、供应链消息、异常价格波动。如有单日涨跌幅 >5%，必须标注百分比和催化剂。此 section 为最高优先级。

投资信号矩阵规则：
- 从今日新闻中提炼 5-12 条可操作的投资信号
- 置信度 1-5（整数）：5=多源确认+直接价格影响；3=可信来源+中等概率；1=推测性/单源
- asset_impact 必须写具体代码或 ETF（如 "NVDA, SOXX" 不能写 "半导体"）
- 优先覆盖：半导体(NVDA/AMD/INTC/MU/AVGO/TSM/SOXX)、Mag7(AAPL/MSFT/GOOGL/AMZN/META/TSLA/NVDA)、能源(XLE/USO)、中国(FXI/ASHR/KWEB)、商品(GLD/SLV/COPX/USO)
- 过滤噪音：只收录可能引起 >=1% 价格波动的信号
- direction 必须使用：看多 | 看空 | 中性
- timeframe：今日 | 本周 | 持续
- catalyst_type：宏观 | 财报 | 地缘 | 政策 | 技术面
- 所有 signal 字段内容必须用简体中文""",

    },

    "global": {
        "title": "🌍 全球简报",
        "source_label": "NPR / ABC News / BBC World / Fox News / Guardian / CNBC",
        "feeds": [
            ("https://feeds.npr.org/1001/rss.xml",                           "NPR",           "rss"),
            ("https://abcnews.go.com/abcnews/topstories",                    "ABC News",      "rss"),
            ("https://feeds.bbci.co.uk/news/world/rss.xml",                  "BBC World",     "rss"),  # [GA]
            ("https://moxie.foxnews.com/google-publisher/latest.xml",        "Fox News",      "rss"),  # [GA]
            ("https://www.theguardian.com/world/rss",                        "Guardian",      "rss"),  # [GA]
            ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC", "rss"),
            ("https://www.cnbc.com/id/100727362/device/rss/rss.html",        "CNBC World",    "rss"),
        ],
        "sections": [
            "头条新闻",
            "地缘政治",
            "市场与经济",
            "科技",
            "明日关注",
        ],
        "system_prompt": """你是一名全球新闻编辑，负责撰写晚间世界简报。
从多个国际新闻社综合当天最重要的全球动态。

输出严格的 JSON（字段名保持英文，内容全部中文）：
{
  "title": "🌍 全球简报 | YYYY-MM-DD",
  "headline": "当天全球最重要事件的一句话概括（中文）",
  "sections": {
    "头条新闻": [
      {"title": "中文标题", "summary": "1-2 句精炼摘要（中文）", "url": "", "source": ""}
    ],
    "地缘政治": [...],
    "市场与经济": [...],
    "科技": [...],
    "明日关注": [...]
  },
  "signal_matrix": [
    {
      "signal": "简洁的事件描述（中文）",
      "direction": "看多 | 看空 | 中性",
      "asset_impact": "GLD, USO, FXI, /ES, US10Y 等",
      "confidence": 3,
      "timeframe": "本周 | 持续",
      "catalyst_type": "宏观 | 地缘 | 政策"
    }
  ]
}

规则：
- 每 section 最多 4 条
- 跨源去重：同一事件多家报道 → 一条，最权威来源
- "头条新闻"：主导当天全球头条的 3-4 条新闻
- "明日关注"：未来 24-48h 关键事件（经济数据、选举、峰会、财报）
- 必须标注来源（AP/Reuters/BBC/CNN 等）
- 绝不编造细节

投资信号矩阵规则：
- 提炼 5-10 条宏观/地缘投资信号
- 聚焦跨资产影响：货币、商品、主权债、股指
- 置信度：5=多源确认+清晰市场机制；1=推测性尾部风险
- asset_impact 举例：US10Y, /ES, GLD, USO, FXI, EURUSD, VIX
- 过滤不会影响任何可交易资产的信号
- catalyst_type：宏观 | 地缘 | 政策（不涉及财报/技术面）
- direction：看多 | 看空 | 中性
- 所有 signal 字段内容必须用简体中文""",
    },
}


# ── RSS/Atom 解析 ─────────────────────────────────────
def fetch_feed(url, name, fmt="rss"):
    """抓取 RSS 或 Atom feed，返回条目列表。失败返回空列表不中断。"""
    try:
        req = Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml",
        })
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        root = ET.fromstring(raw)

        # Atom 格式
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        is_atom = root.tag == "{http://www.w3.org/2005/Atom}feed" or fmt == "atom"

        if is_atom:
            entries = root.findall("atom:entry", ns)
            if not entries:
                entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        else:
            entries = root.findall(".//item")

        items = []
        for entry in entries[:8]:
            if is_atom:
                title = entry.find("atom:title", ns) or entry.find("{http://www.w3.org/2005/Atom}title")
                summary = entry.find("atom:summary", ns) or entry.find("{http://www.w3.org/2005/Atom}summary")
                link = entry.find("atom:link", ns) or entry.find("{http://www.w3.org/2005/Atom}link")
            else:
                title = entry.find("title")
                summary = entry.find("description")
                link = entry.find("link")

            title_text = title.text.strip() if title is not None and title.text else ""
            if not title_text:
                continue

            summary_text = ""
            if summary is not None:
                raw_s = summary.text or ""
                summary_text = re.sub(r'<[^>]+>', '', raw_s).strip()[:300]

            link_text = ""
            if link is not None:
                href = link.get("href") or link.text or ""
                link_text = href.strip()

            items.append({
                "title": title_text,
                "summary": summary_text,
                "url": link_text,
                "source": name,
            })

        print(f"  ✅ {name}: {len(items)} items")
        return items

    except Exception as e:
        print(f"  ⚠️ {name}: {type(e).__name__} — skipped", file=sys.stderr)
        return []


# ── AIHOT API 抓取 ─────────────────────────────────────
def fetch_aihot():
    """从 AIHOT API 抓取中文AI新闻（168信源，数字生命卡兹克维护）。
    返回与 fetch_feed() 相同格式的 items 列表。"""
    try:
        req = Request("https://aihot.virxact.com/api/public/daily", headers={
            "User-Agent": UA,
            "Accept": "application/json",
        })
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        items = []
        sections = data.get("sections", [])
        for section in sections:
            section_label = section.get("label", "")
            for entry in section.get("items", [])[:3]:  # Top 3 per section
                title = entry.get("title", "")
                summary_zh = entry.get("summaryZh", entry.get("summary", ""))
                url = entry.get("sourceUrl", entry.get("url", ""))
                if not title:
                    continue
                items.append({
                    "title": title,
                    "summary": (summary_zh or "")[:200],
                    "url": url,
                    "source": f"AIHOT/{section_label}",
                })

        print(f"  ✅ AIHOT: {len(items)} items from {len(sections)} sections")
        return items

    except Exception as e:
        print(f"  ⚠️ AIHOT: {type(e).__name__} — skipped", file=sys.stderr)
        return []


# ── 多源聚合 ──────────────────────────────────────────
def collect_all(cfg):
    """从所有源采集并聚合为纯文本"""
    all_items = []
    feed_counts = {}  # {name: count} for health check
    for url, name, fmt in cfg["feeds"]:
        items = fetch_feed(url, name, fmt)
        all_items.extend(items)
        feed_counts[name] = len(items)

    # Feed health summary
    zero_feeds = [n for n, c in feed_counts.items() if c == 0]
    active_feeds = [n for n, c in feed_counts.items() if c > 0]
    print(f"  📊 Feed health: {len(active_feeds)}/{len(cfg['feeds'])} active")
    if zero_feeds:
        print(f"  ⚠️  Empty feeds: {', '.join(zero_feeds)}")

    # AIHOT 中文源（仅 AI 日报）
    if REPORT_TYPE == "ai":
        aihot_items = fetch_aihot()
        all_items.extend(aihot_items)

    if not all_items:
        return ""

    lines = [f"=== {len(all_items)} Headlines from {len(cfg['feeds'])} Sources ==="]
    for item in all_items:
        lines.append(f"\n[{item['source']}] {item['title']}")
        if item["summary"]:
            lines.append(f"  {item['summary']}")
        if item["url"]:
            lines.append(f"  🔗 {item['url']}")

    result = "\n".join(lines)
    print(f"  📦 Total: {len(all_items)} items, {len(result)} chars")
    return result[:16000]


# ── DeepSeek 炼油 ─────────────────────────────────────
def refine(content, cfg):
    import requests as req
    if not DEEPSEEK_KEY:
        print("❌ DEEPSEEK_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    system = cfg["system_prompt"].replace("YYYY-MM-DD", TODAY)

    resp = req.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Raw feeds for {TODAY}. Synthesize into a daily brief:\n\n{content}"},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


# ── Markdown 生成 ─────────────────────────────────────
def build_markdown(data, cfg):
    lines = [
        "---",
        f"type: daily-report",
        f"report: {REPORT_TYPE}",
        f"date: \"{TODAY}\"",
        f"tags: [{REPORT_TYPE}, daily-brief, auto-generated, multi-source]",
        f"sources: \"{cfg['source_label']}\"",
        "---",
        "",
        f"# {data.get('title', cfg['title'] + ' | ' + TODAY)}",
        "",
    ]
    if data.get("headline"):
        lines.append(f"> {data['headline']}")
        lines.append("")

    lines.append(f"> 📡 {cfg['source_label']}")
    lines.append(f"> ⏰ Generated {NOW} (UTC+8) · Auto-collected + DeepSeek synthesis")
    lines.append("")

    for section_name, entries in data.get("sections", {}).items():
        if not entries:
            continue
        lines.append(f"## {section_name}")
        lines.append("")
        for e in entries:
            title = e.get("title", "")
            url = e.get("url", "")
            summary = e.get("summary", "")
            src = e.get("source", "")
            if url:
                lines.append(f"### [{title}]({url})")
            else:
                lines.append(f"### {title}")
            if src:
                lines.append(f"> 📍 {src}")
            lines.append("")
            lines.append(summary)
            lines.append("")

    # Investment Signal Matrix (NEW — only for us_market + global)
    signals = data.get("signal_matrix", [])
    if signals:
        lines.append("## 📊 投资信号矩阵")
        lines.append("")
        lines.append("| 信号事件 | 方向 | 影响标的 | 置信度 | 时间框架 |")
        lines.append("|--------|-----------|-------------|------------|-----------|")
        for s in signals:
            sig = s.get("signal", "")
            direction = s.get("direction", "")
            asset = s.get("asset_impact", "")
            conf = s.get("confidence", 3)
            tf = s.get("timeframe", "")
            stars = "★" * conf + "☆" * (5 - conf)
            lines.append(f"| {sig} | {direction} | {asset} | {stars} | {tf} |")
        lines.append("")
        lines.append(f"> *{len(signals)} 条信号，取自今日新闻。置信度：★★★★★ = 多源确认。仅供参考，不构成投资建议。*")
        lines.append("")

    lines.append("---")
    lines.append(f"*由 [AI Content Factory](https://github.com/Daniel421-luo/content-factory) 自动生成 · {len(data.get('sections', {}))} 个板块*")
    return "\n".join(lines)


# ── 保存 ──────────────────────────────────────────────
def save(md, data):
    prefix_map = {"ai": "AI日报", "us_market": "美股简报", "global": "全球简报"}
    prefix = prefix_map.get(REPORT_TYPE, "日报")
    out_dir = "日报"
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, f"{prefix}-{TODAY}.md")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  ✅ {fp}")
    jp = os.path.join(out_dir, f"{prefix}-{TODAY}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {jp}")


# ── main ──────────────────────────────────────────────
if __name__ == "__main__":
    cfg = SOURCES.get(REPORT_TYPE, SOURCES["ai"])
    print(f"🔄 P11 v3 · {cfg['title']} · {NOW}")
    print(f"📡 {len(cfg['feeds'])} sources: {cfg['source_label']}")
    print()

    content = collect_all(cfg)
    if not content or len(content) < 300:
        print("❌ Insufficient content collected. Exiting.")
        sys.exit(0)

    print(f"\n🧠 Refining via DeepSeek ({len(content)} chars → structured JSON)...")
    data = refine(content, cfg)

    print(f"\n📝 Generating Markdown...")
    md = build_markdown(data, cfg)

    print(f"\n💾 Saving...")
    save(md, data)

    print(f"\n🎉 {cfg['title']} complete — {sum(1 for v in data.get('sections', {}).values() if v)} sections")
