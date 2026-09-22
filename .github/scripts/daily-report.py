"""P11 日报引擎 v5 — 全国际主流数据源，两报架构。

每天 2 个时段，每报 5-8 个 RSS/Atom 源，DeepSeek 跨源合成。
所有源均为国际主流媒体（BBC/Reuters/CNBC/AP/TechCrunch 等）。
GitHub Actions runner 在美国机房，全源可达。

两报:
  08:00 BJT → 🤖 晨报·AI (科技 RSS × 7 + AIHOT 中文源)
  18:00 BJT → 🌙 晚报·市场与全球 (财经 + 时政 RSS × 12 合并)

v5 更新（2026-09-22）:
  - 【合并】原「美股简报(16:00)」+「全球简报(20:00)」→「晚报(18:00)」一份
    原因：两报共用 CNBC/BBC 源，同一事件（如中美会谈）被采集提炼两次
  - 【去重】新增跨天去重：提炼前注入前 2 天标题，已有内容不再重复输出
  - 保留 AI 日报独立（其源为 AIHOT 168 中文源 + 科技媒体，与财经/时政源几乎不重叠）

v4 更新:
  - pubDate 解析 + 24h 新鲜度过滤（杜绝过期内容）
  - 跨 section 去重规则（同一事件只出现在最相关的 section）
  - 强化反幻觉规则（绝不编造数字/价格变动/百分比）
  - WSJ Markets 源从 feeds.a.dj.com 迁移到 feeds.content.dowjones.io
"""
import os, sys, json, re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
from urllib.request import urlopen, Request

TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TZ).strftime("%Y-%m-%d")
NOW = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
NOW_UTC = datetime.now(timezone.utc)
CUTOFF = NOW_UTC - timedelta(hours=48)  # 48h: handles weekends + timezone skew
REPORT_TYPE = os.environ.get("REPORT_TYPE", "ai")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# 跨天去重：注入前 N 天已推送的标题，避免同一事件反复出现
DEDUP_DAYS = 2
# 各报对应的历史文件前缀（用于读取前几天的标题）
# 一个报种可对应多个前缀：晚报 是 美股简报+全球简报 合并而来，
# 过渡期需同时回溯旧报，否则合并首日会重复推送旧报已报过的内容。
HISTORY_PREFIX = {
    "ai": ["AI日报"],
    "evening": ["晚报", "美股简报", "全球简报"],
    # 旧报种保留（手动触发时仍可用）
    "us_market": ["美股简报"],
    "global": ["全球简报"],
}

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

铁律（违反任何一条均为不合格输出）：

【反幻觉铁律】
- 绝不编造任何数字：融资金额、估值、增长率、百分比。若来源未提供，不写具体数字
- 每条的 url 字段必须来自原始 feeds 中真实存在的链接。不要编造 URL
- 不确定的信息 → 省略，不要猜测

【跨 section 去重铁律】
- 同一事件绝不能在多个 section 中出现
- 生成完所有 section 后，逐条交叉检查 URL 是否重复 → 删除重复，只保留最相关的一条

常规规则：
- 跨源去重：同一事件多家报道 → 只保留一条，标注最权威的来源
- 每 section 最多 5 条，质量优先于数量
- summary：像跟朋友聊天一样精炼，说清楚"发生了什么、为什么重要"
- 跳过纯 PR/营销软文
- 空 section → 空数组
- 所有 title 和 summary 必须用简体中文输出""",
    },

    "evening": {
        "title": "🌙 晚报",
        "source_label": "CNBC / MarketWatch / WSJ / Reuters / BBC / Seeking Alpha / NPR / ABC / Guardian / Fox",
        "feeds": [
            # ── 财经（原美股简报源）
            ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC",         "rss"),
            ("https://feeds.marketwatch.com/marketwatch/topstories",                              "MarketWatch",  "rss"),
            ("https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",                        "WSJ Markets",  "rss"),
            ("https://feeds.bbci.co.uk/news/business/rss.xml",                                    "BBC Business", "rss"),  # [GA]
            ("https://seekingalpha.com/feed.xml",                                                 "Seeking Alpha","rss"),  # 个股催化剂
            ("https://www.cbsnews.com/latest/rss/moneywatch",                            "CBS MoneyWatch","rss"),
            # ── 时政（原全球简报源）
            ("https://feeds.npr.org/1001/rss.xml",                           "NPR",           "rss"),
            ("https://abcnews.go.com/abcnews/topstories",                    "ABC News",      "rss"),
            ("https://feeds.bbci.co.uk/news/world/rss.xml",                  "BBC World",     "rss"),  # [GA]
            ("https://moxie.foxnews.com/google-publisher/latest.xml",        "Fox News",      "rss"),  # [GA]
            ("https://www.theguardian.com/world/rss",                        "Guardian",      "rss"),  # [GA]
            ("https://www.cnbc.com/id/100727362/device/rss/rss.html",        "CNBC World",    "rss"),
        ],
        "sections": [
            "盘前信号",
            "市场与宏观经济",
            "财报与重点个股",
            "半导体观察",
            "地缘政治",
            "风险雷达",
            "明日关注",
        ],
        "system_prompt": """你是一名资深市场分析师 + 国际新闻编辑，负责撰写整合财经与时政的晚间简报。
