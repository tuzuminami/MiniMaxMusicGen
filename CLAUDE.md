# CLAUDE.md — MiniMax Music 3 完全ローカルアプリ（M3 18GB）

## プロジェクト概要

MacBook Pro M3 / 18GB で動く、MiniMax Music 3 ベースの完全ローカル音楽生成 GUI アプリ。
最優先目標: **初心者が GUI から、完全無料・API なし・クラウドなしで日本語含む音楽生成ができること**。
CLI デモやモデル起動確認だけでは完成扱いにしない。

## 絶対条件（変更不可）

- 完全無料。外部 AI API・クラウド推論・API キー・有料サービスすべて禁止
  （OpenAI / Anthropic / Gemini / Replicate / fal / RunPod / HF Inference API / Suno / Udio 等すべて不可）
- CUDA / NVIDIA 依存禁止。Apple Silicon / MLX 優先
- 歌詞・Prompt・生成音源を外部送信しない。Telemetry は可能な限り無効化
- ネット利用はソース取得 / モデル DL / pip パッケージ取得 / 明示的アップデートのみ。セットアップ後はオフライン生成可能
- `.env` に API キーを要求する設計は禁止

## 基準環境

- MacBook Pro M3 / Unified Memory 18GB / macOS / arm64
- 優先順位: **安定性 > メモリ効率 > 使いやすさ > 生成速度**
- 量子化: 4bit (Low Memory) / 6bit (Balanced, デフォルト候補) / 8bit (Quality)。
  6bit が OOM / swap 過多なら実測に基づき 4bit をデフォルトに変更。「理論上動く」より実機結果を優先
- Python 環境は uv（`pyproject.toml` / `uv.lock` / `.venv`）。sudo pip / system Python 汚染 / 既存 conda・pyenv 変更は禁止

## 確定した技術スタック（再調査禁止・詳細は docs/research/01-minimax-music3-mlx.md）

```
Python 3.12（.venv / uv 管理。system の 3.14 は MLX 非対応）
mlx 0.32.0 + Metal
mlx-audio = git main（Blaizzy/mlx-audio）※PyPI 0.4.8 には MiniMax Music3 が入っていない
model = mlx-community/MiniMax-Music3-4bit（実測 8.58GB、sample_rate 44100）
UI = Gradio 6.24.0
```

**ランタイム制約（超えると例外）**
- `steps` は **1〜30**
- `duration` は **0〜360 秒**。これは**上限**であって指定長ではない。
  モデルは曲が自然に終わると途中で止まる（実測: 60秒指定 → 21.06秒生成）。
  長い曲がほしいときは歌詞を増やす。UI ではこれを明示すること
- 歌詞は必須。インストは `[instrumental]` を渡す

**実測値（M3 Pro 18GB）**
- モデルロード: 約 2.2 秒（lazy mmap なので速い）
- 生成: 10秒/steps=8 → 65秒・ピーク13.0GB / 30秒/steps=16 → **325秒**・ピーク18.8GB /
  30秒/steps=24 → 434秒・ピーク18.8GB（実時間比 約 11〜14x）
- `mx.get_peak_memory()` は MLX の確保総量。**必要な物理 RAM ではない**
  （30秒生成は空き15GB・swap+2GB で完走）。Memory Guard は実績ベースの目安
  `9.0 + 0.10×秒` を使う（`registry.estimated_memory_gb`）
- 初心者向けの長さは **30/60 秒のみ**。90 秒以上は詳細設定へ（18GB では非現実的）
- MLX は GPU 実行のため **プロセスの CPU 使用率は 5〜10% にしか見えない**。
  「止まっている」と誤判断しないこと。確認は `ioreg -c AGXAccelerator` の Device Utilization

**Gradio 6 の注意点**
- `theme` は `Blocks()` ではなく `launch()` に渡す
- `Textbox(show_copy_button=...)` は廃止
- `launch(show_api=...)` は廃止

## 組織体制（トークン節約のためのエージェント運用）

