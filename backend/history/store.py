"""生成結果の保存と履歴管理。

outputs/<YYYY-MM-DD_HHMMSS>/ に song.wav, metadata.json, prompt.txt,
lyrics.txt, generation.log をまとめて置く。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def _safe_slug(text: str, limit: int = 40) -> str:
    keep = [c for c in text.strip() if c.isalnum() or c in " -_ぁ-んァ-ヶ一-龠ー"]
    slug = "".join(keep).strip().replace(" ", "_")
    return slug[:limit]


def _stamp_from_name(name: str) -> str:
    """metadata.json が無いフォルダ向けに、フォルダ名から日時を復元する。"""
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})", name)
    if not m:
        return name
    return f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"


@dataclass
class HistoryEntry:
    directory: Path
    title: str
    created_at: str
    duration_sec: float
    preset: str
    seed: int | None
    prompt: str
    model: str
    wav_path: Path | None

    def as_row(self) -> list:
        return [
            self.title,
            self.created_at,
            f"{self.duration_sec:.0f}秒" if self.duration_sec else "-",
            self.preset,
            str(self.seed) if self.seed is not None else "-",
            (self.prompt[:60] + "…") if len(self.prompt) > 60 else self.prompt,
            str(self.directory),
        ]


class HistoryStore:
    def __init__(self, outputs_dir: Path):
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def new_run_dir(self, title: str = "", when: datetime | None = None) -> Path:
        stamp = (when or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
        name = stamp
        slug = _safe_slug(title)
        if slug:
            name = f"{stamp}_{slug}"
        d = self.outputs_dir / name
        suffix = 1
        while d.exists():
            suffix += 1
            d = self.outputs_dir / f"{name}-{suffix}"
        d.mkdir(parents=True)
        return d

    def save_run(
        self,
        run_dir: Path,
        *,
        style_prompt: str,
        lyrics: str,
        metadata: dict,
        log_text: str = "",
    ) -> None:
        run_dir = Path(run_dir)
        (run_dir / "prompt.txt").write_text(style_prompt, encoding="utf-8")
        (run_dir / "lyrics.txt").write_text(lyrics, encoding="utf-8")
        (run_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if log_text:
            (run_dir / "generation.log").write_text(log_text, encoding="utf-8")

    def list_entries(self) -> list[HistoryEntry]:
        entries: list[HistoryEntry] = []
        if not self.outputs_dir.exists():
            return entries
        for d in sorted(self.outputs_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            meta_file = d / "metadata.json"
            wav_file = d / "song.wav"
            # 強制終了などで中身のないフォルダが残ることがある。履歴には出さない。
            if not meta_file.exists() and not wav_file.exists():
                continue
            meta: dict = {}
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    meta = {}
            entries.append(
                HistoryEntry(
                    directory=d,
                    title=meta.get("title") or d.name,
                    created_at=meta.get("created_at") or _stamp_from_name(d.name),
                    duration_sec=float(meta.get("generated_duration_sec") or 0),
                    preset=meta.get("preset", "-"),
                    seed=meta.get("seed"),
                    prompt=meta.get("style_prompt", ""),
                    model=meta.get("model", "-"),
                    wav_path=wav_file if wav_file.exists() else None,
                )
            )
        return entries

    def delete(self, run_dir: Path) -> bool:
        """outputs 配下であることを確認したうえで削除する（誤削除防止）。"""
        run_dir = Path(run_dir).resolve()
        root = self.outputs_dir.resolve()
        if root not in run_dir.parents or not run_dir.is_dir():
            return False
        shutil.rmtree(run_dir)
        return True
