"""P11 周报引擎 — 读本周日报 → DeepSeek 策展 → 输出 视界HTML + MD。

周六 09:00 BJT 运行。读过去 7 天的 AI日报/美股简报/全球简报，
DeepSeek 精选 top 10 条目，按关注领域分类，输出：
  1. 周刊-YYYY-MM-DD.html — 视界级精美页面（可直接浏览器打开或 Obsidian 内嵌）
  2. 周刊-YYYY-MM-DD.md   — Obsidian 可编辑版本（含「我的看法」槽位）
"""
import os, sys, json, glob
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ)
TODAY = NOW.strftime("%Y-%m-%d")
SATURDAY = NOW  # 脚本在周六跑，所以 NOW 就是周六

# 本周一 → 周六的日期范围
MONDAY = SATURDAY - timedelta(days=SATURDAY.weekday())
DATES = [(MONDAY + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6)]  # Mon–Sat

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_KEY:
    print("❌ DEEPSEEK_API_KEY not set", file=sys.stderr)
    sys.exit(1)

# ── 读取本周所有日报 ─────────────────────────────────────
REPORT_DIR = "日报"
PATTERNS = {
    "ai": "AI日报-{}.md",
    "us": "美股简报-{}.md",
    "global": "全球简报-{}.md",
}

def read_week_reports():
    """读取本周所有日报，返回纯文本摘要"""
    all_content = []
    file_count = 0
    for date_str in DATES:
        for key, pattern in PATTERNS.items():
            fp = os.path.join(REPORT_DIR, pattern.format(date_str))
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    text = f.read()
                    # 取前 2500 字符（日报有 YAML frontmatter + 内容，截取足够但不过量）
                    all_content.append(f"=== {pattern.format(date_str)} ===\n{text[:2500]}\n")
                    file_count += 1

    if file_count == 0:
        print("❌ No reports found for this week", file=sys.stderr)
        return "", 0

    print(f"📚 Loaded {file_count} reports from {DATES[0]} ~ {DATES[-1]}")
    return "\n---\n".join(all_content), file_count

# ── DeepSeek 策展 ───────────────────────────────────────
SYSTEM_PROMPT = """你是一位顶级的信息策展人，为一位同时关注 AI商业、全屋定制行业、期权交易、效率工具的创始人筛选本周最重要的信息。

你的任务：从本周的日报中，精选出对这个人最有价值的 10-15 条信息，按四个领域分类。

输出严格的 JSON（字段名英文，内容中文）：
{
  "title": "周刊 | M月D日 - M月D日",
  "headline": "本周一句话总结（中文，有力，有观点）",
  "stats": {
    "report_count": 21,
    "item_count": 150,
    "picked_count": 12
  },
  "sections": {
    "AI × 商业变现": [
      {
        "title": "中文标题",
        "why": "为什么这条对创始人重要（1句）",
        "summary": "1-2句精炼摘要",
        "action": "值得动手做的下一步（1句）",
        "source": "来源报告名",
        "url": ""
      }
    ],
    "全屋定制 × AI": [...],
    "交易与宏观": [...],
    "工具与方法": [...]
  }
}

策展原则：
- 不是"本周新闻汇总"，而是"本周对你最有行动价值的信息"
- 每条必须有 why（为什么重要）+ action（能做什么）
- 同领域内按重要性排序，最重要的放第一条
- 跳过纯八卦、纯公关稿、与你关注领域无关的内容
- 标题要有信息量，不要"XX发布新版本"这种空洞标题
- 如果本周某领域确实没有值得关注的内容，该领域可以为空数组
- url 如果有就填，没有留空字符串"""

def curate(content, report_count):
    import requests as req
    week_label = f"{MONDAY.strftime('%-m/%-d')} - {SATURDAY.strftime('%-m/%-d')}"

    resp = req.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.replace("M月D日 - M月D日", week_label)},
                {"role": "user", "content": f"本周（{week_label}）日报内容如下，请策展精选：\n\n{content[:28000]}"},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = json.loads(resp.json()["choices"][0]["message"]["content"])
    data["stats"]["report_count"] = report_count
    return data