从多个财经与时政新闻源综合今天最重要的信息。这份简报同时服务「了解市场」和「了解世界」。

输出严格的 JSON（字段名保持英文，内容全部中文）：
{
  "title": "🌙 晚报 | YYYY-MM-DD",
  "headline": "今日市场与全球最重要事件的一句话概括（中文）",
  "sections": {
    "盘前信号": [
      {"title": "中文标题", "summary": "1-2 句含关键数据（中文）", "url": "", "source": ""}
    ],
    "市场与宏观经济": [...],
    "财报与重点个股": [...],
    "半导体观察": [...],
    "地缘政治": [...],
    "风险雷达": [...],
    "明日关注": [...]
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

铁律（违反任何一条均为不合格输出）：

【反幻觉铁律】—— 最高优先级
- 绝不编造任何数字：价格、百分比、涨跌幅、市值、交易量、伤亡人数、经济损失。若来源未提供具体数字，写"大幅波动"而非"暴跌16%"
- 每条的 url 字段必须来自原始 feeds 中真实存在的链接。不要编造 URL
- 若来源只说"英伟达下跌"，你不能写成"英伟达暴跌16%"
- 摘要中提到的任何事实必须在来源文章中能找到对应。不确定的信息 → 省略
- 如果一条新闻的信息不足以支撑一条独立的摘要，跳过它

【跨 section 去重铁律】—— 第二优先级
- 同一事件绝不能在多个 section 中出现
- 例：一条「中美就 AI 安全磋商」的新闻，不能同时出现在「地缘政治」和「市场与宏观经济」——只放在最相关的那个 section
- 生成完所有 section 后，必须逐条交叉检查 URL 是否重复 → 删除重复
- 同一标的的不同角度（如 NVDA 财报 vs NVDA 出口管制）可以分属不同 section，但必须是不同事件

【时效性铁律】
- 只使用最近 24-30 小时的新闻
- 旧闻（几天前）除非有重大新进展，否则不收录

常规规则：
- 每 section 最多 4-5 条，质量优先于数量
- 跨源去重：同一事件多家报道 → 只保留一条，标注最权威来源
- 「盘前信号」放当日开盘前最值得关注的市场动向
- 「地缘政治」放国际冲突、外交、政策类事件
- 「风险雷达」放可能扰动市场但尚未定价的风险
- 「明日关注」放未来 24-48h 关键事件（经济数据、选举、峰会、财报）
- 跳过纯 PR/营销软文
- 空 section → 空数组
- 所有 title 和 summary 必须用简体中文输出

投资信号矩阵规则：
- 从今日新闻中提炼 5-12 条可操作的投资信号
- 置信度 1-5（整数）：5=多源确认+直接价格影响；3=可信来源+中等概率；1=推测性/单源
- asset_impact 必须写具体代码或 ETF（如 "NVDA, SOXX" 不能写 "半导体"）
- 优先覆盖：半导体(NVDA/AMD/INTC/MU/AVGO/TSM/SOXX)、Mag7(AAPL/MSFT/GOOGL/AMZN/META/TSLA/NVDA)、能源(XLE/USO)、中国(FXI/ASHR/KWEB)、商品(GLD/SLV/COPX/USO)、主权债(TLT, US10Y)、汇率(EURUSD, DXY)
- 过滤噪音：只收录可能引起 >=1% 价格波动的信号
- direction 必须使用：看多 | 看空 | 中性
- timeframe：今日 | 本周 | 持续
- catalyst_type：宏观 | 财报 | 地缘 | 政策 | 技术面
- 所有 signal 字段内容必须用简体中文
- 信号矩阵中的信号也必须遵守反幻觉铁律：不编造数字""",
    },
}

# ── RSS/Atom 解析 ─────────────────────────────────────
def _parse_pubdate(entry, is_atom, ns):
    """Extract and parse pubDate from RSS or Atom entry. Returns datetime or None."""
    candidates = []
    if is_atom:
        for tag in ["atom:published", "atom:updated"]:
            el = entry.find(tag, ns)
            if el is not None and el.text:
                candidates.append(el.text)
        for tag in ["{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"]:
            el = entry.find(tag)
            if el is not None and el.text:
                candidates.append(el.text)
    else:
        pub = entry.find("pubDate")
        if pub is not None and pub.text:
            candidates.append(pub.text)
        # Some feeds use dc:date
        dc = entry.find("{http://purl.org/dc/elements/1.1/}date")
        if dc is not None and dc.text:
            candidates.append(dc.text)

    for raw in candidates:
        try:
            return parsedate_to_datetime(raw.strip())
        except (ValueError, TypeError):
            continue
    return None


def fetch_feed(url, name, fmt="rss"):
    """抓取 RSS 或 Atom feed，返回条目列表。过滤 24h 以前的内容。失败返回空列表不中断。"""
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
        stale = 0
        for entry in entries[:12]:  # sample more entries to account for stale filtering
            # ── Date freshness check ──
            pub_dt = _parse_pubdate(entry, is_atom, ns)
            if pub_dt is not None and pub_dt < CUTOFF:
                stale += 1
                continue

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
                "pub_date": pub_dt.isoformat() if pub_dt else None,
            })
            if len(items) >= 8:
                break

        print(f"  ✅ {name}: {len(items)} items (filtered {stale} stale)")
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


# ── 跨天去重：读取前 N 天标题 ──────────────────────────
def load_recent_titles(days=DEDUP_DAYS):
    """读取前 N 天已推送的标题，供 DeepSeek 判断哪些事件已经报过。

    返回 (titles_by_day, date_span)：
      titles_by_day = {"2026-09-21": ["标题1", ...], ...}

    一个报种可有多个历史前缀（如 evening = 晚报 + 美股简报 + 全球简报），
    同一日期多个前缀的标题会合并去重，避免重复注入。
    """
    prefixes = HISTORY_PREFIX.get(REPORT_TYPE)
    if not prefixes:
        return {}, ""

    by_day = {}
    for i in range(1, days + 1):
        d = (datetime.now(TZ) - timedelta(days=i)).strftime("%Y-%m-%d")
        day_titles = []
        for prefix in prefixes:
            fp = os.path.join("日报", f"{prefix}-{d}.md")
            if not os.path.exists(fp):
                continue
            try:
                with open(fp, encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("### "):
                            t = line[4:].strip()
                            if t.startswith("["):
                                t = re.sub(r"^\[(.*?)\](\(.*?\))?$", r"\1", t)
                            t = t.strip()
                            if t:
                                day_titles.append(t)
            except Exception as e:
                print(f"  ⚠️ 读取历史 {fp} 失败: {type(e).__name__}")
                continue
        # 同一天多前缀 → 按标题去重（保持顺序）
        if day_titles:
            by_day[d] = list(dict.fromkeys(day_titles))

    span = "、".join(by_day.keys()) if by_day else ""
    return by_day, span


def build_dedup_block(titles_by_day, span):
    """把前几天的标题格式化为 prompt 注入块。无历史则返回空串。"""
    if not titles_by_day:
        return ""
    lines = [
        "",
        "【跨天去重输入】",
        f"以下是 {span} 已推送过的标题。请用它们判断今天的内容是否重复：",
        "",
    ]
    for d, titles in sorted(titles_by_day.items(), reverse=True):
        lines.append(f"— {d} —")
        for t in titles:
            lines.append(f"  · {t}")
        lines.append("")
    lines.extend([
        "【跨天去重规则】—— 与上面【跨 section 去重铁律】同等优先级",
        "对与历史列表重复的事件，按以下三种情况处理：",
        "  1. 完全无新进展  → 直接跳过，不要出现在今天的简报里",
        "  2. 有实质新进展  → 只写「新进展」部分，标题末尾加「（更新）」",
        "  3. 有重大反转/升级 → 正常收录，标题末尾加「（重大更新）」",
        "判断「有无进展」要看事实变化（新数字/新表态/新执行），不是换了一家媒体重报。",
        "宁可少收录，也不要重复收录。今天是 2 份简报中的一份，读者不希望读第二遍。",
    ])
    return "\n".join(lines)


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

    # 跨天去重：注入前 N 天标题
    titles_by_day, span = load_recent_titles()
    dedup_block = build_dedup_block(titles_by_day, span)
    if dedup_block:
        n_titles = sum(len(v) for v in titles_by_day.values())
        print(f"  🔁 跨天去重：注入 {span} 的 {n_titles} 条历史标题")
    else:
        print(f"  🔁 跨天去重：无历史文件（首次运行或新报种）")

    resp = req.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": (
                    f"今天日期：{TODAY}（北京时间）。只使用最近 24-30 小时的新闻。\n"
                    f"下面的 feeds 中可能混有旧闻（几天甚至几周前的），请自行判断时效性并过滤。\n"
                    f"如果某条 feed 内容的日期明显早于 {TODAY}，忽略它。\n"
                    f"{dedup_block}\n\n"
                    f"Raw feeds:\n\n{content}"
                )},
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
    repo_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "your/content-factory")
    lines.append(f"*由 [AI Content Factory]({repo_url}) 自动生成 · {len(data.get('sections', {}))} 个板块*")
    return "\n".join(lines)


# ── 保存 ──────────────────────────────────────────────
def save(md, data):
    prefix_map = {"ai": "AI日报", "evening": "晚报", "us_market": "美股简报", "global": "全球简报"}
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
    cfg = SOURCES.get(REPORT_TYPE)
    if not cfg:
        print(f"❌ Unknown REPORT_TYPE={REPORT_TYPE!r}. Valid: {list(SOURCES)}", file=sys.stderr)
        sys.exit(1)
    print(f"🔄 P11 v5 · {cfg['title']} · {NOW}")
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
