# 🏭 AI 情报内容工厂 (P11 v4 — Unified Pipeline)

> **状态**: ✅ 统一管道已建成 (2026-05-31)
> 全自动采集 → DeepSeek 炼油 → Obsidian 入库 → Bark/飞书推送到手机

## 三条日报

| 时间 | 报告 | 来源 | 特性 |
|------|------|------|------|
| 08:00 BJT | 🤖 AI 日报 | 英文科技 RSS × 7 + AIHOT 中文 168 信源 | AI/科技新闻 |
| 16:00 BJT | 📈 美股简报 | CNBC/WSJ/MarketWatch/Seeking Alpha/CBS | 📊 含投资信号矩阵 |
| 20:00 BJT | 🌍 全球简报 | NPR/ABC/BBC/Fox/Guardian/CNBC | 📊 含投资信号矩阵 |

## 已合并的旧管道

- ~~Intel Pipeline (Python, local)~~ → 已归档至 `content-factory/.github/scripts/`
- ~~News Aggregator (Claude Code manual)~~ → 投资信号矩阵已集成到 GHA 日报
- ~~AIHOT standalone script~~ → AIHOT API 已集成到 AI 日报 RSS 采集

## 架构

```
GitHub Actions (US 机房, 突破被墙)
  │
  ├── 7个 RSS/Atom 源 (TechCrunch, MIT Tech Review, VentureBeat, etc.)
  ├── AIHOT API (中文 AI 168 信源, 卡兹克维护)
  ├── 9个财经/国际源 (CNBC, WSJ, MarketWatch, BBC, NPR, etc.)
  │
  ▼ DeepSeek API 合成 → JSON → Markdown + 投资信号矩阵
  │
  ▼ Git Push → GitHub Repo
  │
Mac (LaunchAgent 08:15 + 20:15)
  │
  ├── git pull → Obsidian Vault (日报/ 目录)
  ├── Bark → iPhone 推送通知
  └── 飞书 → 聊天消息通知
  │
每晚 21:00：
  └── send-daily-digest.py → 三报汇总 → 飞书每日卡片
```

## 新增功能 (v4)

- 📊 **投资信号矩阵**: 美股简报 + 全球简报含信号表格（方向/资产/置信度/时间框架）
- 📱 **手机推送**: 日报生成后自动通过 Bark 推送 iPhone + 飞书消息通知
- 🇨🇳 **AIHOT 中文源**: AI 日报整合卡兹克 168 信源中文 AI 新闻
- 🩺 **Feed 健康监控**: 每个源的抓取状态自动日志记录

## 推送设置

1. **Bark** (iOS): App Store 安装 → 复制 Key → 存入 `~/.config/bark/key`
2. **飞书**: 已配置 larksuite/cli 后自动工作
3. **每日汇总**: `python3 ~/bin/send-daily-digest.py --send`