# ── HTML 生成（视界设计） ──────────────────────────────
def build_html(data):
    week_start = MONDAY.strftime("%-m/%-d")
    week_end = SATURDAY.strftime("%-m/%-d")
    week_label = f"{week_start} - {week_end}"
    gen_time = NOW.strftime("%Y-%m-%d %H:%M")

    # Section metadata for visual styling
    section_meta = {
        "AI × 商业变现": {"icon": "🤖", "color": "#2563eb", "bg": "#eff6ff", "border": "#bfdbfe"},
        "全屋定制 × AI": {"icon": "🏠", "color": "#7c3aed", "bg": "#f5f3ff", "border": "#ddd6fe"},
        "交易与宏观": {"icon": "📈", "color": "#dc2626", "bg": "#fef2f2", "border": "#fecaca"},
        "工具与方法": {"icon": "🔧", "color": "#059669", "bg": "#ecfdf5", "border": "#a7f3d0"},
    }

    sections_html = ""
    for sec_name, entries in data.get("sections", {}).items():
        if not entries:
            continue
        meta = section_meta.get(sec_name, {"icon": "📌", "color": "#6b7280", "bg": "#f9fafb", "border": "#e5e7eb"})

        cards = ""
        for i, e in enumerate(entries):
            title = e.get("title", "")
            why = e.get("why", "")
            summary = e.get("summary", "")
            action = e.get("action", "")
            source = e.get("source", "")
            url = e.get("url", "")
            title_html = f'<a href="{url}" target="_blank" rel="noopener">{title}</a>' if url else title

            cards += f"""
                <div class="card">
                    <div class="card-number">{(i+1):02d}</div>
                    <div class="card-body">
                        <h3>{title_html}</h3>
                        <div class="card-why">💡 {why}</div>
                        <p class="card-summary">{summary}</p>
                        <div class="card-action">🎯 <strong>行动：</strong>{action}</div>
                        <div class="card-meta">
                            <span class="card-source">{source}</span>
                        </div>
                    </div>
                    <div class="card-take">
                        <div class="take-label">💭 我的看法</div>
                        <div class="take-placeholder">在此写下你的判断...</div>
                    </div>
                </div>"""

        sections_html += f"""
            <section class="section-block" style="--accent: {meta['color']}; --bg: {meta['bg']}; --border: {meta['border']}">
                <div class="section-header">
                    <span class="section-icon">{meta['icon']}</span>
                    <h2>{sec_name}</h2>
                    <span class="section-count">{len(entries)} 条精选</span>
                </div>
                <div class="cards">
                    {cards}
                </div>
            </section>"""

    stats = data.get("stats", {})

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>视界 · 周刊 {week_label}</title>
<style>
    :root {{
        --page-bg: #fafaf7;
        --card-bg: #ffffff;
        --text: #1e293b;
        --text-muted: #64748b;
        --text-subtle: #94a3b8;
        --border: #e2e8f0;
        --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03);
        --shadow-hover: 0 4px 12px rgba(0,0,0,0.06);
        --radius: 12px;
        --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
        --font-mono: "SF Mono", "Fira Code", "JetBrains Mono", monospace;
    }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    body {{
        font-family: var(--font-sans);
        background: var(--page-bg);
        color: var(--text);
        line-height: 1.6;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }}

    .page {{
        max-width: 720px;
        margin: 0 auto;
        padding: 40px 24px 80px;
    }}

    /* ── Header ── */
    .masthead {{
        text-align: center;
        padding: 48px 0 40px;
        border-bottom: 1px solid var(--border);
        margin-bottom: 40px;
    }}

    .masthead .brand {{
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--text-subtle);
        margin-bottom: 12px;
    }}

    .masthead h1 {{
        font-size: 32px;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: var(--text);
        margin-bottom: 8px;
    }}

    .masthead .headline {{
        font-size: 17px;
        color: var(--text-muted);
        font-weight: 400;
        max-width: 480px;
        margin: 0 auto 16px;
        line-height: 1.5;
    }}

    .masthead .meta {{
        font-size: 13px;
        color: var(--text-subtle);
    }}

    .masthead .date-badge {{
        display: inline-block;
        background: #f1f5f9;
        border-radius: 20px;
        padding: 4px 14px;
        font-size: 12px;
        font-weight: 500;
        color: var(--text-muted);
    }}

    /* ── Stats bar ── */
    .stats-bar {{
        display: flex;
        justify-content: center;
        gap: 32px;
        margin-bottom: 48px;
        flex-wrap: wrap;
    }}

    .stat {{
        text-align: center;
    }}

    .stat-value {{
        font-size: 28px;
        font-weight: 700;
        color: var(--text);
        letter-spacing: -0.02em;
    }}

    .stat-label {{
        font-size: 12px;
        color: var(--text-muted);
        margin-top: 2px;
    }}

    /* ── Sections ── */
    .section-block {{
        margin-bottom: 48px;
    }}

    .section-header {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 20px;
        padding-bottom: 12px;
        border-bottom: 2px solid var(--border, #e2e8f0);
    }}

    .section-icon {{
        font-size: 22px;
    }}

    .section-header h2 {{
        font-size: 19px;
        font-weight: 700;
        color: var(--text);
        letter-spacing: -0.01em;
        flex: 1;
    }}

    .section-count {{
        font-size: 12px;
        color: var(--text-subtle);
        font-weight: 500;
        background: #f1f5f9;
        border-radius: 10px;
        padding: 2px 10px;
    }}

    /* ── Cards ── */
    .cards {{
        display: flex;
        flex-direction: column;
        gap: 12px;
    }}

    .card {{
        background: var(--card-bg);
        border-radius: var(--radius);
        box-shadow: var(--shadow);
        display: grid;
        grid-template-columns: 44px 1fr 200px;
        gap: 0;
        overflow: hidden;
        transition: box-shadow 0.2s;
    }}

    .card:hover {{
        box-shadow: var(--shadow-hover);
    }}

    .card-number {{
        display: flex;
        align-items: flex-start;
        justify-content: center;
        padding: 18px 0 0 0;
        font-family: var(--font-mono);
        font-size: 13px;
        font-weight: 600;
        color: var(--text-subtle);
    }}

    .card-body {{
        padding: 18px 16px;
    }}

    .card-body h3 {{
        font-size: 15px;
        font-weight: 600;
        line-height: 1.4;
        margin-bottom: 6px;
        color: var(--text);
    }}

    .card-body h3 a {{
        color: inherit;
        text-decoration: none;
        border-bottom: 1px solid transparent;
        transition: border-color 0.2s;
    }}

    .card-body h3 a:hover {{
        border-bottom-color: var(--text);
    }}

    .card-why {{
        font-size: 13px;
        color: var(--text-muted);
        margin-bottom: 4px;
        line-height: 1.5;
    }}

    .card-summary {{
        font-size: 13px;
        color: var(--text-muted);
        line-height: 1.6;
        margin-bottom: 6px;
    }}

    .card-action {{
        font-size: 12px;
        color: var(--text);
        background: var(--bg, #f8fafc);
        border-radius: 6px;
        padding: 6px 10px;
        line-height: 1.4;
    }}

    .card-meta {{
        margin-top: 8px;
    }}

    .card-source {{
        font-size: 11px;
        color: var(--text-subtle);
    }}

    .card-take {{
        padding: 18px 16px;
        border-left: 1px solid var(--border);
        background: #fafbfc;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }}

    .take-label {{
        font-size: 11px;
        font-weight: 600;
        color: var(--text-subtle);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 8px;
    }}

    .take-placeholder {{
        font-size: 12px;
        color: #cbd5e1;
        font-style: italic;
        line-height: 1.5;
    }}

    /* ── Footer ── */
    .footer {{
        text-align: center;
        padding-top: 40px;
        border-top: 1px solid var(--border);
        margin-top: 20px;
        color: var(--text-subtle);
        font-size: 12px;
    }}

    .footer a {{
        color: var(--text-muted);
        text-decoration: none;
    }}

    /* ── Mobile ── */
    @media (max-width: 640px) {{
        .page {{
            padding: 20px 16px 60px;
        }}
        .masthead {{
            padding: 28px 0 24px;
            margin-bottom: 24px;
        }}
        .masthead h1 {{
            font-size: 24px;
        }}
        .card {{
            grid-template-columns: 36px 1fr;
        }}
        .card-take {{
            display: none;
        }}
        .stats-bar {{
            gap: 20px;
            margin-bottom: 32px;
        }}
        .stat-value {{
            font-size: 22px;
        }}
    }}

    /* ── Print ── */
    @media print {{
        body {{ background: white; }}
        .page {{ max-width: 100%; padding: 20px; }}
        .card {{ box-shadow: none; break-inside: avoid; border: 1px solid #e5e7eb; }}
        .card-take {{ background: white; }}
    }}
</style>
</head>
<body>
<div class="page">

    <header class="masthead">
        <div class="brand">视界 · Weekly View</div>
        <h1>{week_label}</h1>
        <p class="headline">{data.get('headline', '')}</p>
        <span class="date-badge">{gen_time} · 自动生成</span>
    </header>

    <div class="stats-bar">
        <div class="stat">
            <div class="stat-value">{stats.get('report_count', 0)}</div>
            <div class="stat-label">本周日报</div>
        </div>
        <div class="stat">
            <div class="stat-value">{stats.get('picked_count', 0)}</div>
            <div class="stat-label">精选条目</div>
        </div>
        <div class="stat">
            <div class="stat-value">4</div>
            <div class="stat-label">关注领域</div>
        </div>
    </div>

    {sections_html}

    <footer class="footer">
        <p>由 AI Content Factory 自动策展 · 每周六上午生成</p>
        <p style="margin-top:4px">在 Obsidian 中打开同名 .md 文件可编辑「我的看法」</p>
    </footer>

</div>
</body>
</html>"""
    return html

# ── Markdown 生成（Obsidian 可编辑版） ─────────────────
def build_markdown(data):
    week_label = f"{MONDAY.strftime('%-m/%-d')} - {SATURDAY.strftime('%-m/%-d')}"
    gen_time = NOW.strftime("%Y-%m-%d %H:%M")
    stats = data.get("stats", {})

    lines = [
        "---",
        f"type: weekly-digest",
        f"week: \"{week_label}\"",
        f"date: \"{TODAY}\"",
        f"tags: [周刊, weekly, 策展, auto-generated]",
        "---",
        "",
        f"# 🔭 视界周刊 | {week_label}",
        "",
        f"> {data.get('headline', '')}",
        "",
        f"> 📊 {stats.get('report_count', 0)} 份日报 → {stats.get('picked_count', 0)} 条精选 · 生成于 {gen_time}",
        "",
        f"📄 [在浏览器中打开 HTML 版](周刊-{TODAY}.html)",
        "",
        "---",
        "",
    ]

    for sec_name, entries in data.get("sections", {}).items():
        if not entries:
            continue
        lines.append(f"## {sec_name}")
        lines.append("")
        for i, e in enumerate(entries):
            title = e.get("title", "")
            why = e.get("why", "")
            summary = e.get("summary", "")
            action = e.get("action", "")
            source = e.get("source", "")
            url = e.get("url", "")

            if url:
                lines.append(f"### {i+1}. [{title}]({url})")
            else:
                lines.append(f"### {i+1}. {title}")
            lines.append(f"> 💡 {why}")
            lines.append("")
            lines.append(summary)
            lines.append("")
            lines.append(f"- 🎯 **行动：** {action}")
            lines.append(f"- 📍 {source}")
            lines.append("")
            lines.append(f"💭 **我的看法：** _（在此写下你的判断）_")
            lines.append("")

    lines.append("---")
    repo_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "your/content-factory")
    lines.append(f"*由 [AI Content Factory]({repo_url}) 自动策展 · 每周六上午生成*")
    return "\n".join(lines)

# ── 保存 ──────────────────────────────────────────────
def save_all(html, md):
    os.makedirs(REPORT_DIR, exist_ok=True)

    html_path = os.path.join(REPORT_DIR, f"周刊-{TODAY}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ {html_path}")

    md_path = os.path.join(REPORT_DIR, f"周刊-{TODAY}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  ✅ {md_path}")

    # Also save JSON for potential future use
    json_path = os.path.join(REPORT_DIR, f"周刊-{TODAY}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False)  # data already in memory, but we save the raw week data reference
    print(f"  ✅ {json_path}")

# ── main ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🔭 P11 周报引擎 · {NOW.strftime('%Y-%m-%d %H:%M')}")
    print(f"📅 本周范围: {DATES[0]} ~ {DATES[-1]}")
    print()

    content, file_count = read_week_reports()
    if not content:
        print("❌ 本周无日报数据，跳过生成")
        sys.exit(0)

    # If we have fewer than 3 reports for the week (e.g., just 1-2 days),
    # still generate but flag it
    if file_count < 6:
        print(f"⚠️ 仅 {file_count} 份日报（正常应为 15-21 份），可能本周刚开始或日报管道中断")

    print(f"\n🧠 DeepSeek 策展中...")
    data = curate(content, file_count)

    print(f"\n🎨 生成视界 HTML...")
    html = build_html(data)

    print(f"\n📝 生成 Obsidian MD...")
    md = build_markdown(data)

    print(f"\n💾 保存...")
    save_all(html, md)

    # Summary
    total_picked = sum(len(v) for v in data.get("sections", {}).values())
    print(f"\n🎉 周报生成完成 — {total_picked} 条精选，覆盖 {len([k for k,v in data.get('sections',{}).items() if v])} 个领域")
