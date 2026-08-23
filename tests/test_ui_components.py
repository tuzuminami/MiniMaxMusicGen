"""UI 部品の設定が破綻していないか確かめる。

「作曲する」を押した瞬間に Gradio が入力を弾く種類の不具合は、
画面を作るだけでは気づけない。ここで初期値と選択肢を機械的に検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ui import build_ui  # noqa: E402


def _components(kind) -> list:
    demo = build_ui()
    return [c for c in demo.blocks.values() if isinstance(c, kind)]


def test_slider_defaults_are_within_range():
    """初期値が最小値を下回っていると、送信時に必ずエラーになる。

    実際に「生成ステップ数」で minimum=1 / value=0 になっており、
    作曲ボタンが常に失敗していた。
    """
    for s in _components(gr.Slider):
        assert s.minimum <= s.value <= s.maximum, (
            f"Slider({s.label!r}) の初期値 {s.value} が "
            f"範囲 [{s.minimum}, {s.maximum}] の外にある"
        )


def test_choice_defaults_exist_in_choices():
    """Radio / Dropdown の初期値が選択肢に無いと送信時に弾かれる。"""
    for kind in (gr.Radio, gr.Dropdown):
        for c in _components(kind):
            if c.value is None:
                continue
            values = [v for _, v in c.choices]
            assert c.value in values, (
                f"{kind.__name__}({c.label!r}) の初期値 {c.value!r} が "
                f"選択肢 {values!r} に含まれない"
            )


def test_duration_choices_are_integers():
    """長さは int で渡す前提。ラベルと値を分けておく（文字列だと型不一致になる）。"""
    demo = build_ui()
    radios = [
        c for c in demo.blocks.values()
        if isinstance(c, gr.Radio) and c.label and "長さ" in c.label
    ]
    assert radios, "長さの選択肢が見つからない"
    for r in radios:
        for _, value in r.choices:
            assert isinstance(value, int), f"{r.label}: 値 {value!r} が int でない"


def test_ui_builds_without_error():
    assert build_ui() is not None
