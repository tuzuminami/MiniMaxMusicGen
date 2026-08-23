"""Application Service。UI と生成バックエンドの間をつなぐ層。

UI はこのクラスだけを使う。MLX やモデルの詳細は下の層に閉じ込める。
"""

from __future__ import annotations

import platform
import queue
import shutil
import subprocess
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from .config import APP_VERSION, Settings, load_settings
from .generation.base import (
    CancelToken,
    GenerationCancelled,
    GenerationError,
    GenerationRequest,
    MusicBackend,
)
from .generation.minimax_mlx import MiniMaxMusic3MLXBackend
from .history.store import HistoryStore
from .memory import guard
from .models import registry
from .prompt.builder import PromptInput, build


@dataclass
class GenerationOutcome:
    ok: bool
    stage: str
    ratio: float
    message: str = ""
    detail: str = ""
    wav_path: Path | None = None
    run_dir: Path | None = None
    metadata: dict | None = None


def _mlx_version() -> str:
    try:
        import mlx.core as mx

        return getattr(mx, "__version__", "unknown")
    except ImportError:
        return "not installed"


def _mlx_audio_version() -> str:
    try:
        from importlib.metadata import version

        return version("mlx-audio")
    except Exception:  # noqa: BLE001
        return "unknown"


class MusicService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.history = HistoryStore(self.settings.outputs)
        self._cancel = CancelToken()
        self._backend: MusicBackend | None = None
        self._backend_key: str | None = None

    # --- バックエンド ----------------------------------------------------
    def backend_for(self, preset: str) -> MiniMaxMusic3MLXBackend:
        spec = registry.spec_for_preset(preset)
        if self._backend is None or self._backend_key != spec.key:
            self._backend = MiniMaxMusic3MLXBackend(self.settings.models, spec.key)
            self._backend_key = spec.key
        return self._backend  # type: ignore[return-value]

    def available_durations(self, preset: str) -> list[int]:
        return self.backend_for(preset).supported_durations()

    # --- 事前チェック ----------------------------------------------------
    def preflight(self, preset: str, duration_sec: int = 30) -> guard.GuardVerdict:
        backend = self.backend_for(preset)
        return guard.check(
            backend.estimated_memory_gb(duration_sec), self.settings.models
        )

    def model_ready(self, preset: str) -> bool:
        return self.backend_for(preset).is_ready()

    # --- 生成 -----------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.cancel()
        if self._backend is not None:
            self._backend.stop()  # type: ignore[attr-defined]

    def generate(
        self,
        inp: PromptInput,
        preset: str = "Low Memory",
        seed: int | None = None,
        steps: int | None = None,
        offline: bool = True,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> Iterator[GenerationOutcome]:
        """生成を実行し、進捗を逐次 yield する。"""
        self._cancel = CancelToken()
        backend = self.backend_for(preset)
        spec = registry.spec_for_preset(preset)

        if not backend.is_ready():
            yield GenerationOutcome(
                False,
                "エラー",
                0.0,
                "モデルがまだダウンロードされていません。\n"
                "「モデル管理」タブでダウンロードしてください。",
                detail=f"missing: {spec.repo_id}",
            )
            return

        built = build(inp)
        params = dict(registry.PRESET_PARAMS.get(preset, {"steps": 24}))
        if steps:
            params["steps"] = min(int(steps), registry.MAX_STEPS)

        run_dir = self.history.new_run_dir(inp.title)
        wav_path = run_dir / "song.wav"
        started_at = datetime.now()

        events: list[tuple[str, float]] = []

        req = GenerationRequest(
            style_prompt=built.style_prompt,
            lyrics=built.lyrics,
            duration_sec=inp.duration_sec,
            seed=seed,
            extra={**params, "offline": offline},
        )

        yield GenerationOutcome(True, "準備しています", 0.02)

        # 生成は別スレッドで走らせ、進捗はキュー経由で受け取って逐次 yield する。
        # こうしないと UI が「準備中」のまま完了まで固まって見える。
        updates: queue.Queue[tuple[str, float] | None] = queue.Queue()
        box: dict[str, object] = {}

        def progress(stage: str, ratio: float) -> None:
            events.append((stage, ratio))
            if on_progress:
                on_progress(stage, ratio)
            updates.put((stage, ratio))

        def run() -> None:
            try:
                box["result"] = backend.generate(
                    req, wav_path, progress=progress, cancel=self._cancel
                )
            except GenerationCancelled:
                box["cancelled"] = True
            except GenerationError as exc:
                box["error"] = exc
            except Exception as exc:  # noqa: BLE001 - UI を落とさない
                box["error"] = GenerationError(
                    "予期しないエラーが発生しました。", detail=traceback.format_exc()
                )
                del exc
            finally:
                updates.put(None)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        while True:
            item = updates.get()
            if item is None:
                break
            stage, ratio = item
            yield GenerationOutcome(True, stage, ratio)
        worker.join()

        if box.get("cancelled"):
            self.history.delete(run_dir)
            yield GenerationOutcome(False, "停止しました", 0.0, "生成を停止しました。")
            return

        if "error" in box:
            exc = box["error"]
            assert isinstance(exc, GenerationError)
            self.history.save_run(
                run_dir,
                style_prompt=built.style_prompt,
                lyrics=built.lyrics,
                metadata={
                    "error": exc.message,
                    "created_at": started_at.isoformat(timespec="seconds"),
                },
                log_text=exc.detail,
            )
            yield GenerationOutcome(False, "エラー", 0.0, exc.message, detail=exc.detail)
            return

        result = box["result"]
        assert result is not None

        metadata = {
            "title": inp.title or run_dir.name,
            "created_at": started_at.isoformat(timespec="seconds"),
            "app_version": APP_VERSION,
            "preset": preset,
            "seed": result.seed,
            "requested_duration_sec": inp.duration_sec,
            "generated_duration_sec": result.generated_duration_sec,
            "generation_elapsed_sec": result.elapsed_sec,
            "style_prompt": built.style_prompt,
            "structured_prompt": built.sections,
            "lyrics": built.lyrics,
            "is_instrumental": built.is_instrumental,
            "bpm": built.bpm,
            "user_input": {
                "description": inp.description,
                "genre": inp.genre,
                "moods": inp.moods,
                "tempo": inp.tempo,
                "vocal": inp.vocal,
            },
            "model": spec.repo_id,
            "quantization": spec.quantization,
            "steps": params.get("steps"),
            "mlx_version": _mlx_version(),
            "mlx_audio_version": _mlx_audio_version(),
            "offline": offline,
            "machine": {
                "chip": guard.get_status().chip,
                "macos": platform.mac_ver()[0],
                "python": platform.python_version(),
            },
            **{k: v for k, v in result.backend_info.items() if k != "log"},
        }

        mp3 = self.to_mp3(result.wav_path)
        if mp3:
            metadata["mp3"] = mp3.name

        self.history.save_run(
            run_dir,
            style_prompt=built.style_prompt,
            lyrics=built.lyrics,
            metadata=metadata,
            log_text=result.backend_info.get("log", "")
            + "\n"
            + "\n".join(f"{s} {r:.2f}" for s, r in events),
        )

        yield GenerationOutcome(
            True,
            "完了",
            1.0,
            f"生成が完了しました（{result.elapsed_sec:.0f}秒かかりました）。",
            wav_path=result.wav_path,
            run_dir=run_dir,
            metadata=metadata,
        )

    # --- 便利機能 --------------------------------------------------------
    @staticmethod
    def to_mp3(wav_path: Path) -> Path | None:
        """WAV から MP3 も作る（WAV が原本）。ffmpeg が無ければ何もしない。

        ローカルの ffmpeg を使うだけで、外部サービスは使わない。
        """
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not Path(wav_path).exists():
            return None
        mp3 = Path(wav_path).with_suffix(".mp3")
        try:
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path),
                 "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3)],
                check=True, capture_output=True, timeout=180,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return mp3 if mp3.exists() else None

    @staticmethod
    def reveal_in_finder(path: Path) -> None:
        if Path(path).exists():
            subprocess.run(["open", "-R", str(path)], check=False)

    @staticmethod
    def open_folder(path: Path) -> None:
        p = Path(path)
        if p.exists():
            subprocess.run(["open", str(p)], check=False)
