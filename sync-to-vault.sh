#!/bin/bash
# Sync Content Factory output to your Obsidian Vault.
#
# SETUP: Set VAULT_PATH to your Obsidian vault's content-factory directory:
#   export VAULT_PATH="$HOME/path/to/your-vault/03-拓展项目"
#
# Or for iCloud users (macOS default):
#   export VAULT_PATH="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault/03-拓展项目"
#
# Usage: bash sync-to-vault.sh

set -euo pipefail

VAULT_PATH="${VAULT_PATH:-}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$VAULT_PATH" ]; then
  echo "❌ VAULT_PATH is not set."
  echo ""
  echo "   Set it to your Obsidian vault's 03-拓展项目 directory:"
  echo ""
  echo "   export VAULT_PATH=\"\$HOME/path/to/your-vault/03-拓展项目\""
  echo ""
  echo "   For iCloud vaults (macOS):"
  echo "   export VAULT_PATH=\"\$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault/03-拓展项目\""
  exit 1
fi

echo "🔄 同步内容工厂 → Obsidian Vault..."

# 日报
mkdir -p "$VAULT_PATH/日报"
cp -r "$REPO_DIR/日报/"* "$VAULT_PATH/日报/" 2>/dev/null || true
echo "  ✅ 日报"

# 抖音素材库 (只同步已提炼内容，不覆盖本地管理的索引/收件箱)
mkdir -p "$VAULT_PATH/抖音素材库"
if [ -d "$REPO_DIR/抖音素材库/已提炼" ]; then
  for d in "$REPO_DIR/抖音素材库/已提炼"/*/; do
    cat_name=$(basename "$d")
    mkdir -p "$VAULT_PATH/抖音素材库/已提炼/$cat_name"
    cp -r "$d"* "$VAULT_PATH/抖音素材库/已提炼/$cat_name/" 2>/dev/null || true
  done
fi
echo "  ✅ 抖音素材库（已提炼内容，跳过索引/收件箱）"

# 内容发布
mkdir -p "$VAULT_PATH/内容发布"
cp -r "$REPO_DIR/内容发布/"* "$VAULT_PATH/内容发布/" 2>/dev/null || true
echo "  ✅ 内容发布"

echo "🎉 同步完成！"
