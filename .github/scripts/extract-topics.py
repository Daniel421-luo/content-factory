#!/usr/bin/env python3
"""Extract topics from Content Factory daily report for push notifications.

Usage:
  python extract-topics.py <report.md> <mode>
  mode: bark   → compact for push notification body
        feishu → full topic list for IM message

Also reads TIME_CONTEXT env var for an optional time-context header line.
"""

import os, sys, re

filepath = sys.argv[1]
mode = sys.argv[2]
time_context = os.environ.get("TIME_CONTEXT", "")

with open(filepath) as f:
    content = f.read()

lines = content.split("\n")

# Extract frontmatter date
fm_date = ""
for line in lines:
    if line.startswith("date:"):
        fm_date = line.split('"')[1] if '"' in line else line.split(":")[1].strip()
        break

# Extract headlines: only > lines before the first ## section
headlines = []
for line in lines:
    if line.startswith("## "):
        break
    if line.startswith("> ") and not any(line.startswith(f"> {c}") for c in "📡⏰📍"):
        headlines.append(line[2:].strip())

# Extract sections and their articles
sections = []
current_section = None
for line in lines:
    if line.startswith("## "):
        if current_section:
            sections.append(current_section)
        current_section = {"name": line[3:].strip(), "articles": []}
    elif line.startswith("### [") and current_section:
        m = re.match(r"### \[(.+?)\]\(.+?\)", line)
        if m:
            title = m.group(1)
            if len(title) > 50:
                title = title[:48] + "…"
            current_section["articles"].append(title)

if current_section:
    sections.append(current_section)

# ── Time context line ──
tc_line = time_context

if mode == "bark":
    parts = []
    if tc_line:
        parts.append(tc_line)
    if headlines:
        parts.append(" › ".join(headlines[:2]))
    section_parts = []
    for s in sections:
        section_parts.append(f"{s['name']}({len(s['articles'])})")
    if section_parts:
        parts.append(" · ".join(section_parts))
    print("\n".join(parts))

elif mode == "feishu":
    output = []
    if tc_line:
        output.append(tc_line)
        output.append("")
    if headlines:
        for h in headlines[:2]:
            output.append(f"> {h}")
        output.append("")
    for s in sections:
        output.append(f"【{s['name']}】")
        for a in s["articles"]:
            output.append(f"  • {a}")
        output.append("")
    print("\n".join(output))

else:
    print(f"Unknown mode: {mode}", file=sys.stderr)
    sys.exit(1)
