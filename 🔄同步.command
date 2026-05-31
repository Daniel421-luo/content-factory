#!/bin/bash
cd "$(dirname "$0")"
echo "🔄 拉取最新内容..."
git pull origin main 2>&1
echo ""
echo "✅ 同步完成。刷新 Obsidian 即可看到最新内容。"
read -p "按回车关闭..."
