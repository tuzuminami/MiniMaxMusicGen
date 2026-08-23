# 調査: MiniMax Music 3 の Apple Silicon 実行手段（2026-08-17 時点）

一次情報（HF API / GitHub API / PyPI JSON / 公式 README）で確認済み。**再調査しないこと。**

## 結論

M3 18GB で歌声つき音楽生成を今日動かせる構成は実質1つ。

```
Python 3.12
mlx-audio  = git main（Blaizzy/mlx-audio）※PyPI 0.4.8 では不可
model      = mlx-community/MiniMax-Music3-4bit  (9.21GB)
実行        = python -m mlx_audio.music.generate
```

## MiniMax Music 3 本体

- HF: `MiniMaxAI/MiniMax-Music3` / GitHub: `MiniMax-AI/MiniMax-Music3`
- 構成: Global LLM 8B + Local LLM 0.6B + Flow Matching 2.4B + Flow-VAE Decoder 123M
- ライセンス: MiniMax-Music3 COMMUNITY LICENSE（商用可。UI に "MiniMax-Music3" 表示が必須。
  年商 $20M 超は別途書面許諾）
- **公式本家は CUDA 必須**（GPU 2枚 / diffusers 経路で 24GB VRAM）。Apple Silicon 対応の記載なし
  → MLX で動かすには下記 mlx-community 変換版 + mlx-audio が必要

## MLX 変換版（mlx-community, 2026-08-16 作成）

| repo id | 合計サイズ | 18GB 適合 |
|---|---|---|
| `mlx-community/MiniMax-Music3-mxfp4` | 8.90 GB | ◎（最小・実験的） |
| **`mlx-community/MiniMax-Music3-4bit`** | **9.21 GB** | **◎ 採用** |
| `mlx-community/MiniMax-Music3-6bit` | 11.69 GB | △ ぎりぎり |
| `mlx-community/MiniMax-Music3-8bit` | 14.17 GB | ✕ 18GB では厳しい |

4bit の中身: `model-0000{1,2}-of-00002.safetensors` + `config.json` + `tokenizer/` + `scheduler/`。
affine 4bit group64、embedding/conv/vocoder は full precision 維持。

別系統 `ddalcu/MiniMax-Music3-MLX-Serve-8bit` は Zig+MLX の独自エンジン用で **mlx-audio とは非互換**。

## mlx-audio（ここが最重要）

- PR #888「feat(music): add MiniMax Music 3 inference」が **2026-08-15 に main へ merge 済み**
- **PyPI 最新 0.4.8 は 2026-08-10 リリース = PR より前。`pip install mlx-audio` では動かない**
  → `git+https://github.com/Blaizzy/mlx-audio.git@main` を使うこと
- 依存: mlx>=0.31.1, mlx-lm>=0.31.1, transformers>=5.14.0, numpy, scipy, sounddevice,
  miniaudio, huggingface_hub>=1.0, tqdm
- CLI:
  ```
  python -m mlx_audio.music.generate --model <path> --caption "..." \
    --lyrics-file lyrics.txt --duration 30 --steps 30 --output song.wav
  ```
  `--model` は必須（デフォルトなし）。`--steps` デフォルト 30。
- **歌詞は必須**。`[verse]` `[chorus]` タグを使う。インストは `[instrumental]`
- music ドメインに実装されているモデルは minimax_music3 のみ

## 代替候補（保険）

- `mlx-community/ACE-Step1.5-MLX-4bit` 5.28GB — 歌声つき、mlx-audio 経由、ライセンス未確認
- `mlx-community/stable-audio-3-small-music` 3.45GB — インストのみ（歌声なし）
- MOSS-Music は音楽「解析」モデルで**生成用ではない**
- YuE / DiffRhythm / MusicGen の MLX 実装は確認できず（未確認）

## Python

- mlx 0.32.0 は cp314 wheel あり。ただし mlx-lm / sounddevice / miniaudio が 3.14 未検証
- → **3.12 を採用**（実機で mlx 0.32.0 + Metal 動作確認済み）

## 未確認・リスク

- **18GB 実機での peak RAM 実測値は公開情報なし**。9.21GB の重み + アクティベーション +
  full precision の vocoder/embedding が乗るため、macOS の wired limit（18GB 機で約13.5GB）に
  接触する可能性あり。ダメなら mxfp4 へ切り替える
- 出力サンプルレートは公式 32kHz / MLX カード 44.1kHz と記載が食い違う（未検証）
- 5分尺は 9000 acoustic frames 上限まで使いメモリ・時間とも跳ね上がる → 短尺から試す

## 主要 URL

- https://huggingface.co/mlx-community/MiniMax-Music3-4bit
- https://github.com/Blaizzy/mlx-audio
- https://huggingface.co/MiniMaxAI/MiniMax-Music3
