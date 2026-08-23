#!/bin/bash
# 初回セットアップ。Python 環境を用意し、必要なライブラリを入れる。
# sudo は使わない。既存の Python 環境も変更しない。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=============================================="
echo " ローカル音楽生成 セットアップ"
echo "=============================================="
echo ""

# --- Apple Silicon 確認 ---
if [ "$(uname -m)" != "arm64" ]; then
  echo "❌ このアプリは Apple Silicon (M1/M2/M3/M4) 専用です。"
  exit 1
fi
echo "✅ Apple Silicon: $(sysctl -n machdep.cpu.brand_string)"

# --- メモリ・ディスク ---
RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
echo "✅ メモリ: ${RAM_GB} GB"
echo "✅ ディスク空き: $(df -h . | tail -1 | awk '{print $4}')"

# --- uv ---
if ! command -v uv >/dev/null 2>&1; then
  echo ""
  echo "⚠️  uv（Python環境ツール）が見つかりません。"
  echo "   次のコマンドでインストールしてから、もう一度実行してください:"
  echo ""
  echo "     curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo ""
  exit 1
fi
echo "✅ uv: $(uv --version)"

# --- ffmpeg（任意） ---
if command -v ffmpeg >/dev/null 2>&1; then
  echo "✅ ffmpeg: あり"
else
  echo "・ ffmpeg: なし（WAV生成には不要です。必要なら brew install ffmpeg）"
fi

# --- Python 環境 ---
echo ""
echo "Python 環境を用意しています（数分かかることがあります）…"
uv venv --python 3.12 >/dev/null 2>&1 || true
uv pip install -q \
  "mlx>=0.32.0" \
  "mlx-audio @ git+https://github.com/Blaizzy/mlx-audio.git@main" \
  "huggingface_hub[hf_xet]" \
  soundfile \
  "gradio>=6.0"

echo "✅ ライブラリの準備ができました。"
echo ""

# --- 動作確認 ---
"$PROJECT_ROOT/.venv/bin/python" -m backend.cli doctor || true

echo ""
echo "=============================================="
echo " 次の手順"
echo "=============================================="
echo ""
echo " 1. モデル（約9GB）を取得します:"
echo "      ./bin/local-music download"
echo ""
echo " 2. アプリを起動します:"
echo "      start.command をダブルクリック"
echo ""