メインスレッドは「統括 + 実装 + 実機テスト」に専念し、探索的な作業はサブエージェントへ委譲する。

| 役割 | 担当 | 使い方 |
|---|---|---|
| 統括/実装 | メインスレッド | 設計判断・コード実装・実機での生成テスト・ベンチマーク |
| 調査班 | `general-purpose` agent | Web 一次情報調査（公式 GitHub / HF Model Card / Issues）。結論のみ返させる |
| 探索班 | `Explore` agent | 依存ライブラリ / ランタイムのコード調査、外部通信監査(§26)。ファイルダンプ不要、結論だけ受け取る |
| 設計班 | `Plan` agent | 大きな構造判断が必要な時のみ（多用しない） |

### 運用ルール

- サブエージェントへの指示は「何を返すか」を明示し、結論・要点のみ返させる。
- 調査結果は `docs/research/*.md` に保存し、再開時はまずそこを読む。同じ調査を繰り返さない。
- 生成テストは 5〜7 分かかる。background で実行し、生成ログは `tail` / `grep` で必要部分だけ読む。

## 進捗管理（セッション引き継ぎ）

- `PROGRESS.md` に各 Phase の状態（未着手 / 進行中 / 完了 + 実測結果の要点）を 1 Phase 1〜3 行で記録
- **Phase 完了ごとに必ず更新**。セッション再開時は `PROGRESS.md` → 必要な `docs/research/` の順に読み、コード全体の再探索をしない
- 実測値（メモリ・生成時間・成否）は `PROGRESS.md` か `BENCHMARK.md` に残す。会話コンテキストだけに置かない

## 現在の状態

全 14 Phase は完了し、Smoke Test・Offline Smoke Test・Benchmark を通過している（`PROGRESS.md`）。以降の変更は「完了条件」を回帰基準として扱い、生成経路に触れる変更は実機生成で再確認する。GUI は 127.0.0.1 のみで bind し、0.0.0.0 は使わない。Prompt Builder はルールベースで、LLM API は使わない。

## 実装原則

- 巨大な独自フレームワークを作らない。MLX ランタイムの**薄いラッパー**にする
- レイヤ分離: UI → Application Service → Music Generation Backend → MLX runtime
- `MusicBackend` 抽象 + `MiniMaxMusic3MLXBackend` 実装（将来モデル差し替え可能に）
- 絶対パスをハードコードしない。PROJECT_ROOT 基準の相対 or ユーザー設定可能パス
- モデル名は使用前に必ず現在の存在・互換性を一次情報で確認
- エラーは初心者向けメッセージ + 展開可能な Technical details。素の traceback を UI に出さない
- Memory Guard 必須: 生成前に available memory / memory pressure / swap を macOS 標準機能で確認
- 生成前に突然の大容量 DL 禁止。モデルは事前 DL、必要ファイルのみ取得（repo 全体 clone 禁止）
- UI に存在しない引数の設定項目を作らない

## Git / 管理外ファイル

- モデル / outputs / logs / cache / 音声ファイル / .venv は Git 管理しない
- `.gitignore`: `.venv/ models/ outputs/ logs/ cache/ __pycache__/ .DS_Store *.wav *.mp3 *.flac .env`

## 禁止操作

sudo / OS 設定変更 / SIP・Gatekeeper 変更 / 既存ファイル大量削除 / 既存 Python 環境削除 / Git 履歴破壊 / ユーザーデータ削除

## 完了条件（すべて必須）

MLX 実機生成 / GUI 生成 / 日本語入力 / WAV 保存 / History / Metadata / Memory Guard /
Model Manager / Setup / Doctor / オフライン生成 / README / Smoke Test 成功 / Benchmark 作成。
**実機生成なしで完成扱いしない。README と実装を同期させる。**

## 失敗時の判断

一度の失敗で「Apple Silicon 非対応」と結論しない。原因は一次情報（公式 README / Issues）で確認し、根拠のない回避策を積み増さない。
