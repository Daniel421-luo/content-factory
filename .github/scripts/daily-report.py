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
            "Product Launches & Updates",
            "Industry Moves & Funding",
            "Research & Papers",
            "Opinion & Deep Dives",
        ],
        "system_prompt": """You are the editor-in-chief of an AI industry daily brief.
Synthesize today's most important AI developments from multiple international tech sources.

Output STRICT JSON:
{
  "title": "🤖 AI Daily | YYYY-MM-DD",
  "headline": "One-line summary of today's biggest AI story",
  "sections": {
    "Product Launches & Updates": [
      {"title": "...", "summary": "1-2 punchy sentences", "url": "", "source": ""}
    ],
    "Industry Moves & Funding": [...],
    "Research & Papers": [...],
    "Opinion & Deep Dives": [...]
  }
}

Rules:
- Cross-source dedup: same event reported by multiple sources = keep ONE, label the most authoritative source
- Max 5 items per section, quality over quantity
- summary: punchy, like telling a friend "here's what happened in AI today"
- Skip pure PR/marketing fluff
- Empty sections → empty array""",
    },

    "us_market": {
        "title": "📈 Wall Street Brief",
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
            "Pre-Market Signals",
            "Sector Rotation",
            "Earnings & Key Stocks",
            "半导体观察 Semiconductor Watch",
            "Macro & Policy",
            "Risk Radar",
        ],
        "system_prompt": """You are a US equity markets analyst preparing a pre-market brief.
Synthesize today's key market-moving information from multiple financial news sources.

Output STRICT JSON:
{
  "title": "📈 Wall Street Brief | YYYY-MM-DD",
  "headline": "One-line summary of today's market narrative",
  "sections": {
    "Pre-Market Signals": [
      {"title": "...", "summary": "1-2 sentences with key numbers", "url": "", "source": ""}
    ],
    "Sector Rotation": [...],
    "Earnings & Key Stocks": [...],
    "半导体观察 Semiconductor Watch": [...],
    "Macro & Policy": [...],
    "Risk Radar": [...]
  },
  "signal_matrix": [
    {
      "signal": "Concise event (English)",
      "direction": "Bullish | Bearish | Neutral",
      "asset_impact": "NVDA, SOXX, etc.",
      "confidence": 4,
      "timeframe": "today | this week | ongoing",
      "catalyst_type": "macro | earnings | geopolitical | policy | technical"
    }
  ]
}

Rules:
- Max 4 items per section
- NEVER fabricate numbers. If a source gives a specific price/percentage, cite it exactly
- Always attribute to source (CNBC/MarketWatch/WSJ/etc.)
- "Risk Radar": only list events that could genuinely move markets today/tomorrow
- Pre-Market: include futures direction if available
- "半导体观察 Semiconductor Watch": MUST scan for news about these tickers — MU (Micron), NVDA, AMD, INTC, SOXX, DRAM, AVGO, TSM. Include analyst upgrades/downgrades, price target changes, product launches, supply chain news, and unusual price movements. If there's a significant mover (>5%), ALWAYS include it with the percentage and catalyst. This section is the highest priority for our readers.

	INVESTMENT SIGNAL MATRIX Rules (NEW):
	- Generate 5-12 actionable investment signals distilled from today's news
	- Confidence ranges 1-5 (integer). Use this calibration: 5=multi-source confirmed, direct price impact expected today; 3=credible source, moderate impact probability; 1=speculative or single-source, low conviction
	- Asset impact MUST name specific tickers or ETFs (e.g. "NVDA, SOXX" not "semiconductors")
	- Priority coverage: Semis (NVDA/AMD/INTC/MU/AVGO/TSM/SOXX), Mag7 (AAPL/MSFT/GOOGL/AMZN/META/TSLA/NVDA), Energy (XLE/USO), China (FXI/ASHR/KWEB), Commodities (GLD/SLV/COPX/USO)
	- Filter noise: only include signals that could realistically move prices >=1%
	- catalyst_type must be exactly one of: macro | earnings | geopolitical | policy | technical
	- direction must be exactly: Bullish | Bearish | Neutral
	- timeframe: today | this week | ongoing
	- Add signal_matrix to the JSON output (array of signal objects)""",

    },

    "global": {
        "title": "🌍 Global Brief",
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
            "Top Stories",
            "Geopolitics",
            "Markets & Economy",
            "Technology & Science",
            "What to Watch Tomorrow",
        ],
        "system_prompt": """You are a global news editor preparing an evening world brief.
Synthesize today's most important international developments from multiple global news agencies.

Output STRICT JSON:
{
  "title": "🌍 Global Brief | YYYY-MM-DD",
  "headline": "One-line summary of today's dominant global story",
  "sections": {
    "Top Stories": [
      {"title": "...", "summary": "1-2 punchy sentences", "url": "", "source": ""}
    ],
    "Geopolitics": [...],
    "Markets & Economy": [...],
    "Technology & Science": [...],
    "What to Watch Tomorrow": [...]
  },
  "signal_matrix": [
    {
      "signal": "Concise event",
      "direction": "Bullish | Bearish | Neutral",
      "asset_impact": "GLD, USO, FXI, /ES, US10Y, etc.",
      "confidence": 3,
      "timeframe": "this week | ongoing",
      "catalyst_type": "macro | geopolitical | policy"
    }
  ]
}

Rules:
- Max 4 items per section
- Cross-source dedup: same event from multiple agencies → one entry, most authoritative source
- Top Stories: lead with the 3-4 stories that dominated global headlines today
- What to Watch: next 24-48h key events (economic data, elections, summits, earnings)
- Always attribute to source (AP/Reuters/BBC/CNN/etc.)
- Never fabricate details

SIGNAL MATRIX Rules (NEW):
- Generate 5-10 macro/geopolitical investment signals
- Focus on cross-asset impacts: currencies, commodities, sovereign bonds, equity indices
- Confidence: 5=confirmed multi-source with clear market mechanism; 1=speculative tail risk
- Asset impact examples: US10Y, /ES, GLD, USO, FXI, EURUSD, VIX
- Filter out signals that would not move any tradable asset
- catalyst_type for global: macro | geopolitical | policy (no earnings/technical)
- direction: Bullish | Bearish | Neutral
- Add signal_matrix to the JSON output""",
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
        lines.append("## 📊 Investment Signal Matrix")
        lines.append("")
        lines.append("| Signal | Direction | Asset Impact | Confidence | Timeframe |")
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
        lines.append(f"> *{len(signals)} signals distilled from today's news. Confidence: ★★★★★ = confirmed multi-source. Use as discussion starters, not trade orders.*")
        lines.append("")

    lines.append("---")
    lines.append(f"*Auto-generated by [AI Content Factory](https://github.com/Daniel421-luo/content-factory) · {len(data.get('sections', {}))} sections*")
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
