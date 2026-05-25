#!/bin/bash
# 将 content-factory repo 的内容同步到 Obsidian iCloud Vault
# 用法：在 Mac 上运行 bash sync-to-vault.sh

VAULT_PATH="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault/03-拓展项目"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🔄 同步内容工厂 → Obsidian Vault..."

# 日报
mkdir -p "$VAULT_PATH/日报"
cp -r "$REPO_DIR/日报/"* "$VAULT_PATH/日报/" 2>/dev/null
echo "  ✅ 日报"

# 抖音素材库
mkdir -p "$VAULT_PATH/抖音素材库"
cp -r "$REPO_DIR/抖音素材库/"* "$VAULT_PATH/抖音素材库/" 2>/dev/null
echo "  ✅ 抖音素材库"

# 内容发布
mkdir -p "$VAULT_PATH/内容发布"
cp -r "$REPO_DIR/内容发布/"* "$VAULT_PATH/内容发布/" 2>/dev/null
echo "  ✅ 内容发布"

echo "🎉 同步完成！"
echo "   位置: $VAULT_PATH/日报/"
echo "   位置: $VAULT_PATH/抖音素材库/"
echo "   位置: $VAULT_PATH/内容发布/"
