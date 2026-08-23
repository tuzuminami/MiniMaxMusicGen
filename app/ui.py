"""初心者向け Web UI（localhost 限定）。

外部へは bind しない。127.0.0.1 のみ。
"""

from __future__ import annotations

import sys
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import APP_VERSION, apply_privacy_env, load_settings  # noqa: E402
from backend.doctor import format_text, run_checks  # noqa: E402
from backend.models import downloader, registry  # noqa: E402
from backend.prompt.builder import GENRES, MOODS, PromptInput, TEMPOS, VOCALS  # noqa: E402
from backend.service import MusicService  # noqa: E402

apply_privacy_env()
SETTINGS = load_settings()
SERVICE = MusicService(SETTINGS)

PRESET_HELP = {
    "Low Memory": "いちばん安全。メモリが少ないときはこれ。",
    "Balanced": "ふだん使い向け。品質と速さのバランス。",
    "Quality": "高品質だが重い。18GB では他アプリを閉じてから。",
}

EXAMPLE_DESC = """夏の夕方をイメージした少し切ないピアノポップ。
テンポは遅め。女性ボーカル。
映画のエンディングのような雰囲気。"""

EXAMPLE_LYRICS = """風がとおる 白い午後
遠くで揺れる夏の音

まだ名前のない気持ちを
そっと空へ放した"""


# --- 曲をつくる ---------------------------------------------------------
def _status_md(icon: str, title: str, body: str = "") -> str:
    out = f"### {icon} {title}"
    if body:
        out += "\n\n" + body.replace("\n", "  \n")
    return out


def do_generate(
    description, lyrics, vocal, genre, moods, tempo, duration, preset,
    seed, steps, bpm, title, long_duration, force,
):
    """生成を実行し、進捗を逐次返す。"""
    # 詳細設定で長尺が指定されていればそちらを使う
    if long_duration:
        duration = int(long_duration)
    audio_update = gr.update(value=None, visible=False)
    empty = ("", "", gr.update(visible=False))

    if not description.strip() and not lyrics.strip():
        yield (
            _status_md("⚠️", "入力が空です", "「曲の説明」か「歌詞」のどちらかは入力してください。"),
            audio_update, *empty,
        )
        return

    if not SERVICE.model_ready(preset):
        spec = registry.spec_for_preset(preset)
        yield (
            _status_md(
                "📦", "モデルの準備が必要です",
                f"このプリセットには {spec.label}（約{spec.download_gb}GB）が必要です。\n"
                "上の「モデル管理」タブからダウンロードしてください。",
            ),
            audio_update, *empty,
        )
        return

    # --- Memory Guard ---
    verdict = SERVICE.preflight(preset, int(duration))
    if verdict.level == "danger" and not force:
        yield (
            _status_md("🛑", "メモリが足りません", verdict.message),
            audio_update, "", "",
            gr.update(visible=True),  # Low Memory で生成ボタンを出す
        )
        return
    if verdict.level == "warning":
        yield (_status_md("⏳", "生成を開始します", verdict.message), audio_update, *empty)

    inp = PromptInput(
        description=description,
        lyrics=lyrics,
        vocal=vocal,
        genre=genre,
        moods=list(moods or []),
        tempo=tempo,
        bpm=int(bpm) if bpm else None,
        duration_sec=int(duration),
        title=title.strip(),
    )

    for out in SERVICE.generate(
        inp,
        preset=preset,
        seed=int(seed) if seed not in (None, "", -1) else None,
        steps=int(steps) if steps else None,
    ):
        if not out.ok:
            yield (
                _status_md("❌", out.stage, out.message),
                gr.update(value=None, visible=False),
                "",
                out.detail,
                gr.update(visible=False),
            )
            return

        if out.ratio >= 1.0 and out.wav_path:
            meta = out.metadata or {}
            req_d = meta.get("requested_duration_sec")
            gen_d = meta.get("generated_duration_sec")
            note = ""
            if req_d and gen_d and gen_d < req_d - 2:
                note = f"（上限{req_d}秒を指定しましたが、曲が自然に終わりました）"
            body = (
                f"{out.message}\n"
                f"Seed: {meta.get('seed')} ／ 長さ: {gen_d}秒 {note}\n"
                f"保存先: {out.run_dir}"
            )
            yield (
                _status_md("✅", "完成しました", body),
                gr.update(value=str(out.wav_path), visible=True),
                meta.get("style_prompt", ""),
                "",
                gr.update(visible=False),
            )
            return

        pct = int(out.ratio * 100)
        yield (
            _status_md("🎵", f"{out.stage}…", f"進捗: {pct}%"),
            audio_update, "", "", gr.update(visible=False),
        )


