"""生成を行う子プロセスの入口。

親プロセス（UI）とは stdout の JSON Lines で通信する。
別プロセスにしている理由:
  - Stop ボタンでプロセスごと終了でき、モデルのメモリを確実に解放できる
  - 生成が落ちても UI が巻き添えにならない

使い方: python -m backend.generation.worker <job.json>
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def emit(event: str, **fields) -> None:
    """親プロセスへ 1 行 JSON で状況を伝える。"""
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    if len(sys.argv) < 2:
        emit("error", message="ジョブ設定が渡されませんでした。", detail="missing job file")
        return 2

    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    # 外部送信を防ぐため、子プロセスでも必ず Telemetry を止める。
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    if job.get("offline", True):
        os.environ["HF_HUB_OFFLINE"] = "1"

    try:
        emit("progress", stage="モデルを準備しています", ratio=0.05)
        started = time.perf_counter()

        from mlx_audio.music.utils import load_model  # 重いのでここで import
        import mlx.core as mx

        model = load_model(job["model_path"])
        load_elapsed = time.perf_counter() - started
        emit("progress", stage="歌詞を解析しています", ratio=0.15, load_sec=round(load_elapsed, 1))

        gen_started = time.perf_counter()
        emit("progress", stage="音楽を生成しています（時間がかかります）", ratio=0.25)

        results = list(
            model.generate(
                text=job["caption"],
                lyrics=job["lyrics"],
                duration=float(job["duration"]),
                steps=int(job["steps"]),
                seed=int(job["seed"]),
            )
        )
        if not results:
            raise RuntimeError("Music generation produced no audio")

        emit("progress", stage="音声を書き出しています", ratio=0.9)

        from mlx_audio.audio_io import write as audio_write

        sample_rate = results[0].sample_rate
        audio = (
            results[0].audio
            if len(results) == 1
            else mx.concatenate([r.audio for r in results], axis=0)
        )
        out_path = Path(job["output_path"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        audio_write(out_path, audio, sample_rate)

        elapsed = time.perf_counter() - gen_started
        samples = int(audio.shape[0])
        emit(
            "done",
            output_path=str(out_path),
            sample_rate=int(sample_rate),
            generated_duration_sec=round(samples / sample_rate, 2),
            elapsed_sec=round(elapsed, 1),
            load_sec=round(load_elapsed, 1),
            seed=int(job["seed"]),
            peak_memory_gb=round(mx.get_peak_memory() / 1024**3, 2),
        )
        return 0

    except KeyboardInterrupt:
        emit("cancelled")
        return 130
    except Exception as exc:  # noqa: BLE001 - 親へ必ず理由を返す
        emit("error", message=str(exc), detail=traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
