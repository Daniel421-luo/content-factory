# 🏭 AI 情报内容工厂

> 全自动采集 → DeepSeek 炼油 → 多渠道分发。一人运营媒体矩阵的基础设施。

## 架构

```
信息源（AIHOT/RSS/抖音）→ GitHub Actions (Cron) → DeepSeek API → 结构化笔记 → Git Repo
                                                                         ↓
                                                            本地 Mac git pull → Obsidian
```

## 三条工作流

| 工作流 | 触发方式 | 频率 | 输出 |
|--------|---------|:--:|------|
| 📰 日报生成 | Cron 自动 | 每天2次 | AI日报 + 财经日报 |
| 🎬 抖音提炼 | GitHub Issue | 按需 | 提炼笔记 + 索引更新 |
| ✍️ 每周改写 | Cron 周六 | 每周1次 | 公众号 + 小红书初稿 |

## 使用方式

### 贴抖音链接（手机操作）
1. 打开 GitHub App → content-factory → Issues → New Issue
2. 标题写视频主题，正文粘贴抖音链接
3. 提交 → 5分钟后刷新，提炼笔记已入库

### 查看日报
直接浏览 `日报/` 目录

### 审核发布
1. Mac: `git pull` → 审核 `内容发布/公众号/queue/`
2. 修改后复制到公众号后台发布
3. 移动到 `published/` → `git push`

## 目录结构

```
content-factory/
├── .github/workflows/    # 3条自动化工作流
├── .github/scripts/      # Python 脚本
├── 日报/                  # AI日报 + 财经日报
├── 抖音素材库/
│   ├── raw-links/        # 待处理链接池
│   ├── 已提炼/            # 按类别归档
│   └── 00-索引.md         # 自动维护的索引
├── 内容发布/
│   ├── 公众号/queue/      # AI生成 → 待审核
│   ├── 公众号/published/  # 已发布归档
│   └── 小红书/queue/      # AI生成 → 待审核
└── agent-configs/        # Prompt + 模板
```

## 设置

1. Fork/Clone 此仓库
2. GitHub → Settings → Secrets → 添加 `DEEPSEEK_API_KEY`
3. 启用 Actions (Settings → Actions → Allow)

## 成本

- GitHub Actions: ¥0 (2000min/月免费)
- DeepSeek API: <$1/月
- 总计: <¥10/月
