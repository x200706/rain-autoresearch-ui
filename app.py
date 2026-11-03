"""Rain Autoresearch 的 Gradio 介面。啟動：python app.py（說明見 README）。"""
import html
import os
import time
from pathlib import Path
from urllib.parse import quote

import gradio as gr

from rainui import charts, config, models, progress, results, runner, skill, stations, theme, view
from rainui.stations import SUBGOAL_ORDER

ASSETS = Path(__file__).resolve().parent / "assets"
SPLITS = [("8 : 2", "82"), ("7 : 3", "73")]
SOURCES = [("已有資料的測站", "existing"), ("上傳新測站 CSV", "upload")]
SUB_CHOICES = [(f"{s}｜{stations.SUBGOALS[s]['desc']}", s) for s in SUBGOAL_ORDER]
METRIC_CHOICES = [("MAE（越低越好）", "mae"), ("RMSE（越低越好）", "rmse"), ("低估筆數（越少越好）", "under")]
PRED_SPLITS = [("訓練集", "train"), ("測試集", "test")]
# 深淺色只切換 body 的 dark class（所有顏色都是 CSS 變數），不重新載入頁面，看到一半也不會中斷。
# 選擇記在 localStorage；Gradio 跟著系統深淺色自己改模式時，監看器會改回使用者選的。
HIST_JS = """
() => {
  if (!window.raApplyTheme) {
    window.raThemeMode = () => {
      let saved = null;
      try { saved = localStorage.getItem('ra-theme'); } catch (e) {}
      return saved || new URLSearchParams(location.search).get('__theme') || 'dark';
    };
    window.raApplyTheme = (mode) => {
      const dark = mode === 'dark';
      if (document.body.classList.contains('dark') !== dark) document.body.classList.toggle('dark', dark);
      document.documentElement.style.colorScheme = mode;
      // 主題按鈕顯示「目前」的模式，滑鼠提示說明按下去會切到哪一種
      const themeBtn = document.getElementById('theme-btn');
      if (themeBtn) {
        themeBtn.textContent = dark ? '☾ 深色模式' : '☀ 淺色模式';
        themeBtn.title = dark ? '切換為淺色模式' : '切換為深色模式';
      }
    };
    // 切換按鈕直接在瀏覽器處理，不經過 Gradio 的事件佇列：頁面還在載入圖表時按也會立刻生效
    document.addEventListener('click', (event) => {
      if (!event.target.closest('#theme-btn')) return;
      const next = window.raThemeMode() === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('ra-theme', next); } catch (e) {}
      window.raApplyTheme(next);
    });
    new MutationObserver(() => {
      const want = window.raThemeMode() === 'dark';
      if (document.body.classList.contains('dark') !== want) window.raApplyTheme(window.raThemeMode());
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }
  window.raApplyTheme(window.raThemeMode());
  if (window.__raHistClick) return;
  window.__raHistClick = true;
  // 右側卡片：把 data-hist 寫進隱藏欄位，再按隱藏按鈕，交給 Python 切換主畫面
  document.addEventListener('click', (event) => {
    const card = event.target.closest('[data-hist]');
    const field = document.querySelector('#hist-key textarea, #hist-key input');
    if (!card || !field) return;
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), 'value').set;
    setter.call(field, card.dataset.hist);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    setTimeout(() => document.getElementById('hist-go')?.click(), 0);
  });
}
"""


# ---------------------------------------------------------------- left panel
def make_config(model, run_name, source, station, upload, split, metric, thr, sub_mode, subs, sub_text,
                max_gen, patience, children, parallel, template):
    """左側欄位 → RunConfig 與資料來源的錯誤。上傳模式只看上傳的檔案，選單模式只看選單。"""
    source_error = ""
    if source == "upload":
        if not upload:
            source_error = "請上傳測站 CSV"
            sid = ""
        else:
            sid = upload["station"]
            if upload["errors"]:
                source_error = "；".join(upload["errors"])
            else:
                try:
                    if sum(1 for v in upload["rain"] if v >= float(thr)) == 0:
                        source_error = f"沒有 ≥ {thr} mm 的時段，主目標算不出來"
                except (TypeError, ValueError):
                    pass
    else:
        sid = station or ""
    cfg = skill.RunConfig(station=sid, split=split or "82", run_name=(run_name or "").strip(), model=(model or "").strip(),
                          metric=metric, threshold=thr if thr is not None else 0, sub_mode=sub_mode,
                          subgoals=list(subs or []), sub_text=sub_text or "", max_gen=max_gen, patience=patience,
                          children=children, parallel=parallel, template=template or "")
    return cfg, source_error


