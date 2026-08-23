"""コマンドライン入口。

    ./bin/local-music doctor     環境診断
    ./bin/local-music ui         GUI を起動
    ./bin/local-music models     モデルの状態を表示
    ./bin/local-music download   推奨モデルを取得
    ./bin/local-music generate   簡易生成（動作確認用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import apply_privacy_env, load_settings  # noqa: E402
from backend.doctor import ERR, format_text, run_checks  # noqa: E402
from backend.models import downloader, registry  # noqa: E402


def cmd_doctor(_args) -> int:
    checks, overall = run_checks()
    print(format_text(checks, overall))
    return 1 if overall == ERR else 0


def cmd_ui(_args) -> int:
    from app.ui import main as ui_main

    ui_main()
    return 0


def cmd_models(_args) -> int:
    s = load_settings()
    print(f"保存先: {s.models}")
    print(f"ディスク空き: {registry.disk_free_gb(s.models)} GB\n")
    for st in registry.status_all(s.models):
        mark = "✅" if st.installed else "・"
        size = f"{st.size_gb} GB" if st.installed else f"約 {st.spec.download_gb} GB"
        star = " ★推奨" if st.spec.recommended else ""
        print(f"{mark} {st.spec.label:<36} {st.spec.quantization:<7} {size}{star}")
    return 0


def cmd_download(args) -> int:
    s = load_settings()
    spec = registry.MODELS.get(args.model or registry.DEFAULT_MODEL_KEY)
    if spec is None:
        print(f"不明なモデル: {args.model}\n利用可能: {', '.join(registry.MODELS)}")
        return 2
    for msg in downloader.download(s.models, spec):
        print(msg)
    print(downloader.verify(s.models, spec))
    return 0 if registry.is_installed(s.models, spec) else 1


def cmd_generate(args) -> int:
    from backend.prompt.builder import PromptInput
    from backend.service import MusicService

    service = MusicService()
    inp = PromptInput(
        description=args.description,
        lyrics=args.lyrics or "",
        vocal="インストゥルメンタル" if not args.lyrics else "自動",
        genre=args.genre,
        tempo="Medium",
        duration_sec=args.duration,
        title=args.title or "",
    )
    final = None
    for out in service.generate(inp, preset=args.preset, seed=args.seed):
        print(f"[{out.ratio*100:5.1f}%] {out.stage}")
        if not out.ok:
            print(f"エラー: {out.message}")
            if args.verbose and out.detail:
                print(out.detail)
            return 1
        final = out
    if final and final.wav_path:
        print(f"\n完成: {final.wav_path}")
        return 0
    return 1


def main() -> int:
    apply_privacy_env()
    p = argparse.ArgumentParser(prog="local-music", description="完全ローカル音楽生成")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("doctor", help="環境診断")
    sub.add_parser("ui", help="GUI を起動")
    sub.add_parser("models", help="モデルの状態を表示")

    d = sub.add_parser("download", help="モデルを取得")
    d.add_argument("--model", default=registry.DEFAULT_MODEL_KEY)

    g = sub.add_parser("generate", help="簡易生成")
    g.add_argument("description", help="曲の説明")
    g.add_argument("--lyrics", default="", help="歌詞（省略でインスト）")
    g.add_argument("--genre", default="Ambient")
    g.add_argument("--duration", type=int, default=30)
    g.add_argument("--preset", default="Low Memory")
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--title", default="")
    g.add_argument("--verbose", action="store_true")

    args = p.parse_args()
    handlers = {
        "doctor": cmd_doctor,
        "ui": cmd_ui,
        "models": cmd_models,
        "download": cmd_download,
        "generate": cmd_generate,
    }
    if args.command not in handlers:
        p.print_help()
        return 0
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
