"""音楽生成バックエンドの抽象。

UI / Application Service はこの層だけに依存する。将来モデルを差し替える場合は
MusicBackend を実装したクラスを追加し、registry に登録すれば良い。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# 進捗コールバック: (段階名, 0.0-1.0 の進捗) -> None
ProgressFn = Callable[[str, float], None]


class GenerationCancelled(Exception):
    """ユーザーが Stop を押したときに送出する。"""


class GenerationError(Exception):
    """生成失敗。message は初心者向けの日本語、detail は技術的詳細。"""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class GenerationRequest:
    style_prompt: str
    lyrics: str
    duration_sec: int = 30
    seed: int | None = None
    # ランタイム固有のパラメータ（steps, guidance, temperature 等）。
    # 対応していないキーはバックエンド側で無視する。
    extra: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    wav_path: Path
    generated_duration_sec: float
    elapsed_sec: float
    seed: int
    backend_info: dict = field(default_factory=dict)


class CancelToken:
    """スレッド間で安全に停止要求を伝える。"""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise GenerationCancelled()


class MusicBackend(ABC):
    """ローカル音楽生成モデルの共通インターフェース。"""

    name: str = "base"

    @abstractmethod
    def is_ready(self) -> bool:
        """モデルがローカルに揃っていて生成可能か。"""

    @abstractmethod
    def estimated_memory_gb(self, duration_sec: int = 30) -> float:
        """指定の長さを生成するのに必要と見込まれるメモリ量（Memory Guard 用）。"""

    @abstractmethod
    def supported_durations(self) -> list[int]:
        """このバックエンドで実用的に生成できる秒数の一覧。"""

    @abstractmethod
    def load(self, progress: ProgressFn | None = None) -> None:
        """モデルをメモリへロードする。"""

    @abstractmethod
    def generate(
        self,
        request: GenerationRequest,
        out_path: Path,
        progress: ProgressFn | None = None,
        cancel: CancelToken | None = None,
    ) -> GenerationResult:
        """生成して out_path に WAV を書き出す。"""

    @abstractmethod
    def unload(self) -> None:
        """モデルを解放してメモリを返す。"""

    def info(self) -> dict:
        """metadata.json に残す情報。"""
        return {"backend": self.name}
