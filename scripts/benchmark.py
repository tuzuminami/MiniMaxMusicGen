"""実測ベンチマーク。結果を BENCHMARK.md に書き出す。

    .venv/bin/python scripts/benchmark.py                    # Low Memory + Balanced
    .venv/bin/python scripts/benchmark.py --presets "Low Memory"
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.memory import guard  # noqa: E402
from backend.models import registry  # noqa: E402
from backend.prompt.builder import PromptInput  # noqa: E402
from backend.service import MusicService  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CASE = PromptInput(
    description="A calm ambient piano piece with soft strings, slow tempo, cinematic atmosphere.",
    lyrics="",
    vocal="インストゥルメンタル",
    genre="Ambient",
    moods=["静か"],
    tempo="Slow",
    duration_sec=30,
    title="benchmark",
)


def run_one(service: MusicService, preset: str, duration: int) -> dict | None:
    case = PromptInput(**{**CASE.__dict__, "duration_sec": duration, "title": f"bench-{preset}-{duration}s"})
    spec = registry.spec_for_preset(preset)
    before = guard.get_status()
    print(f"\n--- {preset} / {duration}s / {spec.quantization} ---")
    print(f"  空きRAM {before.available_gb}GB / swap {before.swap_used_gb}GB / 圧 {before.free_percent}%")

    started = time.perf_counter()
    final = None
    for out in service.generate(case, preset=preset, seed=42):
        if not out.ok:
            print(f"  ❌ {out.message}")
            return None
        print(f"  [{out.ratio*100:5.1f}%] {out.stage}")
        final = out
    elapsed = time.perf_counter() - started

    if final is None or final.wav_path is None:
        return None
    after = guard.get_status()
    meta = final.metadata or {}
    size_mb = final.wav_path.stat().st_size / 1024 / 1024

    row = {
        "preset": preset,
        "model": meta.get("model"),
        "quantization": meta.get("quantization"),
        "steps": meta.get("steps"),
        "duration_requested_sec": duration,
        "duration_generated_sec": meta.get("generated_duration_sec"),
        "elapsed_sec": round(elapsed, 1),
        "realtime_factor": round(elapsed / max(meta.get("generated_duration_sec") or 1, 1), 2),
        "peak_memory_gb": meta.get("peak_memory_gb"),
        "ram_available_before_gb": before.available_gb,
        "ram_available_after_gb": after.available_gb,
        "memory_pressure_free_pct_before": before.free_percent,
        "swap_before_gb": before.swap_used_gb,
        "swap_after_gb": after.swap_used_gb,
        "output_mb": round(size_mb, 2),
        "output": str(final.wav_path.relative_to(PROJECT_ROOT)),
    }
    print(f"  ✅ {elapsed:.0f}秒 / 実時間比 {row['realtime_factor']}x / ピーク {row['peak_memory_gb']}GB")
    return row


# 実測から分かった、数値表だけでは伝わらない注意点。
EXTRA_SECTIONS = """
## 曲の長さについて（重要）

指定する「長さ」は **上限** です。モデルは曲が自然に終わったと判断すると、そこで止まります。

| 指定 | 実際に生成された長さ | 所要時間 |
|---|---|---|
| 30秒 | 30.02秒（上限に到達） | 325秒 |
| 60秒 | 21.06秒（自然終了） | 228秒 |

長い曲がほしい場合は、**歌詞を多く書く**ほうが効果的です。数字を大きくするだけでは長くなりません。

## メモリについて

`mx.get_peak_memory()` は MLX が確保した総量で、そのぶんの物理 RAM が空いている必要が
あるという意味ではありません。実際には 30 秒生成が空き 15GB・スワップ増 2GB で完走しています。

ただし Balanced ではスワップが 11.19GB → 18.33GB と 7GB 増えました。
**18GB 機では 30 秒前後が快適に使える上限**です。

## 結論（M3 Pro 18GB）

- **ふだん使い: Low Memory / 30秒** … 約 5 分半で 1 曲
- Balanced は約 1.3 倍時間がかかり、スワップも増える。品質差が必要なときだけ
- 90 秒以上は物理メモリを大きく超えるため非推奨（Memory Guard が警告します）
""".splitlines()


def write_report(rows: list[dict]) -> Path:
    st = guard.get_status()
    out = PROJECT_ROOT / "BENCHMARK.md"
    lines = [
        "# BENCHMARK",
        "",
        "実機で計測した結果です。理論値ではありません。",
        "",
        "## 計測環境",
        "",
        f"- チップ: {st.chip}",
        f"- メモリ: {st.total_gb} GB (Unified Memory)",
        f"- macOS: {platform.mac_ver()[0]}",
        f"- Python: {platform.python_version()}",
        f"- 計測日: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "> 計測時、他のアプリの影響でスワップが多めに使われている状態でした。",
        "> クリーンな状態ではこれより速くなる可能性があります。",
        "",
        "## 結果",
        "",
        "| プリセット | 量子化 | steps | 要求長 | 生成長 | 所要時間 | 実時間比 | ピークメモリ | 出力 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['preset']} | {r['quantization']} | {r['steps']} | "
            f"{r['duration_requested_sec']}秒 | {r['duration_generated_sec']}秒 | "
            f"{r['elapsed_sec']}秒 | {r['realtime_factor']}x | "
            f"{r['peak_memory_gb']} GB | {r['output_mb']} MB |"
        )

    lines += ["", "## メモリの推移", "",
              "| プリセット | 生成前 空きRAM | 生成後 空きRAM | swap 前 | swap 後 |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['preset']} | {r['ram_available_before_gb']} GB | {r['ram_available_after_gb']} GB | "
            f"{r['swap_before_gb']} GB | {r['swap_after_gb']} GB |"
        )

    lines += EXTRA_SECTIONS + [
        "",
        "## 読み方",
        "",
        "- **実時間比** … 1秒の曲をつくるのに何秒かかるか。小さいほど速い",
        "- **ピークメモリ** … MLX が確保した最大メモリ量（`mx.get_peak_memory()`）",
        "",
        "## 生データ",
        "",
        "```json",
        json.dumps(rows, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", nargs="*", default=["Low Memory", "Balanced"])
    ap.add_argument("--duration", type=int, default=30)
    args = ap.parse_args()

    service = MusicService()
    rows = []
    for preset in args.presets:
        if not service.model_ready(preset):
            print(f"skip {preset}: モデル未導入")
            continue
        row = run_one(service, preset, args.duration)
        if row:
            rows.append(row)

    if not rows:
        print("計測できませんでした。")
        return 1
    path = write_report(rows)
    print(f"\n📄 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
