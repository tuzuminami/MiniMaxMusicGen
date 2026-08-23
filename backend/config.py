"""パス解決とアプリ設定。絶対パスはハードコードせず PROJECT_ROOT 基準にする。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

APP_VERSION = "0.1.0"

# backend/config.py の 2 階層上がプロジェクトルート。
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_path(key: str, default: Path) -> Path:
    v = os.environ.get(key)
    return Path(v).expanduser() if v else default


@dataclass
class Settings:
    models_dir: str = str(PROJECT_ROOT / "models")
    outputs_dir: str = str(PROJECT_ROOT / "outputs")
    logs_dir: str = str(PROJECT_ROOT / "logs")
    default_preset: str = "Low Memory"
    default_backend: str = ""  # 空なら registry の既定を使う
    port: int = 7860
    offline: bool = True  # モデル取得後は既定でオフライン

    @property
    def models(self) -> Path:
        return _env_path("LOCAL_MUSIC_MODELS_DIR", Path(self.models_dir))

    @property
    def outputs(self) -> Path:
        return _env_path("LOCAL_MUSIC_OUTPUTS_DIR", Path(self.outputs_dir))

    @property
    def logs(self) -> Path:
        return _env_path("LOCAL_MUSIC_LOGS_DIR", Path(self.logs_dir))

    def as_dict(self) -> dict:
        return asdict(self)


CONFIG_FILE = PROJECT_ROOT / "config" / "settings.json"


def load_settings() -> Settings:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            known = {f for f in Settings().as_dict()}
            return Settings(**{k: v for k, v in data.items() if k in known})
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    return Settings()


def save_settings(s: Settings) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(s.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def apply_privacy_env(offline: bool = False) -> None:
    """Telemetry を止め、必要ならオフラインを強制する。

    生成時に外部へ何も送らないことを担保するため、アプリ起動時に必ず呼ぶ。
    """
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    # Gradio の解析・バージョンチェックを止める
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def hf_cache_dir(settings: Settings) -> Path:
    """Hugging Face のダウンロード先をプロジェクト内に閉じ込める。"""
    return settings.models / "hf"
