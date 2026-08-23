"""実機生成テスト。コードだけで完成扱いにしないための検証。

    .venv/bin/python scripts/smoke_test.py            # 英語インスト 30秒
    .venv/bin/python scripts/smoke_test.py --japanese # 日本語歌唱 30秒
    .venv/bin/python scripts/smoke_test.py --offline  # オフライン再現テスト
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.memory import guard  # noqa: E402
from backend.prompt.builder import PromptInput  # noqa: E402
from backend.service import MusicService  # noqa: E402

EN_CASE = PromptInput(
    description="A calm ambient piano piece with soft strings, slow tempo, cinematic atmosphere.",
    lyrics="",
    vocal="インストゥルメンタル",
    genre="Ambient",
    moods=["静か", "幻想的"],
    tempo="Slow",
    duration_sec=30,
    title="smoke-instrumental",
)

JP_CASE = PromptInput(
    description=(
        "夏の夕方を感じさせる少し切ないピアノポップ。"
        "女性ボーカル、静かなイントロから徐々に盛り上がる。"
    ),
    lyrics=(
        "風がとおる 白い午後\n"
        "遠くで揺れる夏の音\n"
        "まだ名前のない気持ちを\n"
        "そっと空へ放した"
    ),
    vocal="女性",
    genre="J-Pop",
    moods=["切ない", "ノスタルジック"],
    tempo="Slow",
    duration_sec=30,
    title="smoke-japanese",
)


def probe(wav: Path) -> dict:
    """ffprobe で WAV が正常か確認する。"""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration,size:stream=codec_name,sample_rate,channels",
                "-of", "json", str(wav),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--japanese", action="store_true", help="日本語歌唱テスト")
    ap.add_argument("--offline", action="store_true", help="オフライン強制")
    ap.add_argument("--preset", default="Low Memory")
    ap.add_argument("--duration", type=int, default=30)
    args = ap.parse_args()

    case = JP_CASE if args.japanese else EN_CASE
    case.duration_sec = args.duration
    label = "日本語歌唱" if args.japanese else "英語インスト"

    before = guard.get_status()
    print(f"=== Smoke Test: {label} / {args.preset} / {args.duration}s ===")
    print(f"開始前  空きメモリ {before.available_gb}GB / swap {before.swap_used_gb}GB")
    print(f"オフライン: {args.offline}")

    service = MusicService()
    if not service.model_ready(args.preset):
        print("❌ モデルが未導入です。")
        return 1

    started = time.perf_counter()
    peak_swap = before.swap_used_gb
    min_avail = before.available_gb
    final = None

    for out in service.generate(case, preset=args.preset, seed=42, offline=args.offline):
        now = guard.get_status()
        peak_swap = max(peak_swap, now.swap_used_gb)
        min_avail = min(min_avail, now.available_gb)
        print(f"  [{out.ratio*100:5.1f}%] {out.stage}")
        if not out.ok:
            print(f"❌ 失敗: {out.message}")
            if out.detail:
                print("--- detail ---")
                print(out.detail[-2000:])
            return 1
        final = out

    elapsed = time.perf_counter() - started
    if final is None or final.wav_path is None:
        print("❌ 出力が得られませんでした。")
        return 1

    wav = final.wav_path
    info = probe(wav)
    after = guard.get_status()
    meta = final.metadata or {}

    print("\n--- 結果 ---")
    print(f"WAV: {wav}")
    print(f"サイズ: {wav.stat().st_size/1024/1024:.2f} MB")
    print(f"ffprobe: {json.dumps(info, ensure_ascii=False)}")
    print(f"生成時間: {elapsed:.1f} 秒（音源 {meta.get('generated_duration_sec')} 秒）")
    print(f"実時間比: {elapsed / max(meta.get('generated_duration_sec') or 1, 1):.1f}x")
    print(f"メモリ最小空き: {min_avail}GB / swap {before.swap_used_gb}→{after.swap_used_gb}GB (peak {peak_swap})")
    print(f"モデル: {meta.get('model')} ({meta.get('quantization')}) steps={meta.get('steps')}")

    streams = info.get("streams") or []
    duration = float((info.get("format") or {}).get("duration") or 0)
    if not streams or duration < 1.0:
        print("❌ WAV が正常ではありません。")
        return 1

    print("\n✅ SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
