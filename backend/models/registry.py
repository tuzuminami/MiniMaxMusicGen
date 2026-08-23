"""利用可能なモデルの定義とローカル状態の管理。

サイズ・repo id は docs/research/01-minimax-music3-mlx.md の一次情報確認結果に基づく。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

GB = 1024**3


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo_id: str
    label: str
    quantization: str
    download_gb: float  # HF 上の合計サイズ
    estimated_ram_gb: float  # 生成時に必要と見込まれるメモリ
    recommended: bool
    note: str = ""

    @property
    def local_dir_name(self) -> str:
        return self.repo_id.split("/")[-1]


# M3 18GB では 4bit を既定にする。8bit は 14.17GB で 18GB 機には重すぎるため非推奨。
MODELS: dict[str, ModelSpec] = {
    "minimax-music3-mxfp4": ModelSpec(
        key="minimax-music3-mxfp4",
        repo_id="mlx-community/MiniMax-Music3-mxfp4",
        label="MiniMax Music 3 (mxfp4 / 最小)",
        quantization="mxfp4",
        download_gb=8.90,
        estimated_ram_gb=11.0,
        recommended=False,
        note="最も軽量。実験的な量子化のため、4bit が動かない場合の予備。",
    ),
    "minimax-music3-4bit": ModelSpec(
        key="minimax-music3-4bit",
        repo_id="mlx-community/MiniMax-Music3-4bit",
        label="MiniMax Music 3 (4bit)",
        quantization="4bit",
        download_gb=9.21,
        # 実測: 10秒 / steps=8 でピーク 13.0GB（mx.get_peak_memory）
        estimated_ram_gb=13.0,
        recommended=True,
        note="M3 18GB での推奨モデル。",
    ),
    "minimax-music3-6bit": ModelSpec(
        key="minimax-music3-6bit",
        repo_id="mlx-community/MiniMax-Music3-6bit",
        label="MiniMax Music 3 (6bit)",
        quantization="6bit",
        download_gb=11.69,
        estimated_ram_gb=14.0,
        recommended=False,
        note="18GB 機ではぎりぎり。他のアプリを閉じてから使用してください。",
    ),
    "minimax-music3-8bit": ModelSpec(
        key="minimax-music3-8bit",
        repo_id="mlx-community/MiniMax-Music3-8bit",
        label="MiniMax Music 3 (8bit / 実験的)",
        quantization="8bit",
        download_gb=14.17,
        estimated_ram_gb=16.5,
        recommended=False,
        note="18GB 機では推奨しません（Not recommended on 18GB）。",
    ),
}

DEFAULT_MODEL_KEY = "minimax-music3-4bit"

# 生成に必要なメモリは「曲の長さ」でほぼ決まる（steps の影響は小さい）。
#
# 注意: mx.get_peak_memory() の実測値（10秒=13.0GB / 30秒=18.8GB）は MLX が確保した
# 総量であり、そのぶんの物理 RAM が空いている必要があるわけではない。実際 30 秒生成は
# 空き 15GB・スワップ増 2GB で完走している。ここでは「実際に完走できた条件」から
# 逆算した、物理メモリの目安を返す。
_MEM_BASE_GB = 9.0
_MEM_PER_SEC_GB = 0.10


def estimated_memory_gb(spec: ModelSpec, duration_sec: int = 30) -> float:
    """指定の長さを生成するのに必要と見込まれる空きメモリの目安。"""
    scale = spec.estimated_ram_gb / 13.0  # 4bit を基準に量子化差を反映
    return round((_MEM_BASE_GB + _MEM_PER_SEC_GB * duration_sec) * scale, 1)


# 初心者向けに出す長さ。18GB 機では 60 秒を超えると物理メモリを大きく超え、
# スワップ頼みになって現実的でないため、長尺は詳細設定へ回す。
BEGINNER_DURATIONS = [30, 60]
ADVANCED_DURATIONS = [90, 120, 180]

# プリセット -> モデル。18GB 機の実情に合わせ、Quality でも 6bit までとする。
PRESETS: dict[str, str] = {
    "Low Memory": "minimax-music3-4bit",
    "Balanced": "minimax-music3-4bit",
    "Quality": "minimax-music3-6bit",
}

# プリセットごとの生成パラメータ（steps が多いほど高品質・低速）。
# ランタイム側の制約: steps は 1..30、duration は 0..360 秒。この範囲を超えると例外になる。
MAX_STEPS = 30
MAX_DURATION_SEC = 360

PRESET_PARAMS: dict[str, dict] = {
    "Low Memory": {"steps": 16},
    "Balanced": {"steps": 24},
    "Quality": {"steps": 30},
}


def spec_for_preset(preset: str) -> ModelSpec:
    return MODELS[PRESETS.get(preset, DEFAULT_MODEL_KEY)]


def local_path(models_dir: Path, spec: ModelSpec) -> Path:
    return Path(models_dir) / spec.local_dir_name


# 生成に最低限必要なファイル。これが揃っていれば「導入済み」とみなす。
REQUIRED_FILES = ("config.json",)


def is_installed(models_dir: Path, spec: ModelSpec) -> bool:
    d = local_path(models_dir, spec)
    if not d.is_dir():
        return False
    if not all((d / f).exists() for f in REQUIRED_FILES):
        return False
    return any(d.glob("*.safetensors"))


def installed_size_gb(models_dir: Path, spec: ModelSpec) -> float:
    d = local_path(models_dir, spec)
    if not d.is_dir():
        return 0.0
    total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    return round(total / GB, 2)


def disk_free_gb(models_dir: Path) -> float:
    target = Path(models_dir)
    while not target.exists() and target != target.parent:
        target = target.parent
    return round(shutil.disk_usage(target).free / GB, 1)


@dataclass
class ModelStatus:
    spec: ModelSpec
    installed: bool
    size_gb: float
    path: str
    ready: bool


def status_all(models_dir: Path) -> list[ModelStatus]:
    out = []
    for spec in MODELS.values():
        inst = is_installed(models_dir, spec)
        out.append(
            ModelStatus(
                spec=spec,
                installed=inst,
                size_gb=installed_size_gb(models_dir, spec) if inst else 0.0,
                path=str(local_path(models_dir, spec)),
                ready=inst,
            )
        )
    return out


def remove(models_dir: Path, spec: ModelSpec) -> bool:
    """models_dir 配下であることを確認したうえで削除する。"""
    d = local_path(models_dir, spec).resolve()
    root = Path(models_dir).resolve()
    if root not in d.parents or not d.is_dir():
        return False
    shutil.rmtree(d)
    return True
