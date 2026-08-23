"""macOS のメモリ状況を確認し、生成を安全に始められるか判定する。

標準の sysctl / memory_pressure / vm_stat のみを使う（外部依存なし）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

GB = 1024**3


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _sysctl(key: str) -> str:
    return _run(["sysctl", "-n", key]).strip()


@dataclass
class MemoryStatus:
    total_gb: float
    available_gb: float
    free_percent: int | None
    swap_used_gb: float
    disk_free_gb: float
    chip: str
    is_apple_silicon: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _available_gb() -> tuple[float, int | None]:
    """空きメモリ量(GB)と memory_pressure の free percentage を返す。"""
    free_percent: int | None = None
    out = _run(["memory_pressure"])
    m = re.search(r"System-wide memory free percentage:\s*(\d+)", out)
    if m:
        free_percent = int(m.group(1))

    # vm_stat から free + inactive + speculative を「すぐ使える量」として概算する。
    vm = _run(["vm_stat"])
    page_size = 16384 if "Apple" in _sysctl("machdep.cpu.brand_string") else 4096
    m = re.search(r"page size of (\d+) bytes", vm)
    if m:
        page_size = int(m.group(1))

    pages = {}
    for line in vm.splitlines():
        km = re.match(r'"?Pages ([^:"]+)"?:\s+(\d+)', line.strip())
        if km:
            pages[km.group(1).strip()] = int(km.group(2))

    reclaimable = sum(
        pages.get(k, 0) for k in ("free", "inactive", "speculative", "purgeable")
    )
    available = reclaimable * page_size / GB

    # macOS は圧縮メモリも解放できるため、vm_stat の集計だけだと過小評価になり
    # 常に警告が出てしまう。memory_pressure の指標と大きい方を採用する。
    total = float(_sysctl("hw.memsize") or 0) / GB
    if free_percent is not None:
        available = max(available, total * free_percent / 100)
    return round(available, 1), free_percent


def _swap_used_gb() -> float:
    m = re.search(r"used\s*=\s*([\d.]+)([MGK])", _sysctl("vm.swapusage"))
    if not m:
        return 0.0
    value, unit = float(m.group(1)), m.group(2)
    factor = {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1.0}[unit]
    return round(value * factor, 2)


def get_status(project_root: Path | None = None) -> MemoryStatus:
    chip = _sysctl("machdep.cpu.brand_string") or "unknown"
    total = float(_sysctl("hw.memsize") or 0) / GB
    available, free_percent = _available_gb()
    target = project_root or Path.cwd()
    disk_free = shutil.disk_usage(target).free / GB
    return MemoryStatus(
        total_gb=round(total, 1),
        available_gb=available,
        free_percent=free_percent,
        swap_used_gb=_swap_used_gb(),
        disk_free_gb=round(disk_free, 1),
        chip=chip,
        is_apple_silicon=chip.startswith("Apple"),
    )


@dataclass
class GuardVerdict:
    level: str  # "ok" | "warning" | "danger"
    message: str
    suggest_low_memory: bool
    status: MemoryStatus


def check(required_gb: float, project_root: Path | None = None) -> GuardVerdict:
    """生成に required_gb 必要なとき、今始めて安全かを判定する。"""
    st = get_status(project_root)
    headroom = st.available_gb - required_gb
    apps = "Chrome / Safari の重いタブ、Photoshop、Docker、他のAIアプリ"

    # swap の使用量は「これまでの累積」で、いま空きが十分なら問題にならない。
    # 判定は空きメモリの余裕を主軸にし、swap は補足情報として添える。
    if headroom >= 2.0:
        note = ""
        if st.swap_used_gb >= 8.0:
            note = (
                f"\n（スワップを {st.swap_used_gb}GB 使用しています。"
                "動作が重いと感じたら Mac の再起動をおすすめします）"
            )
        return GuardVerdict("ok", "メモリに余裕があります。" + note, False, st)

    if headroom >= 0:
        msg = (
            f"利用可能なメモリが少なめです（空き {st.available_gb}GB / 必要 約{required_gb}GB）。\n"
            f"生成は開始できますが、動作が遅くなることがあります。\n"
            f"{apps} などを閉じると安定します。"
        )
        return GuardVerdict("warning", msg, True, st)

    msg = (
        f"現在利用可能なメモリが不足しています（空き {st.available_gb}GB / 必要 約{required_gb}GB）。\n\n"
        f"{apps}\n\nなどを閉じてから、もう一度お試しください。"
    )
    return GuardVerdict("danger", msg, True, st)
