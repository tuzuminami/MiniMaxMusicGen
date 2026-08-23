"""モデルのダウンロード。

Hugging Face のリポジトリ全体を無条件に clone せず、生成に必要なファイルだけ取る。
通信が発生するのはこの処理だけ（生成時は一切通信しない）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from .registry import ModelSpec, disk_free_gb, local_path

# 生成に必要なものだけ。README や画像などは取得しない。
ALLOW_PATTERNS = [
    "*.json",
    "*.safetensors",
    "tokenizer/*",
    "scheduler/*",
    "LICENSE",
]


def download_plan(models_dir: Path, spec: ModelSpec) -> dict:
    """ダウンロード前にユーザーへ提示する情報。"""
    return {
        "model": spec.label,
        "repo_id": spec.repo_id,
        "quantization": spec.quantization,
        "download_gb": spec.download_gb,
        "required_free_disk_gb": round(spec.download_gb * 1.15, 1),
        "destination": str(local_path(models_dir, spec)),
        "disk_free_gb": disk_free_gb(models_dir),
    }


def download(models_dir: Path, spec: ModelSpec) -> Iterator[str]:
    """モデルを取得し、進捗メッセージを yield する。"""
    plan = download_plan(models_dir, spec)
    if plan["disk_free_gb"] < plan["required_free_disk_gb"]:
        yield (
            f"❌ ディスクの空きが足りません。\n"
            f"必要: {plan['required_free_disk_gb']}GB / 空き: {plan['disk_free_gb']}GB"
        )
        return

    dest = Path(plan["destination"])
    yield (
        f"ダウンロードを開始します。\n"
        f"　モデル: {spec.label}\n"
        f"　量子化: {spec.quantization}\n"
        f"　サイズ: 約 {spec.download_gb} GB\n"
        f"　保存先: {dest}\n\n"
        f"回線速度によっては数十分かかります。このタブを開いたままお待ちください。"
    )

    # ダウンロード時のみ通信を許可する（オフライン設定を一時的に解除）。
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.pop("HF_HUB_OFFLINE", None)

    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=spec.repo_id,
            local_dir=str(dest),
            allow_patterns=ALLOW_PATTERNS,
            max_workers=4,
        )
    except Exception as exc:  # noqa: BLE001
        yield (
            "❌ ダウンロードに失敗しました。\n"
            "インターネット接続を確認して、もう一度お試しください。\n\n"
            f"技術的詳細: {type(exc).__name__}: {str(exc)[:300]}"
        )
        return

    yield f"✅ ダウンロードが完了しました。\n保存先: {dest}"


def verify(models_dir: Path, spec: ModelSpec) -> str:
    """ローカルのファイルが揃っているか確認する。"""
    d = local_path(models_dir, spec)
    if not d.is_dir():
        return "❌ モデルがまだダウンロードされていません。"

    missing = []
    if not (d / "config.json").exists():
        missing.append("config.json")
    shards = sorted(d.glob("*.safetensors"))
    if not shards:
        missing.append("*.safetensors")

    index = d / "model.safetensors.index.json"
    if index.exists():
        import json

        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            needed = {Path(v).name for v in data.get("weight_map", {}).values()}
            have = {p.name for p in shards}
            for n in sorted(needed - have):
                missing.append(n)
        except (json.JSONDecodeError, OSError):
            pass

    if missing:
        return "❌ 次のファイルが不足しています:\n　" + "\n　".join(missing) + "\n再ダウンロードしてください。"

    total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024**3
    return f"✅ 正常です。ファイル {len(shards)} 個 / 合計 {total:.2f} GB\n{d}"
