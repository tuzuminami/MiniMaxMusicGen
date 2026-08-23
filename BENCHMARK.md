# BENCHMARK

実機で計測した結果です。理論値ではありません。

## 計測環境

- チップ: Apple M3 Pro
- メモリ: 18.0 GB (Unified Memory)
- macOS: 26.5.1
- Python: 3.12.3
- 計測日: 2026-08-17

> 計測時、他のアプリの影響でスワップが多めに使われている状態でした。
> クリーンな状態ではこれより速くなる可能性があります。

## 結果

| プリセット | 量子化 | steps | 要求長 | 生成長 | 所要時間 | 実時間比 | ピークメモリ | 出力 |
|---|---|---|---|---|---|---|---|---|
| Low Memory | 4bit | 16 | 30秒 | 30.02秒 | 325.0秒 | 10.83x | 18.8 GB | 5.05 MB |
| Balanced | 4bit | 24 | 30秒 | 30.02秒 | 434.1秒 | 14.46x | 18.8 GB | 5.05 MB |

## メモリの推移

| プリセット | 生成前 空きRAM | 生成後 空きRAM | swap 前 | swap 後 |
|---|---|---|---|---|
| Low Memory | 14.9 GB | 14.8 GB | 11.27 GB | 11.19 GB |
| Balanced | 14.8 GB | 14.8 GB | 11.19 GB | 18.33 GB |

## 曲の長さについて（重要）

指定する「長さ」は **上限** です。モデルは曲が自然に終わったと判断すると、そこで止まります。

| 指定 | 実際に生成された長さ | 所要時間 |
|---|---|---|
| 30秒 | 30.02秒（上限に到達） | 325秒 |
| 60秒 | 21.06秒（自然終了） | 228秒 |

長い曲がほしい場合は、**歌詞を多く書く**ほうが効果的です。数字を大きくするだけでは長くなりません。

## メモリについて

`mx.get_peak_memory()` は MLX が確保した総量で、そのぶんの物理 RAM が空いている必要が
あるという意味ではありません。実際には 30 秒生成が空き 15GB・スワップ増 2GB で完走しています。

ただし Balanced ではスワップが 11.19GB → 18.33GB と 7GB 増えました。
**18GB 機では 30 秒前後が快適に使える上限**です。

## 結論（M3 Pro 18GB）

- **ふだん使い: Low Memory / 30秒** … 約 5 分半で 1 曲
- Balanced は約 1.3 倍時間がかかり、スワップも増える。品質差が必要なときだけ
- 90 秒以上は物理メモリを大きく超えるため非推奨（Memory Guard が警告します）

## 読み方

- **実時間比** … 1秒の曲をつくるのに何秒かかるか。小さいほど速い
- **ピークメモリ** … MLX が確保した最大メモリ量（`mx.get_peak_memory()`）

## 生データ

```json
[
  {
    "preset": "Low Memory",
    "model": "mlx-community/MiniMax-Music3-4bit",
    "quantization": "4bit",
    "steps": 16,
    "duration_requested_sec": 30,
    "duration_generated_sec": 30.02,
    "elapsed_sec": 325.0,
    "realtime_factor": 10.83,
    "peak_memory_gb": 18.8,
    "ram_available_before_gb": 14.9,
    "ram_available_after_gb": 14.8,
    "memory_pressure_free_pct_before": 83,
    "swap_before_gb": 11.27,
    "swap_after_gb": 11.19,
    "output_mb": 5.05,
    "output": "outputs/2026-08-17_054432_bench-Low_Memory-30s/song.wav"
  },
  {
    "preset": "Balanced",
    "model": "mlx-community/MiniMax-Music3-4bit",
    "quantization": "4bit",
    "steps": 24,
    "duration_requested_sec": 30,
    "duration_generated_sec": 30.02,
    "elapsed_sec": 434.1,
    "realtime_factor": 14.46,
    "peak_memory_gb": 18.8,
    "ram_available_before_gb": 14.8,
    "ram_available_after_gb": 14.8,
    "memory_pressure_free_pct_before": 82,
    "swap_before_gb": 11.19,
    "swap_after_gb": 18.33,
    "output_mb": 5.05,
    "output": "outputs/2026-08-17_054958_bench-Balanced-30s/song.wav"
  }
]
```