def do_stop():
    SERVICE.cancel()
    return _status_md("⏹", "停止しました", "生成を中止し、メモリを解放しました。")


def preview_prompt(description, lyrics, vocal, genre, moods, tempo, duration, bpm):
    from backend.prompt.builder import build

    built = build(
        PromptInput(
            description=description, lyrics=lyrics, vocal=vocal, genre=genre,
            moods=list(moods or []), tempo=tempo,
            bpm=int(bpm) if bpm else None, duration_sec=int(duration),
        )
    )
    return built.style_prompt


# --- 履歴 ---------------------------------------------------------------
HISTORY_HEADERS = ["曲名", "日時", "長さ", "プリセット", "Seed", "プロンプト", "フォルダ"]


def load_history():
    rows = [e.as_row() for e in SERVICE.history.list_entries()]
    return gr.update(value=rows, headers=HISTORY_HEADERS)


def on_history_select(evt: gr.SelectData):
    entries = SERVICE.history.list_entries()
    if evt.index is None:
        return None, "", gr.update(visible=False)
    row = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
    if row >= len(entries):
        return None, "", gr.update(visible=False)
    e = entries[row]
    info = f"**{e.title}**\n\n{e.created_at} ／ {e.preset} ／ Seed {e.seed}\n\n`{e.directory}`"
    audio = str(e.wav_path) if e.wav_path else None
    return audio, info, gr.update(visible=True)


def open_selected_folder(info_md):
    import re

    m = re.search(r"`([^`]+)`", info_md or "")
    if m:
        SERVICE.open_folder(Path(m.group(1)))
        return "📂 Finder で開きました。"
    return "先に一覧から曲を選んでください。"


def delete_selected(info_md):
    import re

    m = re.search(r"`([^`]+)`", info_md or "")
    if not m:
        return "先に一覧から曲を選んでください。", gr.update(), gr.update(visible=False)
    ok = SERVICE.history.delete(Path(m.group(1)))
    msg = "🗑 削除しました。" if ok else "削除できませんでした。"
    return msg, load_history(), gr.update(visible=False)


# --- モデル管理 ---------------------------------------------------------
MODEL_HEADERS = ["モデル", "量子化", "状態", "サイズ", "推奨", "保存先"]


def load_models():
    rows = []
    for st in registry.status_all(SETTINGS.models):
        rows.append([
            st.spec.label,
            st.spec.quantization,
            "✅ 導入済み" if st.installed else "未ダウンロード",
            f"{st.size_gb} GB" if st.installed else f"約 {st.spec.download_gb} GB",
            "★ 推奨" if st.spec.recommended else st.spec.note,
            st.path,
        ])
    return gr.update(value=rows, headers=MODEL_HEADERS)


def _spec_from_label(label: str) -> registry.ModelSpec:
    for spec in registry.MODELS.values():
        if spec.label == label:
            return spec
    return registry.MODELS[registry.DEFAULT_MODEL_KEY]


def do_download(label):
    spec = _spec_from_label(label)
    text = ""
    for msg in downloader.download(SETTINGS.models, spec):
        text = msg
        yield text, gr.update()
    yield text, load_models()


def do_verify(label):
    return downloader.verify(SETTINGS.models, _spec_from_label(label))


def ask_remove(label):
    spec = _spec_from_label(label)
    if not registry.is_installed(SETTINGS.models, spec):
        return "このモデルはまだダウンロードされていません。", gr.update(visible=False)
    return (
        f"⚠️ 「{spec.label}」を削除します。よろしいですか？\n"
        f"（再度使うには約 {spec.download_gb}GB のダウンロードが必要です）",
        gr.update(visible=True),
    )


def do_remove(label):
    spec = _spec_from_label(label)
    ok = registry.remove(SETTINGS.models, spec)
    msg = "🗑 削除しました。" if ok else "削除できませんでした。"
    return msg, load_models(), gr.update(visible=False)


def open_models_folder():
    SETTINGS.models.mkdir(parents=True, exist_ok=True)
    SERVICE.open_folder(SETTINGS.models)
    return "📂 Finder で開きました。"


# --- システムチェック ---------------------------------------------------
def do_doctor():
    checks, overall = run_checks(SETTINGS)
    return format_text(checks, overall)


