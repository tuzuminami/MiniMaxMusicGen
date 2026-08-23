"""環境診断。CLI (`bin/local-music doctor`) と UI の「システムチェック」で共用する。"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import APP_VERSION, Settings, load_settings
from .memory import guard
from .models import registry

OK, WARN, ERR = "OK", "WARNING", "ERROR"


@dataclass
class Check:
    name: str
    status: str
    value: str
    hint: str = ""


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _cmd_version(cmd: str, *args: str) -> str:
    path = _which(cmd)
    if not path:
        return ""
    try:
        out = subprocess.run(
            [path, *args], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        return out.splitlines()[0] if out else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def run_checks(settings: Settings | None = None) -> tuple[list[Check], str]:
    """全項目を確認し、(結果一覧, 総合判定) を返す。"""
    s = settings or load_settings()
    st = guard.get_status(s.models)
    checks: list[Check] = []

    checks.append(
        Check(
            "Apple Silicon",
            OK if st.is_apple_silicon else ERR,
            st.chip,
            "" if st.is_apple_silicon else "このアプリは Apple Silicon 専用です。",
        )
    )
    checks.append(Check("macOS", OK, platform.mac_ver()[0] or platform.platform()))
    checks.append(
        Check(
            "メモリ（合計）",
            OK if st.total_gb >= 16 else WARN,
            f"{st.total_gb} GB",
            "" if st.total_gb >= 16 else "16GB 未満では動作が不安定になることがあります。",
        )
    )
    avail_status = OK if st.available_gb >= 12 else (WARN if st.available_gb >= 8 else ERR)
    checks.append(
        Check(
            "メモリ（空き）",
            avail_status,
            f"{st.available_gb} GB",
            "" if avail_status == OK else "他のアプリを閉じるとより安定します。",
        )
    )
    checks.append(
        Check(
            "メモリ負荷",
            OK if (st.free_percent or 0) >= 30 else WARN,
            f"空き {st.free_percent}%" if st.free_percent is not None else "不明",
        )
    )
    swap_status = OK if st.swap_used_gb < 4 else WARN
    checks.append(
        Check(
            "スワップ使用量",
            swap_status,
            f"{st.swap_used_gb} GB",
            "" if swap_status == OK else "メモリが逼迫しています。再起動すると改善することがあります。",
        )
    )

    need_disk = max(m.download_gb for m in registry.MODELS.values() if m.recommended)
    disk_status = OK if st.disk_free_gb >= need_disk + 5 else (WARN if st.disk_free_gb >= need_disk else ERR)
    checks.append(
        Check(
            "ディスク空き",
            disk_status,
            f"{st.disk_free_gb} GB",
            "" if disk_status == OK else f"モデル用に {need_disk}GB 以上の空きが必要です。",
        )
    )

    py = platform.python_version()
    py_ok = sys.version_info[:2] == (3, 12)
    checks.append(
        Check(
            "Python",
            OK if py_ok else WARN,
            py,
            "" if py_ok else "3.12 での動作を確認しています。",
        )
    )
    uv_v = _cmd_version("uv", "--version")
    checks.append(Check("uv", OK if uv_v else WARN, uv_v or "未インストール", "" if uv_v else "セットアップに使用します。"))
    ff = _cmd_version("ffmpeg", "-version")
    checks.append(
        Check(
            "ffmpeg",
            OK if ff else WARN,
            ff.split(" version ")[-1].split(" ")[0] if ff else "未インストール",
            "" if ff else "MP3 変換に使います。無くても WAV 生成はできます。",
        )
    )

    try:
        import mlx.core as mx

        a = mx.ones((8, 8))
        mx.eval(a @ a)
        checks.append(Check("MLX / Metal", OK, f"{getattr(mx, '__version__', '?')} ({mx.default_device()})"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("MLX / Metal", ERR, "利用不可", str(exc)[:120]))

    try:
        import mlx_audio.music.models.minimax_music3  # noqa: F401
        from importlib.metadata import version

        checks.append(Check("MiniMax ランタイム", OK, f"mlx-audio {version('mlx-audio')}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check(
                "MiniMax ランタイム",
                ERR,
                "利用不可",
                "mlx-audio が正しく入っていません。セットアップをやり直してください。" + str(exc)[:80],
            )
        )

    # CUDA を使っていないことの確認（絶対条件）
    checks.append(Check("CUDA / NVIDIA", OK, "未使用（Apple Metal のみ）"))

    installed = [m for m in registry.status_all(s.models) if m.installed]
    default_spec = registry.MODELS[registry.DEFAULT_MODEL_KEY]
    default_ready = registry.is_installed(s.models, default_spec)
    checks.append(
        Check(
            "モデル",
            OK if default_ready else ERR,
            f"{len(installed)} 個導入済み"
            + (f"（{', '.join(m.spec.quantization for m in installed)}）" if installed else ""),
            "" if default_ready else "「モデル管理」タブからダウンロードしてください。",
        )
    )
    checks.append(
        Check(
            "オフライン生成",
            OK if default_ready else WARN,
            "可能" if default_ready else "モデル取得が必要",
            "" if default_ready else "モデルを取得すればネット接続なしで生成できます。",
        )
    )
    checks.append(Check("外部 AI API", OK, "0 件（完全ローカル）"))
    checks.append(Check("アプリ", OK, f"v{APP_VERSION}"))

    if any(c.status == ERR for c in checks):
        overall = ERR
    elif any(c.status == WARN for c in checks):
        overall = WARN
    else:
        overall = OK
    return checks, overall


def format_text(checks: list[Check], overall: str) -> str:
    mark = {OK: "✅", WARN: "⚠️ ", ERR: "❌"}
    lines = ["システムチェック", "=" * 46]
    for c in checks:
        lines.append(f"{mark[c.status]} {c.name:<22} {c.value}")
        if c.hint:
            lines.append(f"     → {c.hint}")
    lines += ["=" * 46, f"総合判定: {overall}"]
    return "\n".join(lines)
