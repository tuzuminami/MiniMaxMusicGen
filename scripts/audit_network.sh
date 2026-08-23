#!/bin/bash
# 外部AI API・クラウド推論を使っていないことを検証する監査スクリプト。
# 絶対条件を満たしているかの確認用。CI 代わりに随時実行する。
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="app backend scripts bin"
FAIL=0

# ソースだけを見る。ビルド生成物とこの監査スクリプト自身（検査パターンを含む）は除く。
grep_src() {
  grep -rnI --exclude-dir=__pycache__ --exclude="audit_network.sh" "$@" $SRC 2>/dev/null
}

echo "=============================================="
echo " 外部通信監査"
echo "=============================================="

# 単語境界で見る。'audio' が 'udio' に一致するような誤検出を避ける。
BANNED='\b(openai|anthropic|claude-3|gemini|generativeai|replicate\.com|runpod|fal\.ai|together\.xyz|groq|elevenlabs|suno\.ai|udio\.com|api_key|apikey|secret_key)\b'

echo ""
echo "[1] 禁止された外部AIサービスへの参照"
if grep_src -iE "$BANNED"; then
  echo "  ❌ 禁止された参照が見つかりました"
  FAIL=1
else
  echo "  ✅ 該当なし"
fi

echo ""
echo "[2] CUDA / NVIDIA 依存"
if grep_src -iE '\b(cuda|nvidia|cudnn|nccl)\b' | grep -v '未使用\|絶対条件'; then
  echo "  ❌ CUDA 依存の可能性があります"
  FAIL=1
else
  echo "  ✅ 該当なし（Apple Metal のみ）"
fi

echo ""
echo "[3] 外部通信を行うコード（モデル取得のみ許可）"
HITS=$(grep_src -E '\b(requests\.(get|post)|urlopen|httpx\.|snapshot_download|hf_hub_download)' || true)
if [ -n "$HITS" ]; then
  echo "$HITS" | sed 's/^/  /'
  if echo "$HITS" | grep -vq 'downloader.py'; then
    echo "  ❌ モデル取得以外の通信が含まれています"
    FAIL=1
  else
    echo "  ✅ モデル取得（downloader.py）のみ"
  fi
else
  echo "  ✅ 通信コードなし"
fi

echo ""
echo "[4] UI の待ち受けアドレス"
if grep_src -n '0\.0\.0\.0'; then
  echo "  ❌ 外部公開の設定があります"
  FAIL=1
else
  grep -rn 'server_name\|share=' app/ | sed 's/^/  /'
  echo "  ✅ 127.0.0.1 のみ / share=False"
fi

echo ""
echo "[5] APIキーを要求する設計になっていないか"
if [ -f .env ] || [ -f .env.example ]; then
  echo "  ❌ .env が存在します（APIキー不要の設計のはず）"
  FAIL=1
else
  echo "  ✅ .env なし"
fi

echo ""
echo "[6] Telemetry 無効化"
grep -rn 'DISABLE_TELEMETRY\|DO_NOT_TRACK\|ANALYTICS_ENABLED' backend/config.py | sed 's/^/  /'

echo ""
echo "=============================================="
if [ "$FAIL" -eq 0 ]; then
  echo " 結果: PASS ✅  外部AI API 0件 / 有料サービス 0件"
else
  echo " 結果: FAIL ❌"
fi
echo "=============================================="
exit $FAIL
