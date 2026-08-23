# PROGRESS

セッション再開時はまずこのファイルを読むこと。各 Phase は 1〜3 行で状態と実測要点のみ記録する。

| Phase | 内容 | 状態 | 要点 |
|---|---|---|---|
| 1 | 環境調査 | 完了 | Apple M3 Pro / 18GB / macOS 26.5.1 / arm64。uv 0.9.29・brew・ffmpeg 8.1.2・git あり。system python は 3.14（MLX非対応）→ `.venv` は 3.12 |
| 2 | MLX 実装比較調査 | 完了 | 詳細は `docs/research/01-minimax-music3-mlx.md`。mlx-audio は **git main 必須**（PyPI 0.4.8 は非対応）。MLX 0.32.0 + Metal 動作確認済み |
| 3 | 最小 CLI 生成（ゲート） | **完了** | 実機生成成功。ロード 2.2 秒、sample_rate=44100。10秒/steps=8 で 65 秒・ピーク 13.0GB |
| 4 | 量子化評価 → デフォルト決定 | 完了 | 4bit を既定。Quality=6bit、8bit(14.17GB) は 18GB 機で非推奨表示 |
| 5 | Memory Guard | 完了 | `backend/memory/guard.py`。vm_stat と memory_pressure の大きい方を採用 |
| 6 | Prompt Builder | 完了 | `backend/prompt/builder.py`。日本語キーワード辞書＋構造化（Global/Vocal/Arrangement） |
| 7 | GUI | 完了 | `app/ui.py`（Gradio 6.24.0、127.0.0.1 のみ）。4タブ。HTTP 200 応答確認、全ハンドラ動作確認済 |
| 8 | History / Metadata | 完了 | `backend/history/store.py` |
| 9 | Model Manager | 完了 | `backend/models/{registry,downloader}.py`＋UIタブ |
| 10 | 起動方法 | 完了 | `start.command` / `bin/local-music` / `scripts/setup.sh` |
| 11 | Smoke Test | **合格** | 30秒/Low Memory/インスト: 327.7秒(実時間比10.9x)、5.05MB、44.1kHz stereo。RMS変動あり=実音楽、真ステレオ |
| 12 | 日本語 / Offline Smoke Test | **合格** | 日本語歌詞＋`HF_HUB_OFFLINE=1` で 30秒生成成功（326.7秒）。追加DL・外部通信なし |
| 13 | Benchmark | **完了** | `BENCHMARK.md`。Low Memory 325秒(10.83x) / Balanced 434秒(14.46x)、ともにピーク18.8GB |
| 14 | README / CLAUDE.md 更新 | **完了** | `README.md`（16章）＋ CLAUDE.md に実測値と制約を反映 |

## 決定事項ログ

- **ランタイム**: `mlx-audio` git main（PyPI 版には MiniMax Music3 が未収録）
- **モデル**: `mlx-community/MiniMax-Music3-4bit`（実測 8.58GB）を既定
- **Python**: 3.12（`.venv`）。system の 3.14 は使わない
- **ランタイム制約（重要）**: `steps` は **1〜30**（超えると例外）、`duration` は **0〜360 秒**
- **生成方式**: worker を**別プロセス**で起動。Stop 時にプロセスごと落としてメモリを確実に解放する
- **MLX は GPU 実行のため CPU 使用率が低く見える**。「止まっている」と誤判断しないこと

## 既知のリスク

- 実行中の Mac は常時 swap 12GB 前後を使用しており、空きメモリが 4〜9GB しかない状態が多い。
  Memory Guard の警告が出やすい。ベンチマークは他アプリを閉じた状態で取り直すこと。

## 追加で判明したこと

- 外部通信監査 `scripts/audit_network.sh` は **PASS**（外部AI API 0件、通信は downloader.py のみ、bind は 127.0.0.1）
- ユニットテスト 15件すべて合格（`.venv/bin/python -m pytest tests/ -q`）
- 30秒生成でも swap が 2GB 増える（13.93→15.93GB）。18GB 機ではメモリ的にかなりぎりぎり
- `service.generate` は生成を別スレッドで走らせ、キュー経由で進捗を逐次 yield する。
  同期呼び出しにすると UI が「準備中」のまま固まって見えるので戻さないこと

## 完成時点の検証結果（2026-08-17）

- 実機生成: 合格（英語インスト30秒 / 日本語歌唱30秒 / オフライン / 60秒上限）
- Stop: 合格（45秒時点で中断 → ワーカープロセス残存なし、run_dir も削除）
- 外部通信監査: PASS / ユニットテスト 15件合格 / UI HTTP 200 応答確認
- **duration は上限であり指定長ではない**（60秒指定→21.06秒）。UI・README に明記済み

## UI 実機テストで見つかった不具合と修正（2026-08-17）

ブラウザから作曲すると必ず失敗していた。原因は 2 つ。

1. **「生成ステップ数」スライダーが minimum=1 / value=0** → Gradio が送信時に
   `Value 0 is less than minimum value 1` で弾いていた。0 は「おまかせ」の意味なので
   minimum を 0 に変更。**これが「動かない」の主因**
2. **長さの Radio が生の int 選択肢** → 型不一致で拒否される。
   `[(f"{d}秒", d) for d in ...]` のラベル付きに変更（表示も「30秒」で分かりやすくなった）

再発防止として `tests/test_ui_components.py` を追加。全 Slider の初期値が範囲内か、
Radio/Dropdown の初期値が選択肢に含まれるかを機械的に検証する（テスト計 19 件）。

**画面が表示できること ≠ 動くこと。** UI 変更後は必ず gradio_client で
`/do_generate` を実際に 1 回通すこと。

## 長尺（3分）生成の実測と限界（2026-08-17）

`scripts/make_song.py` で日本語ボーカル曲を生成。

- **結果: 174.94秒（2.9分）を 31.5分で生成。完走した**（上限180秒指定）
- ピークメモリ 15.71GB / 最小空き 5.2GB / swap 最大 17.02GB
- 歌詞を9ブロック（verse×3・chorus×3・pre-chorus・bridge・outro）書いたことで、
  60秒指定で21秒しか出なかった問題は解消。**長さは歌詞量で決まる**が裏づけられた

### 判明した限界: テンポ変化はプロンプトで制御しきれない

「ゆるいテンポ→後半アップテンポ」を Prompt Builder の tempo arc
（62BPM→128BPM と明示）で指示したが、**実際には約78BPMのまま**だった。
区間ごとの推定BPMは 77 / 156 / 156 / 77 / 78 / 156 と交互で、156 は 78 の
倍テンポ検出（同一テンポの細かい刻み）。曲の盛り上がり（音量・密度）はついたが、
テンポそのものは変わっていない。

→ 曲中でのテンポ変更が要るときは、区間ごとに分けて生成して繋ぐ等の別手段が必要。
   UI で「テンポが変わる曲」を約束しないこと。
