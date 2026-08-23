"""指定の内容で 1 曲つくる（長尺の検証用）。

    .venv/bin/python scripts/make_song.py

歌詞・曲調はこのファイルを書き換えて使う。UI と同じ Application Service を通すので、
ここで通れば UI からも同じ結果になる。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.memory import guard  # noqa: E402
from backend.prompt.builder import PromptInput  # noqa: E402
from backend.service import MusicService  # noqa: E402

# Giolì & Assia 風のオーガニックな Melodic House / Indie Dance。
# 歌詞の量がそのまま曲の長さになる。フル尺想定なので上限は 360 秒。
LYRICS = """[verse]
We learned to love
without a name,
without a name,
without a name.

Under the lights,
under their eyes,
we kept our hands
close to our sides.

[pre-chorus]
Too close to hide,
too far to touch,
we wanted little,
we wanted too much.

And I know,
I know,
I know—

[chorus]
love doesn't ask
who we are.

Love doesn't ask
who we are.

It only moves,
it only moves,
from me to you,
from me to you.

[verse]
There were nights
we walked like strangers,
two shadows
on the same street.

There were words
we never answered,
there were doors
we couldn't leave.

But your eyes said
stay,
stay,
stay.

Your eyes said
stay.

So I stayed.

[bridge]
Maybe the world
needed a reason.

Maybe the world
needed a word.

Woman and woman,
heart beside heart—

but love was there
before the words.

Before the words.
Before the words.

Love was there
before the words.

[chorus]
And I know,
I know,
I know—

love doesn't ask
who we are.

Love doesn't ask
who we are.

It only moves,
it only moves,
from me to you,
from me to you.

[verse]
We lost some days.
We lost some years.
We learned the shape
of quiet fear.

But now your hand
is in my hand.

Nothing to prove.
Nothing to prove.

Nothing.

To.

Prove.

[bridge]
If this is wrong,
let the night be wrong.

If this is strange,
let the stars be strange.

If this is love—

let it be love.

Let it be love.
Let it be love.

[verse]
Now the room is warm.
Now the morning stays.

You are beside me
in the ordinary day.

No running.
No hiding.
No other life.

Only this.

Only this.

Only this.

[chorus]
I know,
I know,
I know—

love doesn't ask
who we are.

Love doesn't ask
who we are.

It only moves,
it only moves,

from me to you,
from me to you,

from me
to you.

[outro]
And now—

we are here.

We are here.

We are here.

And we are happy
here.
"""

SONG = PromptInput(
    description=(
        "organic melodic house / indie dance with live human warmth, "
        "like a live electronic duo blending acoustic instruments with electronics; "
        "steady four-on-the-floor groove at 120 BPM; "
        "sparse spacious intro with no upfront kick, only hi-hats, shaker, rimshots and low toms, "
        "wide open space around an intimate close-mic female voice; "
        "layers grow every 8 to 16 bars: electronic drums, low toms, deep sub bass, "
        "warm analog synth pads, hypnotic arpeggio sequences and organ-like sustained tones, "
        "filters slowly opening so the spectrum gradually fills up; "
        "sub bass breathes gently with the kick, no aggressive sidechain pumping; "
        "mid-song the handpan takes over as the main motif, a short tender phrase "
        "repeated again and again over polyrhythmic percussion; "
        "ambiguous add9, sus2 and sus4 chords, bass notes shifting under a static harmony, "
        "bittersweet but ultimately reassuring; "
        "vocals evolve from dry, breathy and close into layered doubles, harmonies and "
        "distant whispers, with delay echoes repeating short phrases like 'from me to you'; "
        "no sudden EDM drop: the music swells gradually until you realize it has peaked; "
        "the outro strips everything away until only handpan and voice remain, "
        "warm and wistful, neither sad nor happy, simply present"
    ),
    lyrics=LYRICS,
    vocal="女性",
    genre="Melodic House / Indie Dance",
    moods=[],
    tempo="Medium",
    bpm=120,
    duration_sec=360,
    title="We Are Here",
)

PRESET = "Low Memory"


def main() -> int:
    before = guard.get_status()
    print("=== 曲をつくります ===")
    print(f"  タイトル: {SONG.title}")
    print(f"  長さの上限: {SONG.duration_sec}秒 / プリセット: {PRESET}")
    print(f"  開始前 空きメモリ {before.available_gb}GB / swap {before.swap_used_gb}GB")
    print()

    service = MusicService()
    if not service.model_ready(PRESET):
        print("❌ モデルが未導入です。")
        return 1

    started = time.perf_counter()
    min_avail = before.available_gb
    max_swap = before.swap_used_gb
    final = None

    for out in service.generate(SONG, preset=PRESET, seed=2026):
        now = guard.get_status()
        min_avail = min(min_avail, now.available_gb)
        max_swap = max(max_swap, now.swap_used_gb)
        print(
            f"  [{time.perf_counter()-started:6.0f}s] {out.stage}"
            f"（空き {now.available_gb}GB / swap {now.swap_used_gb}GB）",
            flush=True,
        )
        if not out.ok:
            print(f"\n❌ {out.message}")
            if out.detail:
                print(out.detail[-1500:])
            return 1
        final = out

    elapsed = time.perf_counter() - started
    if final is None or final.wav_path is None:
        print("❌ 出力が得られませんでした。")
        return 1

    meta = final.metadata or {}
    gen = meta.get("generated_duration_sec") or 0
    print("\n=== 完成 ===")
    print(f"  ファイル: {final.wav_path}")
    print(f"  長さ: {gen:.2f}秒（{gen/60:.1f}分） / 上限指定 {SONG.duration_sec}秒")
    print(f"  所要時間: {elapsed/60:.1f}分 / 実時間比 {elapsed/max(gen,1):.1f}x")
    print(f"  ピークメモリ: {meta.get('peak_memory_gb')}GB")
    print(f"  最小空きメモリ: {min_avail}GB / 最大swap: {max_swap}GB")
    print(f"  Seed: {meta.get('seed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
