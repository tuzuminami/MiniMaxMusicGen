"""モデルを使わずに動く基本テスト。

    .venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.history.store import HistoryStore  # noqa: E402
from backend.memory import guard  # noqa: E402
from backend.models import registry  # noqa: E402
from backend.prompt.builder import PromptInput, build  # noqa: E402


# --- Prompt Builder -----------------------------------------------------
def test_instrumental_uses_positive_lead_instrument():
    """インストは否定形だけでなく、主旋律の担当楽器を肯定形で指定する。"""
    out = build(PromptInput(vocal="インストゥルメンタル", genre="Ambient"))
    assert out.is_instrumental
    assert out.lyrics == "[Instrumental]"
    assert "carries the main melody" in out.style_prompt


def test_auto_vocal_follows_lyrics():
    assert build(PromptInput(vocal="自動", lyrics="")).is_instrumental
    assert not build(PromptInput(vocal="自動", lyrics="歌詞あり")).is_instrumental


def test_japanese_lyrics_preserved_and_tagged():
    text = "風がとおる 白い午後\n\n遠くで揺れる夏の音"
    out = build(PromptInput(vocal="女性", lyrics=text))
    assert "風がとおる" in out.lyrics
    assert "[verse]" in out.lyrics and "[chorus]" in out.lyrics


def test_existing_section_tags_are_kept_as_is():
    text = "[chorus]\nさびだけの歌詞"
    assert build(PromptInput(vocal="女性", lyrics=text)).lyrics == text


def test_keywords_split_between_instruments_and_imagery():
    """楽器は編成へ、情景語は imagery へ振り分ける。"""
    out = build(PromptInput(description="夏の夕方のピアノ", vocal="女性", lyrics="あ"))
    body = out.sections
    assert "piano" in body["Arrangement"]
    assert "summer" in body["Imagery"]
    assert "summer" not in body["Arrangement"]


def test_bpm_overrides_tempo_preset():
    assert build(PromptInput(tempo="Slow", bpm=140)).bpm == 140
    assert build(PromptInput(tempo="Slow")).bpm == 72


def test_structure_scales_with_duration():
    short = build(PromptInput(vocal="女性", lyrics="a", duration_sec=30))
    long = build(PromptInput(vocal="女性", lyrics="a", duration_sec=180))
    assert "bridge" not in short.sections["Arrangement"]
    assert "bridge" in long.sections["Arrangement"]


# --- Registry -----------------------------------------------------------
def test_runtime_limits_are_respected():
    """ランタイム制約 (steps 1..30) を超える既定値を持たない。"""
    for preset, params in registry.PRESET_PARAMS.items():
        assert 1 <= params["steps"] <= registry.MAX_STEPS, preset


def test_every_preset_maps_to_a_known_model():
    for preset, key in registry.PRESETS.items():
        assert key in registry.MODELS, preset


def test_default_model_is_the_recommended_one():
    assert registry.MODELS[registry.DEFAULT_MODEL_KEY].recommended


# --- Memory Guard -------------------------------------------------------
def test_guard_reports_this_machine():
    st = guard.get_status()
    assert st.total_gb > 0
    assert st.is_apple_silicon
    assert st.disk_free_gb > 0


def test_guard_blocks_impossible_request():
    assert guard.check(9999.0).level == "danger"


def test_guard_allows_tiny_request():
    assert guard.check(0.1).level == "ok"


# --- History ------------------------------------------------------------
def test_history_roundtrip(tmp_path):
    store = HistoryStore(tmp_path)
    d = store.new_run_dir("テスト曲")
    store.save_run(
        d,
        style_prompt="prompt",
        lyrics="歌詞",
        metadata={"title": "テスト曲", "preset": "Low Memory", "seed": 7,
                  "generated_duration_sec": 30, "style_prompt": "prompt"},
    )
    entries = store.list_entries()
    assert len(entries) == 1
    assert entries[0].title == "テスト曲"
    assert entries[0].seed == 7
    assert (d / "lyrics.txt").read_text(encoding="utf-8") == "歌詞"
    assert store.delete(d)


def test_history_refuses_to_delete_outside_outputs(tmp_path):
    """誤って outputs の外を消さないこと。"""
    store = HistoryStore(tmp_path / "outputs")
    outside = tmp_path / "important"
    outside.mkdir()
    assert not store.delete(outside)
    assert outside.exists()


# --- テンポ変化 ---------------------------------------------------------
def test_tempo_arc_added_when_slow_and_fast_both_mentioned():
    """「ゆるいテンポから後半アップテンポ」のような指定を1文にまとめる。"""
    out = build(
        PromptInput(
            description="ゆるいテンポから始まり、後半はアップテンポに変化する",
            vocal="女性", lyrics="あ", tempo="Medium",
        )
    )
    arc = out.sections["Arrangement"]
    assert "tempo arc" in arc
    assert "up-tempo section" in arc


def test_no_tempo_arc_for_single_tempo():
    out = build(PromptInput(description="静かなバラード", vocal="女性", lyrics="あ"))
    assert "tempo arc" not in out.sections["Arrangement"]
