"""ユーザーの簡単な入力から、音楽生成モデル向けの構造化プロンプトを組み立てる。

LLM API は使わない（絶対条件）。すべて辞書とルールで変換する。
ユーザーにプロンプト文法を覚えさせないことが目的。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# --- UI の選択肢（日本語）から英語ディスクリプタへの対応表 -------------------

GENRES: dict[str, str] = {
    "Pop": "pop",
    "Rock": "rock",
    "Electronic": "electronic",
    "Ambient": "ambient",
    "Jazz": "jazz",
    "Classical": "classical",
    "Hip Hop": "hip hop",
    "R&B": "r&b soul",
    "Folk": "folk acoustic",
    "J-Pop": "japanese pop, j-pop",
    "Experimental": "experimental",
    "その他": "",
}

# mood -> (雰囲気を表す語, 相性のよい編成, ダイナミクス)
MOODS: dict[str, tuple[str, str, str]] = {
    "明るい": ("bright, uplifting, cheerful", "clean electric guitar, bright piano", "energetic"),
    "暗い": ("dark, melancholic, somber", "low strings, deep bass", "restrained"),
    "切ない": ("bittersweet, wistful, emotional", "soft piano, warm strings", "gentle swells"),
    "壮大": ("epic, cinematic, sweeping", "orchestral strings, timpani, choir", "wide dynamic range"),
    "静か": ("calm, quiet, intimate", "sparse arrangement, soft pads", "soft and steady"),
    "激しい": ("intense, powerful, driving", "distorted guitars, hard drums", "loud and punchy"),
    "幻想的": ("dreamy, ethereal, atmospheric", "shimmering synth pads, reverb-heavy textures", "floating"),
    "ノスタルジック": ("nostalgic, warm, retro", "analog keys, tape-warm textures", "gentle"),
    "幸福": ("happy, warm, joyful", "acoustic guitar, light percussion", "lively"),
    "不穏": ("tense, uneasy, mysterious", "dissonant pads, sub bass drone", "brooding"),
}

TEMPOS: dict[str, tuple[str, int]] = {
    "Slow": ("slow tempo", 72),
    "Medium": ("moderate tempo", 100),
    "Fast": ("fast tempo", 138),
}

VOCALS: dict[str, str] = {
    "女性": "female",
    "男性": "male",
    "インストゥルメンタル": "instrumental",
    "自動": "auto",
}

# 女性/男性それぞれの標準的な声質・歌唱スタイル
VOCAL_TIMBRE = {
    "female": "clear warm female voice, natural breathy tone, expressive phrasing",
    "male": "warm male voice, soft mid-range tone, expressive phrasing",
}

# --- 日本語の自由記述からキーワードを拾うための辞書 -------------------------
# ここに無い言葉は原文のまま Imagery として渡す。

KEYWORDS: dict[str, str] = {
    # 楽器
    "ピアノ": "piano",
    "ギター": "guitar",
    "アコギ": "acoustic guitar",
    "アコースティックギター": "acoustic guitar",
    "エレキ": "electric guitar",
    "ベース": "bass",
    "ドラム": "drums",
    "ストリングス": "strings",
    "バイオリン": "violin",
    "ヴァイオリン": "violin",
    "チェロ": "cello",
    "シンセ": "synthesizer",
    "オルガン": "organ",
    "サックス": "saxophone",
    "トランペット": "trumpet",
    "フルート": "flute",
    "琴": "koto",
    "尺八": "shakuhachi",
    "和太鼓": "taiko drums",
    "オーケストラ": "orchestral arrangement",
    "コーラス": "backing vocals",
    "ハモリ": "harmony backing vocals",
    "口笛": "whistling",
    "鍵盤": "keys",
    # ↑ ここまでが楽器。INSTRUMENT_TERMS で編成欄に回す判定に使う。
    # 情景・イメージ
    "夏": "summer",
    "冬": "winter",
    "春": "spring",
    "秋": "autumn",
    "夕方": "evening light",
    "夕暮れ": "sunset",
    "夜": "night",
    "朝": "morning",
    "海": "ocean",
    "空": "open sky",
    "雨": "rain",
    "雪": "snow",
    "星": "starlight",
    "街": "city streets",
    "都会": "urban",
    "田舎": "countryside",
    "森": "forest",
    "宇宙": "space",
    "旅": "journey",
    "青春": "youthful",
    "恋": "romantic",
    "別れ": "farewell",
    "希望": "hopeful",
    "孤独": "lonely",
    # 質感・演出
    "映画": "cinematic",
    "エンディング": "end-credits feel",
    "オープニング": "opening theme feel",
    "アニメ": "anime style",
    "バラード": "ballad",
    "ロック": "rock",
    "ポップ": "pop",
    "ジャズ": "jazz",
    "クラシック": "classical",
    "エレクトロ": "electronic",
    "アンビエント": "ambient",
    "ローファイ": "lo-fi",
    "レトロ": "retro",
    "疾走感": "driving momentum",
    "盛り上が": "building to a powerful climax",
    "壮大": "epic and sweeping",
    "切な": "bittersweet",
    "優し": "gentle",
    "激し": "intense",
    "静か": "quiet and intimate",
    "明る": "bright",
    "暗い": "dark",
    "温か": "warm",
    "冷た": "cold",
    "軽やか": "light and airy",
    "重厚": "heavy and thick",
    "テンポは速": "fast tempo",
    "テンポは遅": "slow tempo",
    "アップテンポ": "up-tempo",
    "スローテンポ": "slow tempo",
}

# 「ゆっくり始まって速くなる」のようなテンポ変化の指定。
# 単一テンポの指定だけでは表現できないので、専用の一文を組み立てる。
_SLOW_CUES = ("ゆるいテンポ", "ゆっくり", "スローテンポ", "テンポは遅", "静かなイントロ", "静かに始ま")
_FAST_CUES = ("アップテンポ", "テンポは速", "速くな", "疾走", "駆け出", "走り出")
_CHANGE_CUES = ("変調", "転調", "変化", "変わ", "から", "後半", "途中")


def _tempo_arc(text: str, bpm: int) -> str:
    """テンポが変化する指定があれば、その一文を返す。無ければ空文字。"""
    has_slow = any(c in text for c in _SLOW_CUES)
    has_fast = any(c in text for c in _FAST_CUES)
    if not (has_slow and has_fast and any(c in text for c in _CHANGE_CUES)):
        return ""
    slow_bpm = max(60, int(bpm * 0.62))
    fast_bpm = min(170, int(bpm * 1.28))
    return (
        f"tempo arc: begins slow and spacious around {slow_bpm} BPM, "
        f"then shifts into an energetic up-tempo section around {fast_bpm} BPM "
        f"in the second half, with the drums and bass driving the change"
    )


# キーワードのうち「楽器」に相当するもの。編成(instrumentation)欄へはこれだけを入れ、
# 情景語（summer など）は Imagery 欄へ回す。
INSTRUMENT_TERMS: frozenset[str] = frozenset(
    {
        "piano", "guitar", "acoustic guitar", "electric guitar", "bass", "drums",
        "strings", "violin", "cello", "synthesizer", "organ", "saxophone",
        "trumpet", "flute", "koto", "shakuhachi", "taiko drums",
        "orchestral arrangement", "backing vocals", "harmony backing vocals",
        "whistling", "keys",
    }
)


# 楽曲構成（尺に応じて変える）
def _structure_for(duration_sec: int, instrumental: bool) -> str:
    if duration_sec <= 30:
        return "intro, single main section, short outro" if instrumental else "short intro, one verse, one chorus"
    if duration_sec <= 60:
        return (
            "intro, main theme, variation, outro"
            if instrumental
            else "intro, verse, chorus, short outro"
        )
    if duration_sec <= 120:
        return (
            "intro, theme A, theme B, restatement of theme A, outro"
            if instrumental
            else "intro, verse 1, chorus, verse 2, chorus, outro"
        )
    return (
        "intro, theme A, theme B, development, climax, gentle outro"
        if instrumental
        else "intro, verse 1, pre-chorus, chorus, verse 2, chorus, bridge, final chorus, outro"
    )


# インスト時に主旋律を担当させる楽器（肯定形で指定するため）
LEAD_BY_GENRE: dict[str, str] = {
    "ambient": "piano",
    "classical": "piano",
    "jazz": "piano",
    "pop": "piano",
    "japanese pop, j-pop": "piano",
    "rock": "electric guitar",
    "electronic": "lead synthesizer",
    "hip hop": "sampled keys",
    "r&b soul": "electric piano",
    "folk acoustic": "acoustic guitar",
    "experimental": "textural synthesizer",
}


@dataclass
class PromptInput:
    """UI から受け取る生の入力。"""

    description: str = ""
    lyrics: str = ""
    vocal: str = "自動"  # VOCALS のキー
    genre: str = "Pop"
    moods: list[str] = field(default_factory=list)
    tempo: str = "Medium"
    bpm: int | None = None  # Advanced。指定があれば tempo より優先
    duration_sec: int = 60
    title: str = ""


@dataclass
class BuiltPrompt:
    """モデルへ渡す最終形。"""

    style_prompt: str  # モデルへ渡すスタイル指定
    lyrics: str  # モデルへ渡す歌詞（インストなら [Instrumental]）
    sections: dict[str, str]  # 人が読める内訳（metadata 保存用）
    is_instrumental: bool
    bpm: int

    def as_dict(self) -> dict:
        return asdict(self)


def _extract_keywords(text: str) -> list[str]:
    """日本語の自由記述から既知のキーワードを英語ディスクリプタとして拾う。"""
    found: list[str] = []
    for jp, en in KEYWORDS.items():
        if jp in text and en not in found:
            found.append(en)
    return found


def _resolve_vocal(vocal: str, lyrics: str) -> str:
    """'自動' を歌詞の有無から解決する。"""
    v = VOCALS.get(vocal, "auto")
    if v != "auto":
        return v
    return "female" if lyrics.strip() else "instrumental"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = it.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it.strip())
    return out


def build(inp: PromptInput) -> BuiltPrompt:
    genre = GENRES.get(inp.genre, inp.genre.lower())
    tempo_word, default_bpm = TEMPOS.get(inp.tempo, TEMPOS["Medium"])
    bpm = inp.bpm or default_bpm
    if inp.bpm:
        tempo_word = f"{bpm} BPM"

    vocal = _resolve_vocal(inp.vocal, inp.lyrics)
    instrumental = vocal == "instrumental"

    mood_words, mood_instruments, mood_dynamics = [], [], []
    for m in inp.moods:
        if m in MOODS:
            w, ins, dyn = MOODS[m]
            mood_words.append(w)
            mood_instruments.append(ins)
            mood_dynamics.append(dyn)

    keywords = _extract_keywords(inp.description)

    # --- Global Metadata -------------------------------------------------
    global_parts = _dedupe([genre, tempo_word, f"{bpm} BPM"] + mood_words)
    global_meta = ", ".join(global_parts)

    # --- Vocal Details ---------------------------------------------------
    if instrumental:
        lead = LEAD_BY_GENRE.get(genre, "piano")
        # 否定形だけに頼らず、肯定形で主旋律の担当楽器を指定する。
        vocal_details = (
            f"instrumental piece with no singing and no vocals; "
            f"the {lead} carries the main melody throughout"
        )
    else:
        timbre = VOCAL_TIMBRE.get(vocal, VOCAL_TIMBRE["female"])
        vocal_details = f"{vocal} lead vocal, {timbre}, clearly intelligible lyrics"
        if inp.duration_sec >= 60:
            vocal_details += ", subtle harmony backing vocals in the chorus"

    # --- Arrangement -----------------------------------------------------
    instruments = _dedupe(
        [k for k in keywords if k in INSTRUMENT_TERMS] + mood_instruments
    )
    arrangement_parts = [f"song structure: {_structure_for(inp.duration_sec, instrumental)}"]
    if instruments:
        arrangement_parts.append("instrumentation: " + ", ".join(instruments[:6]))
    if mood_dynamics:
        arrangement_parts.append("dynamics: " + ", ".join(_dedupe(mood_dynamics)))
    arrangement_parts.append(
        "production: clean modern production, balanced mix, natural stereo width, "
        "moderate reverb for depth"
    )
    arc = _tempo_arc(inp.description, bpm)
    if arc:
        arrangement_parts.append(arc)
    arrangement_parts.append(
        "emotional progression: begins understated and grows in intensity toward the end"
    )
    arrangement = "; ".join(arrangement_parts)

    # --- Imagery ---------------------------------------------------------
    imagery_bits = _dedupe([k for k in keywords if k not in INSTRUMENT_TERMS])
    imagery = ", ".join(imagery_bits) if imagery_bits else ""
    description = inp.description.strip()

    sections = {
        "Global Metadata": global_meta,
        "Vocal Details": vocal_details,
        "Arrangement": arrangement,
        "Imagery": imagery,
        "User Description": description,
    }

    ordered = [global_meta, vocal_details, arrangement]
    if imagery:
        ordered.append(f"imagery: {imagery}")
    if description:
        ordered.append(description)
    style_prompt = ". ".join(p.rstrip(" 。.") for p in ordered if p) + "."

    lyrics = "[Instrumental]" if instrumental else _normalize_lyrics(inp.lyrics)

    return BuiltPrompt(
        style_prompt=style_prompt,
        lyrics=lyrics,
        sections=sections,
        is_instrumental=instrumental,
        bpm=bpm,
    )


def _normalize_lyrics(lyrics: str) -> str:
    """歌詞を整形する。構造タグが無ければ最低限の [verse] を補う。"""
    text = lyrics.replace("\r\n", "\n").strip()
    if not text:
        return "[Instrumental]"
    if re.search(r"\[[^\]]+\]", text):
        return text
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) == 1:
        return f"[verse]\n{blocks[0]}"
    tags = ["[verse]", "[chorus]", "[verse]", "[chorus]", "[bridge]", "[outro]"]
    out = []
    for i, b in enumerate(blocks):
        out.append(f"{tags[i] if i < len(tags) else '[outro]'}\n{b}")
    return "\n\n".join(out)