def refresh_left(api_key, *values):
    cfg, source_error = make_config(*values)
    errors = skill.field_errors(cfg, api_key or "", source_error)
    source, station, upload, thr = values[2], values[3], values[4], values[7]

    def err(key):
        level_msg = errors.get(key)
        return gr.update(value=level_msg[1] if level_msg else "", visible=bool(level_msg))

    hit = view.cache_index().get(skill.fingerprint(cfg)) if not skill.blocking(errors) else None
    label = "Cache Hit・展示快取結果" if hit else "開始訓練"
    try:
        key_text = skill.goal_key(cfg)
    except (TypeError, ValueError):
        key_text = "—"
    override = "" if skill.is_default_goal(cfg) else '<span class="override">介面覆寫：Hermes 會先改程式再開始</span>'
    return (err("key"), err("model"), err("file"), view.file_chip(source, station, upload, thr), err("goal"),
            f'<code class="goal-key">→ {html.escape(key_text)}</code>{override}', err("sub"), err("evo"), err("tpl"),
            view.tokens_html(cfg.template), skill.shell_preview(cfg, str(config.rain_root())),
            gr.update(value=label), hit or "", skill_download(cfg))


def skill_download(cfg: skill.RunConfig) -> str:
    """下載連結直接指向寫好的 SKILL.md；設定一改就重寫，所以按一次就是目前的版本。"""
    folder = config.state_dir() / "downloads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(skill.skill_markdown(cfg), encoding="utf-8", newline="\n")
    href = f"gradio_api/file={quote(str(path))}?v={int(time.time() * 1000)}"
    return f'<a class="dl-btn" href="{href}" download="SKILL.md">下載 SKILL.md</a>'


def on_source(source):
    upload_mode = source == "upload"
    return gr.update(visible=not upload_mode), gr.update(visible=upload_mode, value=None), None


def on_upload(path):
    if not path:
        return None
    check = stations.check_csv(path)
    return {"name": check.name, "station": check.station, "rows": check.rows, "rain": check.rain,
            "errors": check.errors, "path": str(path)}


def on_sub_mode(mode):
    return gr.update(visible=mode == "preset"), gr.update(visible=mode == "semantic")