# --- 画面 ---------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="ローカル音楽生成") as demo:
        gr.Markdown(
            f"# 🎵 ローカル音楽生成　<sub>v{APP_VERSION}</sub>\n"
            "このアプリは **お使いの Mac の中だけ** で音楽をつくります。"
            "インターネットにもクラウドにも、歌詞やプロンプトを送りません。\n"
            "<sub>Powered by MiniMax-Music3 (MLX)</sub>"
        )

        with gr.Tabs():
            # ---------------- 曲をつくる ----------------
            with gr.Tab("🎵 曲をつくる"):
                with gr.Row():
                    with gr.Column(scale=3):
                        description = gr.Textbox(
                            label="① どんな曲にしたいですか？",
                            info="日本語でかまいません。思いつくままに書いてください。",
                            placeholder=EXAMPLE_DESC,
                            lines=5,
                        )
                        lyrics = gr.Textbox(
                            label="② 歌詞（歌なしの曲をつくるなら空のままでOK）",
                            info="日本語の歌詞も歌えます。空行で区切ると自動で構成をつけます。",
                            placeholder=EXAMPLE_LYRICS,
                            lines=8,
                        )
                        with gr.Row():
                            vocal = gr.Radio(
                                list(VOCALS.keys()), value="自動", label="③ ボーカル"
                            )
                            genre = gr.Dropdown(
                                list(GENRES.keys()), value="Pop", label="④ ジャンル"
                            )
                        moods = gr.CheckboxGroup(
                            list(MOODS.keys()), label="⑤ 雰囲気（いくつでも選べます）"
                        )
                        with gr.Row():
                            tempo = gr.Radio(
                                list(TEMPOS.keys()), value="Medium", label="⑥ テンポ"
                            )
                            duration = gr.Radio(
                                [(f"{d}秒", d) for d in registry.BEGINNER_DURATIONS],
                                value=30,
                                label="⑦ 長さの上限（秒）",
                                info=(
                                    "これは「最大の長さ」です。曲が自然に終わると"
                                    "指定より短くなることがあります。はじめは30秒がおすすめです。"
                                ),
                            )
                        preset = gr.Radio(
                            list(PRESET_HELP.keys()),
                            value=SETTINGS.default_preset,
                            label="⑧ 動作モード",
                            info=" ／ ".join(f"{k}: {v}" for k, v in PRESET_HELP.items()),
                        )

                        with gr.Accordion("詳細設定（ふだんは開かなくて大丈夫です）", open=False):
                            title = gr.Textbox(label="曲名（未入力なら日時になります）")
                            long_duration = gr.Radio(
                                [("使わない", 0)]
                                + [(f"{d}秒", d) for d in registry.ADVANCED_DURATIONS],
                                value=0,
                                label="長い曲をつくる（秒・上限）",
                                info=(
                                    "0 で上の設定を使います。⚠️ 18GB の Mac では"
                                    "90秒以上はメモリが足りず、非常に遅くなるか失敗することがあります。"
                                ),
                            )
                            seed = gr.Number(
                                label="Seed（同じ数字＝同じ曲。-1 でランダム）", value=-1, precision=0
                            )
                            # 0 は「おまかせ」を表すので、最小値も 0 にしておく
                            steps = gr.Slider(
                                0, registry.MAX_STEPS, value=0, step=1,
                                label="生成ステップ数（0 でプリセットのおまかせ／多いほど高品質・低速）",
                            )
                            bpm = gr.Number(label="BPM（0 でテンポ設定のおまかせ）", value=0, precision=0)
                            preview_btn = gr.Button("生成に使うプロンプトを確認する", size="sm")

                        with gr.Row():
                            gen_btn = gr.Button("🎶 この内容で作曲する", variant="primary", scale=3)
                            stop_btn = gr.Button("⏹ 停止", scale=1)
                        low_mem_btn = gr.Button(
                            "🔽 Low Memory に変更して生成する", visible=False, variant="secondary"
                        )

                    with gr.Column(scale=2):
                        status = gr.Markdown(
                            _status_md("🎧", "準備OK", "左に入力して「作曲する」を押してください。")
                        )
                        audio_out = gr.Audio(label="できあがった曲", visible=False, type="filepath")
                        with gr.Accordion("生成に使われたプロンプト", open=False):
                            prompt_view = gr.Textbox(label="", lines=8)
                        with gr.Accordion("技術的な詳細（エラー時）", open=False):
                            detail_view = gr.Textbox(label="", lines=10)

                gen_inputs = [
                    description, lyrics, vocal, genre, moods, tempo, duration,
                    preset, seed, steps, bpm, title, long_duration,
                ]
                gen_outputs = [status, audio_out, prompt_view, detail_view, low_mem_btn]

                gen_btn.click(
                    do_generate,
                    inputs=gen_inputs + [gr.State(False)],
                    outputs=gen_outputs,
                )
                low_mem_btn.click(
                    lambda *a: None, None, None
                ).then(
                    do_generate,
                    inputs=[
                        description, lyrics, vocal, genre, moods, tempo, duration,
                        gr.State("Low Memory"), seed, steps, bpm, title,
                        long_duration, gr.State(True),
                    ],
                    outputs=gen_outputs,
                )
                stop_btn.click(do_stop, outputs=status)
                preview_btn.click(
                    preview_prompt,
                    inputs=[description, lyrics, vocal, genre, moods, tempo, duration, bpm],
                    outputs=prompt_view,
                )

            # ---------------- 履歴 ----------------
            with gr.Tab("📁 履歴"):
                gr.Markdown("つくった曲の一覧です。行をクリックすると再生できます。")
                hist_refresh = gr.Button("🔄 一覧を更新", size="sm")
                hist_table = gr.Dataframe(
                    headers=HISTORY_HEADERS, interactive=False, wrap=True
                )
                hist_info = gr.Markdown()
                hist_audio = gr.Audio(label="再生", type="filepath")
                with gr.Row(visible=False) as hist_actions:
                    hist_open = gr.Button("📂 フォルダを開く")
                    hist_del = gr.Button("🗑 削除", variant="stop")
                hist_confirm = gr.Markdown()

                hist_refresh.click(load_history, outputs=hist_table)
                hist_table.select(
                    on_history_select, outputs=[hist_audio, hist_info, hist_actions]
                )
                hist_open.click(open_selected_folder, inputs=hist_info, outputs=hist_confirm)
                hist_del.click(
                    delete_selected,
                    inputs=hist_info,
                    outputs=[hist_confirm, hist_table, hist_actions],
                )
                demo.load(load_history, outputs=hist_table)

            # ---------------- モデル管理 ----------------
            with gr.Tab("📦 モデル管理"):
                gr.Markdown(
                    "音楽をつくるための「モデル」を管理します。\n"
                    "**初めての方は ★推奨 のモデルをダウンロードしてください。**"
                )
                model_table = gr.Dataframe(
                    headers=MODEL_HEADERS, interactive=False, wrap=True
                )
                model_pick = gr.Dropdown(
                    [m.label for m in registry.MODELS.values()],
                    value=registry.MODELS[registry.DEFAULT_MODEL_KEY].label,
                    label="操作するモデル",
                )
                with gr.Row():
                    dl_btn = gr.Button("⬇️ ダウンロード", variant="primary")
                    vf_btn = gr.Button("🔍 確認")
                    rm_btn = gr.Button("🗑 削除", variant="stop")
                    of_btn = gr.Button("📂 フォルダを開く")
                rm_confirm_btn = gr.Button("本当に削除する", variant="stop", visible=False)
                model_log = gr.Textbox(label="状況", lines=8, interactive=False)

                dl_btn.click(do_download, inputs=model_pick, outputs=[model_log, model_table])
                vf_btn.click(do_verify, inputs=model_pick, outputs=model_log)
                rm_btn.click(ask_remove, inputs=model_pick, outputs=[model_log, rm_confirm_btn])
                rm_confirm_btn.click(
                    do_remove, inputs=model_pick, outputs=[model_log, model_table, rm_confirm_btn]
                )
                of_btn.click(open_models_folder, outputs=model_log)
                demo.load(load_models, outputs=model_table)

            # ---------------- システムチェック ----------------
            with gr.Tab("🩺 システムチェック"):
                gr.Markdown("動作に必要な環境が揃っているかを確認します。")
                doc_btn = gr.Button("🩺 チェックを実行", variant="primary")
                doc_out = gr.Textbox(label="結果", lines=24, interactive=False)
                doc_btn.click(do_doctor, outputs=doc_out)
                demo.load(do_doctor, outputs=doc_out)

    return demo


def main() -> None:
    demo = build_ui()
    # 127.0.0.1 のみ。外部へは公開しない。
    demo.queue(default_concurrency_limit=1).launch(
        theme=gr.themes.Soft(),
        server_name="127.0.0.1",
        server_port=SETTINGS.port,
        inbrowser=True,
        share=False,
        quiet=False,
    )


if __name__ == "__main__":
    main()
