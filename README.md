# 🏭 AI Content Factory

> 全自动多源新闻采集 → AI 合成 → Obsidian 入库 → 手机推送

定时从 20+ 国际 RSS/Atom 源采集新闻，用 **DeepSeek** 跨源合成三份中文日报，自动推送到你的 Obsidian Vault 和 iPhone。

## ✨ 每天自动产出

| 时间 (UTC+8) | 日报 | 来源 | 特性 |
|:--:|------|------|------|
| 08:00 | 🤖 **AI 日报** | TechCrunch / MIT Tech Review / VentureBeat / Wired / Ars Technica / ZDNet / The Verge / AIHOT (168 中文源) | AI/科技行业动态 |
| 16:00 | 📈 **美股简报** | CNBC / MarketWatch / WSJ / Reuters / BBC Business / Seeking Alpha / CBS | 含投资信号矩阵 |
| 20:00 | 🌍 **全球简报** | NPR / ABC / BBC World / Fox News / Guardian / CNBC | 含投资信号矩阵 |

## 🚀 快速开始

### 1. Fork 这个仓库

点击右上角 Fork → 创建你自己的副本。

### 2. 配置 Secrets

在 Settings → Secrets and variables → Actions → **New repository secret** 中添加：

| Secret | 必需 | 说明 |
|--------|:----:|------|
| `DEEPSEEK_API_KEY` | ✅ 必需 | [DeepSeek API Key](https://platform.deepseek.com/api_keys)（充值 ¥10 可用数月） |
| `BARK_KEY` | 可选 | [Bark](https://apps.apple.com/app/bark-customed-notifications/id1403753865) iOS 推送 Key |
| `FEISHU_APP_ID` | 可选 | 飞书应用 App ID（需配合下面两个） |
| `FEISHU_APP_SECRET` | 可选 | 飞书应用密钥 |
| `FEISHU_OPEN_ID` | 可选 | 你的飞书用户 Open ID |

> 💡 至少配置 `DEEPSEEK_API_KEY` 就能跑。Bark 和飞书推送是锦上添花。

### 3. 启用 GitHub Actions

1. 进入仓库 Actions 标签页
2. 点击 "I understand my workflows, go ahead and enable them"
3. 手动触发一次测试：

```
Actions → 📰 三报自动生成 → Run workflow → 选一个类型运行
```

### 4. (可选) 同步到 Obsidian

如果你用 Obsidian 管理知识库，可以将生成的日报自动拉取到本地：

```bash
# 1. Clone 你的 fork 到本地
git clone https://github.com/YOUR_USERNAME/content-factory.git

# 2. 设置环境变量（写入 ~/.zshrc 或 ~/.bash_profile）
export VAULT_PATH="$HOME/path/to/your-obsidian-vault/03-拓展项目"

# 3. 运行同步
bash sync-to-vault.sh
```

配合 macOS LaunchAgent 或 cron 定时 `git pull && bash sync-to-vault.sh`，日报就自动出现在 Obsidian 了。

## 🛠 自定义你的日报

### 换个 AI 模型

默认用 `deepseek-chat`（便宜好用）。想换的话编辑 `.github/scripts/daily-report.py`：

```python
"model": "deepseek-chat",  # 改成 "gpt-4o-mini" 或其他
```

同时需要把 `DEEPSEEK_API_KEY` secret 换成对应服务商的 Key，并修改 API endpoint。

### 增删 RSS 源

编辑 `.github/scripts/daily-report.py` 第 40-263 行的 `SOURCES` 字典：

```python
"ai": {
    "feeds": [
        ("https://your-feed-url/rss", "Source Name", "rss"),  # RSS
        ("https://your-atom-feed",     "Atom Source",  "atom"),  # Atom
    ],
    ...
}
```

### 修改推送渠道

- **Bark** (iOS): 脚本第 89-104 行，GitHub Actions 里自动推送
- **飞书**: 脚本第 106-136 行，推送到飞书消息
- **其他渠道**: 在 workflow 中加一个 step，用 curl/webhook 对接钉钉/微信/Telegram

## 🧱 架构

```
GitHub Actions (美国机房, 无 GFW 限制)
  │
  ├── 18 个 RSS/Atom 源 + AIHOT API
  ├── DeepSeek API 跨源合成
  │
  ▼ JSON → Markdown → Git Push
  │
你的 Mac
  ├── git pull → Obsidian Vault
  ├── Bark → iPhone 推送
  └── 飞书 → 消息通知
```

## 📂 文件结构

```
content-factory/
├── .github/
│   ├── workflows/daily-report.yml    # GitHub Actions 调度
│   ├── workflows/douyin-process.yml  # 抖音素材提炼（辅助）
│   └── scripts/daily-report.py       # 核心引擎
├── agent-configs/                    # Claude Code 智能体配置
├── 日报/                             # 生成的三份日报（自动提交）
├── sync-to-vault.sh                  # 同步到 Obsidian 脚本
└── README.md
```

## ❓ FAQ

**Q: 为什么用 GitHub Actions 而不是本地跑？**
A: 美国机房能访问 BBC、Reuters 等被 GFW 污染的源。而且不用 24h 开机。

**Q: 每月成本多少？**
A: DeepSeek API 约 ¥2-5/月（每天 3 次调用）。GitHub Actions 免费额度完全够用。

**Q: 能加中文源吗？**
A: AI 日报已经集成了 AIHOT（168 个中文 AI 源）。加其他中文 RSS 只需在 `SOURCES` 里加一行。

**Q: 怎么确保 AI 不编造假新闻？**
A: 系统内置反幻觉规则：要求 AI 必须引用原文 URL、不编造数字、不确定的信息直接跳过。每个 section 有去重机制防止同一事件被多次报道。

## 📄 License

MIT — 随意 fork、修改、商用。保留原作者署名即可。

---

*Created by [Daniel Luo](https://github.com/Daniel421-luo) · Powered by DeepSeek & GitHub Actions*