# ---------------------------------------------------------------- main view
def render_view(key, sub, pred_split, gen):
    """右側或按鈕選了哪個實驗，主畫面就畫哪個；回傳順序與 VIEW_OUTPUTS 一致。"""
    kind, _, ident = (key or "").partition(":")
    run = runner.get_run(ident) if kind == "run" else None
    station_id = run["station"] if run else ident
    running_view, flow, log, notes, notes_ok = False, "", "", "", False
    if run:
        run, p = runner.poll(run["id"])
        status = view.STATUS_TEXT.get(run["status"], run["status"])
        pill_kind = {"running": "run", "done": "ok", "failed": "err", "stopped": "err"}[run["status"]]
        meta = f"{stations.label(station_id)}・{'展示模式' if run['mode'] == 'demo' else run['model']}"
        head = view.header_html(run["name"], status, meta, pill_kind)
        flow, log = progress.flow_html(p), runner.log_tail(run)
        notes, notes_ok = run.get("notes", ""), run["status"] != "running"
        running_view = run["status"] != "done" or run["mode"] == "demo"
    station = None if running_view else results.load_station(station_id)
    if not run:
        if station is None:
            return (view.header_html("選一個實驗", "", ""), gr.update(visible=False), "", "", gr.update(visible=False),
                    *([gr.update()] * 8), gr.update(value="", interactive=False), gr.update(interactive=False))
        complete = stations.is_complete(station_id) or not station.get("live")
        head = view.header_html(station["label"], "已完成" if complete else "未完成", f"RAIN_SPLIT {station['split']}",
                                "ok" if complete else "warn")
        notes, notes_ok = runner.load_station_notes(station_id), True
    if station is None:
        return (head, gr.update(visible=True), flow, log, gr.update(visible=False), *([gr.update()] * 8),
                gr.update(value=notes, interactive=notes_ok), gr.update(interactive=notes_ok))
    sub = sub if sub in SUBGOAL_ORDER else "under"
    sg = station["subgoals"][sub]
    gens = results.generation_choices(station, sub)
    gen = gen if gen in gens else "全部"
    frame = results.predictions(sg["artifact"], pred_split or "train")
    pred_title = ("訓練集" if (pred_split or "train") == "train" else "測試集") + f"（{sg['best_run'] or '—'}）"
    # 預覽只放技能內容；name／description 是給 Hermes 讀的檔頭，不顯示
    skill_md = skill.strip_frontmatter(Path(run["log"]).with_name("SKILL.md").read_text(encoding="utf-8")) if run \
        else skill.render(skill.default_config(station_id))
    return (head, gr.update(visible=bool(run and log)), flow, log, gr.update(visible=True),
            view.stats_html(station, sub), charts.convergence(sg["conv"]), charts.predictions(frame, pred_title),
            gr.update(choices=gens, value=gen), results.results_table(station, sub, gen),
            station.get("card") or "（沒有測站資訊卡）", station.get("learnings") or "（還沒有學習紀錄）", skill_md,
            gr.update(value=notes, interactive=notes_ok), gr.update(interactive=notes_ok))


def history_update(query, key):
    return view.history_html(view.history_items(query or ""), key)


def footer_html():
    mode = config.run_mode()
    running = any(r["status"] == "running" for r in runner.load_runs())
    state = "● Hermes 執行中" if running else "● Hermes 待命"
    where = "<span>展示模式（不會訓練）</span>" if mode == "demo" else ""
    return f'<div class="footer"><span>{state}</span>{where}<span class="grow"></span>' \
           f'<span>{html.escape(str(config.rain_root()))}</span></div>'


