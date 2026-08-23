"""MiniMax Music 3 (MLX) バックエンド。

mlx-audio の music ランタイムを薄くラップするだけ。生成本体は worker.py を
別プロセスで起動して実行する（Stop とメモリ解放を確実にするため）。
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import PROJECT_ROOT
from ..models import registry
from .base import (
    CancelToken,
    GenerationCancelled,
    GenerationError,
    GenerationRequest,
    GenerationResult,
    MusicBackend,
    ProgressFn,
)

def _venv_python() -> str:
    """.venv の python を優先して使う（start.command 経由でも確実に動くように）。"""
    candidate = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


class MiniMaxMusic3MLXBackend(MusicBackend):
    name = "minimax-music3-mlx"

    def __init__(self, models_dir: Path, model_key: str = registry.DEFAULT_MODEL_KEY):
        self.models_dir = Path(models_dir)
        self.spec = registry.MODELS[model_key]
        self._proc: subprocess.Popen | None = None

    # --- 状態 -----------------------------------------------------------
    def is_ready(self) -> bool:
        return registry.is_installed(self.models_dir, self.spec)

    def model_path(self) -> Path:
        return registry.local_path(self.models_dir, self.spec)

    def estimated_memory_gb(self, duration_sec: int = 30) -> float:
        return registry.estimated_memory_gb(self.spec, duration_sec)

    def supported_durations(self) -> list[int]:
        return list(registry.BEGINNER_DURATIONS)

    def load(self, progress: ProgressFn | None = None) -> None:
        """子プロセス方式のため、ここでは導入済みかの確認のみ行う。"""
        if not self.is_ready():
            raise GenerationError(
                "モデルがまだダウンロードされていません。\n"
                "「モデル管理」タブから ダウンロード を実行してください。",
                detail=f"missing model at {self.model_path()}",
            )

    def unload(self) -> None:
        self.stop()

    def info(self) -> dict:
        return {
            "backend": self.name,
            "model": self.spec.repo_id,
            "quantization": self.spec.quantization,
            "model_path": str(self.model_path()),
        }

    # --- 生成 -----------------------------------------------------------
    def generate(
        self,
        request: GenerationRequest,
        out_path: Path,
        progress: ProgressFn | None = None,
        cancel: CancelToken | None = None,
    ) -> GenerationResult:
        self.load()

        seed = request.seed if request.seed is not None else random.randint(0, 2**31 - 1)
        steps = min(int(request.extra.get("steps", 24)), registry.MAX_STEPS)
        duration = min(int(request.duration_sec), registry.MAX_DURATION_SEC)

        job = {
            "model_path": str(self.model_path()),
            "caption": request.style_prompt,
            "lyrics": request.lyrics,
            "duration": duration,
            "steps": steps,
            "seed": seed,
            "output_path": str(out_path),
            "offline": request.extra.get("offline", True),
        }

        log_lines: list[str] = []
        result_payload: dict | None = None
        error_payload: dict | None = None

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write(json.dumps(job, ensure_ascii=False))
            job_file = f.name

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(PROJECT_ROOT)

        try:
            self._proc = subprocess.Popen(
                [_venv_python(), "-m", "backend.generation.worker", job_file],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                # 親と別のプロセスグループにして、Stop 時にまとめて止められるようにする
                start_new_session=True,
            )

            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                log_lines.append(line)
                if cancel is not None and cancel.cancelled:
                    self.stop()
                    raise GenerationCancelled()
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # ライブラリ側の通常ログ
                kind = msg.get("event")
                if kind == "progress" and progress:
                    progress(msg.get("stage", ""), float(msg.get("ratio", 0.0)))
                elif kind == "done":
                    result_payload = msg
                elif kind == "error":
                    error_payload = msg
                elif kind == "cancelled":
                    raise GenerationCancelled()

            code = self._proc.wait()
        finally:
            Path(job_file).unlink(missing_ok=True)
            proc, self._proc = self._proc, None
            if proc and proc.poll() is None:
                proc.kill()

        if cancel is not None and cancel.cancelled:
            raise GenerationCancelled()

        if error_payload:
            raise GenerationError(
                _friendly_error(error_payload.get("message", "")),
                detail=error_payload.get("detail", ""),
            )

        if result_payload is None:
            tail = "\n".join(log_lines[-25:])
            if code == -signal.SIGKILL or code == 137:
                raise GenerationError(
                    "メモリ不足のため生成が中断された可能性があります。\n"
                    "他のアプリを閉じるか、Low Memory プリセットと短い長さでお試しください。",
                    detail=f"worker killed (exit {code})\n{tail}",
                )
            raise GenerationError(
                "生成に失敗しました。もう一度お試しください。",
                detail=f"worker exit {code}\n{tail}",
            )

        if progress:
            progress("完了", 1.0)

        return GenerationResult(
            wav_path=Path(result_payload["output_path"]),
            generated_duration_sec=float(result_payload["generated_duration_sec"]),
            elapsed_sec=float(result_payload["elapsed_sec"]),
            seed=int(result_payload["seed"]),
            backend_info={
                **self.info(),
                "sample_rate": result_payload.get("sample_rate"),
                "steps": steps,
                "model_load_sec": result_payload.get("load_sec"),
                "peak_memory_gb": result_payload.get("peak_memory_gb"),
                "log": "\n".join(log_lines),
            },
        )

    def stop(self) -> None:
        """生成プロセスを終了させ、モデルのメモリを OS へ返す。"""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()


def _friendly_error(raw: str) -> str:
    """ランタイムの英語エラーを初心者向けの日本語に言い換える。"""
    low = raw.lower()
    if "metal" in low and ("memory" in low or "allocat" in low):
        return (
            "メモリが不足しました。\n"
            "他のアプリ（Chrome、Photoshop、Docker など）を閉じるか、\n"
            "曲の長さを短くして、もう一度お試しください。"
        )
    if "lyrics are required" in low:
        return "歌詞が空です。歌詞を入力するか、ボーカルで「インストゥルメンタル」を選んでください。"
    if "description is required" in low:
        return "曲の説明が空です。どんな曲にしたいかを入力してください。"
    if "duration must be between" in low:
        return "曲の長さが対応範囲外です。360秒（6分）以内を指定してください。"
    if "steps must be between" in low:
        return "生成品質の設定が対応範囲外です。プリセットを選び直してください。"
    if "no such file" in low or "not found" in low:
        return (
            "モデルファイルが見つかりませんでした。\n"
            "「モデル管理」タブから ダウンロード をやり直してください。"
        )
    return f"生成に失敗しました。\n（{raw[:200]}）"
