#!/bin/bash
# ダブルクリックでアプリを起動します。
cd "$(dirname "$0")"

clear
echo "=============================================="
echo "  🎵 ローカル音楽生成"
echo "=============================================="
echo ""

PYTHON="./.venv/bin/python"

# 初回はセットアップを促す
if [ ! -x "$PYTHON" ]; then
  echo "初回セットアップを行います。少し時間がかかります…"
  echo ""
  bash scripts/setup.sh || {
    echo ""
    echo "セットアップに失敗しました。上のメッセージを確認してください。"
    echo "このウィンドウは閉じて大丈夫です。"
    read -r -p "Enter キーで終了します…"
    exit 1
  }
fi

# モデルが無い場合は案内（勝手に大容量ダウンロードは始めない）
if ! "$PYTHON" -c "
import sys; sys.path.insert(0,'.')
from backend.config import load_settings
from backend.models import registry
s=load_settings()
sys.exit(0 if registry.is_installed(s.models, registry.MODELS[registry.DEFAULT_MODEL_KEY]) else 1)
" 2>/dev/null; then
  echo "⚠️  音楽をつくるための「モデル」がまだありません（約9GB）。"
  echo ""
  echo "   アプリの「📦 モデル管理」タブからダウンロードできます。"
  echo "   （ここでダウンロードすることもできます）"
  echo ""
  read -r -p "いま先にダウンロードしますか？ [y/N]: " ans
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    "$PYTHON" -m backend.cli download
  fi
  echo ""
fi

echo "アプリを起動しています…"
echo "ブラウザが自動で開きます。開かない場合は下のURLをブラウザに貼ってください。"
echo ""
echo "    http://127.0.0.1:7860"
echo ""
echo "終了するには、このウィンドウで Control + C を押してください。"
echo "=============================================="
echo ""

exec "$PYTHON" -m backend.cli ui