# ---------------------------------------------------------------- build
def build() -> gr.Blocks:
    model_ids, live = models.fetch()
    choices = stations.station_choices()
    default_station = next((sid for _, sid in choices if sid == "467590"), choices[0][1] if choices else None)
    first_view = f"st:{default_station}" if default_station else next(
        (it["key"] for it in view.history_items()), None)
    css = (ASSETS / "style.css").read_text(encoding="utf-8")
    head = '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css">'
    with gr.Blocks(theme=theme.build(), css=css, js=HIST_JS, title="Rain Autoresearch", head=head) as demo:
        with gr.Row(elem_id="topbar"):
            gr.HTML('<div class="brand"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 15a4 4 0 0 1-.5-8A6 6 0 0 1 18 8a3.5 3.5 0 0 1 0 7"/>'
                    '<path d="M9 18l-1 3"/><path d="M13 18l-1 3"/><path d="M17 18l-1 3"/></svg><h1>Rain Autoresearch</h1>'
                    '<span class="muted">測站降雨模型自動調參互動原型</span></div>', elem_id="brand")
            gr.HTML('<a class="gh" href="https://github.com/x200706/rain-autoresearch-ui" title="GitHub" '
                    'aria-label="GitHub 原始碼"><i class="fa-brands fa-github"></i></a>', elem_id="ghlink")
            theme_btn = gr.Button("☾ 深色模式", size="sm", elem_id="theme-btn", scale=0, min_width=0)

        with gr.Row(elem_id="layout", equal_height=False):
            # ---------------- left: settings
            with gr.Column(elem_id="left", min_width=0):
                with gr.Column(elem_id="left-scroll", min_width=0):
                    gr.HTML('<h3 class="lbl">1 · HERMES 代理（OPENROUTER）</h3>')
                    api_key = gr.Textbox(label="API Key", type="password", placeholder="留空則用 Hermes 預設 Key")
                    err_key = gr.Markdown(visible=False, elem_classes="ferr")
                    model_label = f"代理模型 · {len(model_ids)} 個" + ("" if live else "（內建清單）")
                    model = gr.Dropdown(model_ids, value=config.DEFAULT_MODEL, label=model_label, allow_custom_value=True,
                                        filterable=True)
                    err_model = gr.Markdown(visible=False, elem_classes="ferr")

                    gr.HTML('<h3 class="lbl">2 · 實驗與測站資料</h3>')
                    root_box = gr.Textbox(str(config.rain_root()), label="實驗專案路徑")
                    err_root = gr.Markdown(visible=False, elem_classes="ferr")
                    run_name = gr.Textbox(label="實驗名稱", placeholder="例：竹子湖 第一次自動調參")
                    source = gr.Radio(SOURCES, value="existing", label="資料來源", elem_classes="seg")
                    station = gr.Dropdown(choices, value=default_station, label="測站", filterable=True)
                    upload = gr.File(label="測站 CSV（檔名含 6 碼站號）", file_types=[".csv"], type="filepath", visible=False)
                    upload_state = gr.State(None)
                    chip = gr.HTML()
                    err_file = gr.Markdown(visible=False, elem_classes="ferr")
                    split = gr.Radio(SPLITS, value="82", label="訓練／測試切分", elem_classes="seg")

                    gr.HTML('<h3 class="lbl">3 · 主目標 <span class="tok">[[MAIN_GOAL]]</span></h3>')
                    with gr.Row(elem_classes="pair"):
                        metric = gr.Dropdown(METRIC_CHOICES, value="mae", label="指標", min_width=0)
                        thr = gr.Number(value=40, label="實際雨量門檻 ≥ (mm)", minimum=0, min_width=0)
                    goal_key = gr.HTML()
                    err_goal = gr.Markdown(visible=False, elem_classes="ferr")

                    gr.HTML('<h3 class="lbl">4 · 副目標 <span class="tok">[[SUB_GOALS]]</span></h3>')
                    sub_mode = gr.Radio([("預設三種", "preset"), ("語意描述", "semantic")], value="preset", show_label=False,
                                        elem_classes="seg")
                    subs = gr.CheckboxGroup(SUB_CHOICES, value=list(SUBGOAL_ORDER), show_label=False, elem_classes="subs")
                    sub_text = gr.Textbox(visible=False, lines=3, show_label=False,
                                          placeholder="例：大雨時寧可高估也不要低估，整體誤差不能比原本差太多")
                    err_sub = gr.Markdown(visible=False, elem_classes="ferr")

                    gr.HTML('<h3 class="lbl">5 · 演化參數</h3>')
                    with gr.Row(elem_classes="pair"):
                        max_gen = gr.Number(value=20, label="最多代數 [[MAX_GEN]]", precision=0, min_width=0)
                        patience = gr.Number(value=3, label="早停 [[PATIENCE]]", precision=0, min_width=0)
                    with gr.Row(elem_classes="pair"):
                        children = gr.Number(value=8, label="每代子代 [[CHILDREN]]", precision=0, min_width=0)
                        parallel = gr.Number(value=3, label="同時訓練 [[PARALLEL]]", precision=0, min_width=0)
                    err_evo = gr.Markdown(visible=False, elem_classes="ferr")

                    with gr.Accordion("6 · 預覽", open=False, elem_id="preview"):
                        err_tpl = gr.Markdown(visible=False, elem_classes="ferr")
                        with gr.Tabs():
                            with gr.Tab("SKILL.md 模板"):
                                template = gr.Code(skill.DEFAULT_TEMPLATE, language="markdown", interactive=True,
                                                   show_label=False, lines=14)
                                tokens = gr.HTML()
                            with gr.Tab("Shell 指令"):
                                shell = gr.Code(language="shell", interactive=False, show_label=False)
                        download = gr.HTML(elem_id="dl")

                with gr.Column(elem_id="startbar"):
                    start = gr.Button("開始訓練", variant="primary", size="lg", elem_id="start-btn")
                    hit_state = gr.State("")

            # ---------------- middle: results / running
            with gr.Column(elem_id="main", min_width=0):
                with gr.Row(elem_id="viewbar"):
                    head = gr.HTML()
                    load_cfg = gr.Button("載入這次設定", size="sm", scale=0, min_width=0)
                    del_btn = gr.Button("刪除實驗", size="sm", scale=0, min_width=0, elem_id="del-btn")
                    stop_btn = gr.Button("停止實驗", size="sm", variant="stop", scale=0, min_width=0, visible=False)
                with gr.Row(visible=False, elem_id="del-confirm") as del_confirm:
                    del_text = gr.HTML()
                    del_yes = gr.Button("確定刪除", size="sm", scale=0, min_width=0, elem_id="del-yes")
                    del_no = gr.Button("取消", size="sm", scale=0, min_width=0)
                del_pending = gr.State(None)
                flow = gr.HTML(elem_id="flowbox")
                with gr.Group(visible=False, elem_classes="log-box") as log_group:
                    log = gr.Code(language=None, interactive=False, label="Hermes 輸出（最後 40 行）", lines=10)
                with gr.Column(visible=True, elem_id="result") as result_group:
                    sub_tabs = gr.Radio(view.sub_tab_choices(), value="under", show_label=False, elem_classes="subtabs")
                    stats_box = gr.HTML()
                    with gr.Group(elem_classes="card"):
                        gr.HTML('<div class="card-h"><h3>收斂圖</h3><span class="muted">訓練期 ≥ 40 mm MAE（mm）</span></div>')
                        conv_plot = gr.Plot(show_label=False, elem_classes="static-plot")
                    with gr.Group(elem_classes="card"):
                        gr.HTML('<div class="card-h"><h3>預測效果</h3><span class="muted">各副目標最佳基因的逐時預測</span></div>')
                        pred_split = gr.Radio(PRED_SPLITS, value="train", show_label=False, elem_classes="subtabs pad")
                        pred_plot = gr.Plot(show_label=False)
                        gr.HTML('<div class="plot-hint">拖曳框選放大、雙擊還原；下方滑桿可平移</div>')
                    with gr.Group(elem_classes="card"):
                        with gr.Row(elem_classes="card-h"):
                            gr.HTML("<h3>results.tsv</h3>")
                            gen = gr.Dropdown(["全部"], value="全部", show_label=False, scale=0, min_width=160)
                        table = gr.Dataframe(interactive=False, wrap=False, max_height=420, elem_classes="df")
                    with gr.Tabs(elem_classes="files"):
                        with gr.Tab("測站資訊卡"):
                            card_md = gr.Markdown(elem_classes="md")
                        with gr.Tab("學習紀錄"):
                            learn_md = gr.Markdown(elem_classes="md")
                        with gr.Tab("組合後 SKILL.md"):
                            skill_md = gr.Markdown(elem_classes="md")
                with gr.Group(elem_classes="card notes"):
                    gr.HTML('<div class="card-h"><h3>備註</h3><span class="muted">實驗結束後可以寫下觀察，存在介面的 runs/ 目錄</span></div>')
                    notes = gr.Textbox(show_label=False, lines=3, placeholder="例：α 偏高時低估少但高估多……")
                    save_notes = gr.Button("儲存備註", size="sm")

            # ---------------- right: history
            with gr.Column(elem_id="hist", min_width=0):
                gr.HTML('<h3 class="lbl">歷代實驗</h3>')
                hist_q = gr.Textbox(show_label=False, placeholder="搜尋站號或名稱…")
                hist = gr.HTML(view.history_html(view.history_items(), first_view))
                hist_key = gr.Textbox(elem_id="hist-key", show_label=False, container=False)
                hist_go = gr.Button("切換", elem_id="hist-go")

        footer = gr.HTML(footer_html())
        timer = gr.Timer(3.0)
        view_key = gr.State(first_view)

        # ---------------- wiring
        left_inputs = [api_key, model, run_name, source, station, upload_state, split, metric, thr, sub_mode, subs,
                       sub_text, max_gen, patience, children, parallel, template]
        left_outputs = [err_key, err_model, err_file, chip, err_goal, goal_key, err_sub, err_evo, err_tpl, tokens, shell,
                        start, hit_state, download]
        for comp in left_inputs:
            if comp is upload_state:
                continue
            comp.change(refresh_left, left_inputs, left_outputs, show_progress="hidden")
        source.change(on_source, source, [station, upload, upload_state]).then(
            refresh_left, left_inputs, left_outputs, show_progress="hidden")
        upload.change(on_upload, upload, upload_state).then(refresh_left, left_inputs, left_outputs, show_progress="hidden")
        sub_mode.change(on_sub_mode, sub_mode, [subs, sub_text])

        view_outputs = [head, log_group, flow, log, result_group, stats_box, conv_plot, pred_plot, gen, table, card_md,
                        learn_md, skill_md, notes, save_notes]

        def show(key, sub, psplit, g, query=""):
            return (key, *render_view(key, sub, psplit, g), *_view_buttons(key), history_update(query, key))

        def _view_buttons(key):
            kind, _, ident = (key or "").partition(":")
            run = runner.get_run(ident) if kind == "run" else None
            return gr.update(visible=bool(run and run["status"] == "running")), gr.update(visible=bool(key))

        full_outputs = [view_key, *view_outputs, stop_btn, load_cfg, hist]
        # 卡片點擊：JS 先把 key 寫進隱藏欄位，再按隱藏按鈕
        # 切換到別的實驗時，關掉還開著的刪除確認列並清掉待刪的目標，免得名稱對不上
        hide_delete = dict(fn=lambda: (gr.update(visible=False), None), inputs=None, outputs=[del_confirm, del_pending])
        hist_go.click(lambda k, s, p, q: show(k, s, p, "全部", q) if k else (gr.skip(),) * len(full_outputs),
                      [hist_key, sub_tabs, pred_split, hist_q], full_outputs).then(**hide_delete)
        sub_tabs.input(lambda k, s, p, q: show(k, s, p, "全部", q), [view_key, sub_tabs, pred_split, hist_q], full_outputs)
        pred_split.input(show, [view_key, sub_tabs, pred_split, gen, hist_q], full_outputs)
        gen.input(lambda k, s, g: _table_only(k, s, g), [view_key, sub_tabs, gen], table)
        hist_q.change(history_update, [hist_q, view_key], hist)

        def start_clicked(hit, api, *values):
            cfg, source_error = make_config(*values)
            if skill.blocking(skill.field_errors(cfg, api or "", source_error)):
                gr.Warning("有欄位格式不對，先修正再開始", duration=4)
                return gr.update()
            if hit:
                return hit
            return _launch(cfg, api, values)

        def _launch(cfg, api, values):
            upload_info = values[4]
            try:
                run = runner.start_run(cfg, api_key=api or "",
                                       upload_path=upload_info["path"] if values[2] == "upload" and upload_info else "")
            except (ValueError, RuntimeError, OSError) as exc:
                gr.Warning(str(exc), duration=4)
                return gr.update()
            return f"run:{run['id']}"

        after = dict(fn=lambda k, s, p, q: show(k, s, p, "全部", q), inputs=[view_key, sub_tabs, pred_split, hist_q],
                     outputs=full_outputs)
        start.click(start_clicked, [hit_state, api_key, *left_inputs[1:]], view_key).then(**after).then(
            footer_html, None, footer)

        def stop(key):
            kind, _, ident = (key or "").partition(":")
            if kind == "run":
                runner.stop_run(ident)
            return key
        stop_btn.click(stop, view_key, view_key).then(**after)

        def ask_delete(key):
            """先在頁面上顯示確認列，記下要刪的是哪一個；按「確定刪除」才真的刪。"""
            kind, _, ident = (key or "").partition(":")
            if kind == "run":
                run = runner.get_run(ident)
                what = f"實驗「{run['name']}」的介面紀錄（名稱、備註、Hermes 輸出）" if run else "這筆實驗紀錄"
            elif kind == "st" and ident:
                what = f"{stations.label(ident)} 的實驗結果（整個 outputs/{ident} 資料夾）"
            else:
                return gr.update(visible=False), "", None
            text = f'<div class="del-text">確定要刪除{html.escape(what)}嗎？此動作無法復原。</div>'
            return gr.update(visible=True), text, key
        del_btn.click(ask_delete, view_key, [del_confirm, del_text, del_pending])
        del_no.click(lambda: (gr.update(visible=False), None), None, [del_confirm, del_pending])

        def delete(key, query):
            """刪除確認列記下的那一項；之後主畫面改顯示清單第一項，測站選單與歷代實驗一起更新。"""
            kind, _, ident = (key or "").partition(":")
            if kind == "run":
                runner.delete_run(ident)
                gr.Info("已刪除這筆實驗紀錄", duration=4)
            elif kind == "st" and ident:
                gone = runner.delete_station(ident)
                gr.Info(f"已刪除 {stations.label(ident)} 的實驗結果" if gone else "這個測站沒有可刪除的實驗結果", duration=4)
            else:
                return (gr.skip(),) * (len(full_outputs) + 4)
            first = next((it["key"] for it in view.history_items()), None)
            return (*show(first, "under", "train", "全部", query), gr.update(choices=stations.station_choices()),
                    footer_html(), gr.update(visible=False), None)
        del_yes.click(delete, [del_pending, hist_q], [*full_outputs, station, footer, del_confirm, del_pending])

        def change_root(path, query, key):
            error = config.set_rain_root(path or "")
            results._load_live.cache_clear()
            choices = stations.station_choices()
            first = key if error else next((it["key"] for it in view.history_items()), None)
            return (gr.update(value=error, visible=bool(error)),
                    gr.update(choices=choices, value=choices[0][1] if choices else None),
                    *show(first, "under", "train", "全部", query), footer_html())
        root_box.submit(change_root, [root_box, hist_q, view_key], [err_root, station, *full_outputs, footer]).then(**hide_delete)
        root_box.blur(change_root, [root_box, hist_q, view_key], [err_root, station, *full_outputs, footer]).then(**hide_delete)

        def save(key, text):
            kind, _, ident = (key or "").partition(":")
            if kind == "run":
                runner.save_notes(ident, text)
            elif ident:
                runner.save_station_notes(ident, text)
            gr.Info("備註已儲存", duration=4)
        save_notes.click(save, [view_key, notes], None)

        def load_settings(key):
            kind, _, ident = (key or "").partition(":")
            run = runner.get_run(ident) if kind == "run" else None
            cfg = skill.RunConfig(**run["config"]) if run else skill.default_config(ident)
            known = {sid for _, sid in stations.station_choices()}
            gr.Info("已把設定載入左側", duration=4)
            return ("existing", gr.update(value=cfg.station if cfg.station in known else None, visible=True),
                    gr.update(value=None, visible=False), None, cfg.split, cfg.metric, cfg.threshold, cfg.sub_mode,
                    cfg.subgoals, cfg.sub_text, cfg.max_gen, cfg.patience, cfg.children, cfg.parallel, cfg.template,
                    cfg.run_name if run else "")
        load_cfg.click(load_settings, view_key,
                       [source, station, upload, upload_state, split, metric, thr, sub_mode, subs, sub_text, max_gen,
                        patience, children, parallel, template, run_name]).then(
            refresh_left, left_inputs, left_outputs, show_progress="hidden")

        def tick(key, sub, psplit, g, query):
            """有實驗在跑才更新；跑完那一刻重畫整個主畫面，結果就自動出現。"""
            running = [r for r in runner.load_runs() if r["status"] == "running"]
            if not running:
                return (gr.skip(),) * (len(full_outputs) + 1)
            for r in running:
                runner.poll(r["id"])
            return (*show(key, sub, psplit, g, query), footer_html())
        timer.tick(tick, [view_key, sub_tabs, pred_split, gen, hist_q], [*full_outputs, footer],
                   show_progress="hidden")

        demo.load(refresh_left, left_inputs, left_outputs)
        demo.load(**after)
    return demo


def _table_only(key, sub, gen):
    kind, _, ident = (key or "").partition(":")
    run = runner.get_run(ident) if kind == "run" else None
    station = results.load_station(run["station"] if run else ident)
    return results.results_table(station, sub, gen) if station else gr.update()


if __name__ == "__main__":
    build().queue().launch(favicon_path=str(ASSETS / "favicon.svg"), show_error=True,
                           allowed_paths=[str(config.state_dir())],
                           server_name=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"),
                           server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")))
