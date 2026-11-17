"""把資料轉成畫面片段（HTML 字串、清單）。不碰 Gradio，方便單元測試。"""
import html
import time

import pandas as pd

from . import config, results, runner, skill, stations
from .stations import SUBGOALS

STATUS_TEXT = {"running": "執行中", "done": "完成", "failed": "失敗", "stopped": "已停止"}


def fmt(value, digits=2) -> str:
    return "NA" if value is None else f"{value:.{digits}f}"


def stats_html(station: dict, sub: str) -> str:
    s = results.stats(station, sub)
    beat = s["best_run"] not in ("g01_c1", "–")
    cards = [
        ("最佳 ≥ 40 mm MAE", fmt(s["mae"]), s["best_run"] + ("" if beat else "（未勝過第 1 代）")),
        # 數字是 ≥ 40 mm MAE，卡片標題要寫出來，不然看不出 18.55 是什麼
        ("未經較佳化兩階段分類器對照 ≥ 40 mm MAE", fmt(s["g1"].get("mae_ge40mm")),
         "純 MAE 對照組 ≥ 40 mm MAE " + fmt(s["control"].get("mae_ge40mm"))),
        ("整體 MAE", fmt(s["overall_mae"], 3),
         f"第 1 代 {fmt(s['g1'].get('overall_mae'), 3)}・對照 {fmt(s['control'].get('overall_mae'), 3)}"),
        ("整體 RMSE", fmt(s["overall_rmse"], 3),
         f"第 1 代 {fmt(s['g1'].get('overall_rmse'), 3)}・對照 {fmt(s['control'].get('overall_rmse'), 3)}"),
        ("代數", str(s["generations"] or "–"), ""),
        ("訓練次數", str(s["runs"] or "–"), f"實際訓練 {s['trained']} 次"),
    ]
    body = "".join(f'<div class="stat"><span class="stat-k">{html.escape(k)}</span><span class="stat-v">{html.escape(v)}</span>'
                   f'<span class="stat-s">{html.escape(sub_)}</span></div>' for k, v, sub_ in cards)
    note = ""
    if s["message"]:
        msg = (s["message"].replace("STOP: 3 consecutive generations without primary-objective progress", "連續 3 代主目標沒進步")
               .replace("STOP: ", ""))
        note = f'<div class="stop-note">停止原因：{html.escape(msg)}</div>'
    elif s["decision"] == "continue":
        note = '<div class="stop-note warn">這個副目標還沒跑完</div>'
    return f'<div class="stats">{body}</div>{note}'


def header_html(title: str, pill: str, meta: str, pill_kind: str = "ok") -> str:
    return (f'<div class="view-head"><h2>{html.escape(title)}</h2>'
            f'<span class="pill pill-{pill_kind}">{html.escape(pill)}</span><span class="muted">{html.escape(meta)}</span></div>')


STATUS_KIND = {"running": "run", "done": "ok", "failed": "err", "stopped": "err"}


def history_items(query: str = "") -> list[dict]:
    """右側歷代實驗：介面啟動過的實驗（含名稱與狀態）在前，做過的測站在後。
    每項：key、title、tags[(文字, 種類)]；搜尋比對名稱、站號與站名。"""
    items = []
    for run in runner.load_runs():
        when = time.strftime("%m-%d %H:%M", time.localtime(run["started"]))
        status = STATUS_TEXT.get(run["status"], run["status"])
        kind = STATUS_KIND.get(run["status"], "muted")
        if run["mode"] == "demo":
            status, kind = ("展示中", "run") if run["status"] == "running" else ("展示", "muted")
        tags = [(stations.label(run["station"]), "station"), (status, kind), (when, "muted")]
        if run.get("resumes"):
            tags.insert(2, (f"第 {run['resumes']} 次接續", "muted"))
        items.append({"key": f"run:{run['id']}", "title": run["name"], "tags": tags})
    started = [sid for _, sid in stations.station_choices() if (config.outputs_dir() / sid).exists()]
    entries = [(sid, results.load_station(sid), stations.is_complete(sid)) for sid in started]
    if not started:                                          # 沒有 rain_autoresearch：顯示原型附的資料
        entries = [(sid, st, True) for sid, st in results.load_bundle().items()]
    for sid, station, complete in entries:
        best = results.stats(station, "under")["mae"] if station else None
        items.append({"key": f"st:{sid}", "title": stations.label(sid),
                      "tags": [("完成" if complete else "未完成", "ok" if complete else "warn"),
                               (f"best {fmt(best)} mm", "muted")]})
    q = query.strip()
    return [it for it in items if not q or q in it["title"] + " ".join(t for t, _ in it["tags"])]


def history_html(items: list[dict], selected: str | None) -> str:
    """標籤卡片；點擊由頁面上的 JS 把 data-hist 寫進隱藏欄位，再交給 Python。"""
    if not items:
        return '<div class="hist-empty muted">沒有符合的實驗</div>'
    cards = []
    for it in items:
        tags = "".join(f'<span class="tag tag-{kind}">{html.escape(text)}</span>' for text, kind in it["tags"])
        current = ' aria-current="true"' if it["key"] == selected else ""
        cards.append(f'<button type="button" class="hist-card" data-hist="{html.escape(it["key"])}"{current}>'
                     f'<span class="hist-title">{html.escape(it["title"])}</span><span class="hist-tags">{tags}</span></button>')
    return f'<div class="hist-list">{"".join(cards)}</div>'


def cache_index() -> dict:
    """設定指紋 → 可直接展示的結果。已完成的測站用 program.md 預設設定，介面跑完的實驗用當時的設定。"""
    index = {}
    for sid in stations.completed_stations() or list(results.load_bundle()):
        index[skill.fingerprint(skill.default_config(sid))] = f"st:{sid}"
    for run in runner.load_runs():
        if run["mode"] == "real" and run["status"] == "done":
            index.setdefault(skill.fingerprint(skill.RunConfig(**run["config"])), f"run:{run['id']}")
    return index


def file_chip(source: str, station: str, upload: dict | None, threshold: float) -> str:
    if source in ("upload", "nchu"):
        if not upload:
            return f'<div class="chip muted">{"尚未下載" if source == "nchu" else "尚未上傳"}</div>'
        mark, cls = ("✓", "ok") if not upload["errors"] else ("✕", "err")
        rows = f'{upload["rows"]:,} 小時' if upload["rows"] else ""
        extra = ""
        if upload["station"] and stations.is_complete(upload["station"]):
            extra = '<span class="muted">此站已有結果</span>'
        return (f'<div class="chip"><b class="{cls}">{mark}</b><span class="grow">{html.escape(upload["name"])}</span>'
                f'{extra}<span class="muted">{rows}</span></div>')
    if not station:
        return '<div class="chip muted">尚未選擇測站</div>'
    return f'<div class="chip"><b class="ok">✓</b><span class="grow">data/{html.escape(station)}.csv</span></div>'


def tokens_html(template: str) -> str:
    return " ".join(f'<span class="tok{"" if f"[[{t}]]" in template else " tok-off"}">{t}</span>' for t in skill.TOKENS)


def sub_tab_choices() -> list[tuple[str, str]]:
    return [(SUBGOALS[s]["tab"], s) for s in stations.SUBGOAL_ORDER]


def forecast_html(info: dict, spec: dict) -> str:
    """線上預測的結果卡片、模型說明與資料來源。"""
    target = info["target"]
    actual = "尚無觀測" if info["actual"] is None else f'{info["actual"]:.1f} mm'
    verdict = "有雨" if info["has_rain"] else "無雨"
    amount = f'{info["pred"]:.1f} mm' if info["has_rain"] else "0 mm"
    metric = {m["threshold"]: m for m in spec.get("test_metrics", [])}

    def pf(thr):
        m = metric.get(thr)
        if not m:
            return "–"
        far = "–" if m["far"] is None else f'{m["far"]:.2f}'
        return f'{m["pod"]:.2f} / {far}'
    cards = [
        (f"{target:%Y-%m-%d %H:00} 雨量預測", amount, f"第一階段判定{verdict}（有雨機率 {info['rain_proba']:.2f}）"),
        ("同時段觀測", actual, "CoDiS 有這一小時的資料才會顯示"),
        ("使用的觀測", f'{info["hours_fetched"]} 小時',
         f'{info["fetched_from"]:%m-%d %H:%M} 到 {target - pd.Timedelta(hours=1):%m-%d %H:%M}'
         + (f'，其中今天 {info["realtime_hours"]} 小時來自開放資料' if info.get("realtime_hours") else "")),
        ("測試集 ≥ 10 mm POD / FAR", pf(10.0), "2023–2025 逐時，參考用"),
        ("測試集 ≥ 40 mm POD / FAR", pf(40.0), "2023–2025 逐時，參考用"),
    ]
    body = "".join(f'<div class="stat"><span class="stat-k">{html.escape(k)}</span>'
                   f'<span class="stat-v{" stat-v-sm" if "/" in v else ""}">{html.escape(v)}</span>'
                   f'<span class="stat-s">{html.escape(s)}</span></div>' for k, v, s in cards)
    note = "".join(f'<div class="stop-note warn">{html.escape(n)}</div>' for n in info.get("notes", []))
    if info.get("realtime_hours"):
        note += ('<div class="stop-note">今天的整點來自氣象署開放資料，只有氣溫、溼度、氣壓、風、陣風與雨量；'
                 '露點由氣溫與溼度算出，其他欄位沿用 CoDiS 昨天最後一筆（見下方資料來源）</div>')
    if info["has_rain"] and not info["lstm_available"]:
        note = (f'<div class="stop-note warn">判定有雨，但前 {info["time_step"]} 小時有雨量缺測，'
                '第二階段無法預測雨量，暫以 0 mm 表示</div>')
    return f'<div class="stats">{body}</div>{note}'


def forecast_model_md(spec: dict) -> str:
    return (f"**模型**：{stations.label(spec['station'])}，副目標「{SUBGOALS[spec['subgoal']]['short']}」的最佳基因 "
            f"{spec['run']}（{spec['lstm_layers']} 層 × {spec['lstm_units']} 單元、序列 {spec['time_step']} 小時、"
            f"α = {spec['wmae_alpha']}）。\n\n"
            "**流程**：輸入時間 T 後，當場抓 T 之前的逐時觀測（昨天以前來自 CoDiS，今天的整點來自氣象署開放資料），照訓練時的前處理組成特徵，"
            "第一階段雙 LightGBM 判斷 T 有沒有雨，判定有雨才由 LSTM 用前 "
            f"{spec['time_step']} 小時估雨量。資料不存檔。\n\n"
            f"打包時已用同一套程式重算 {spec['verification']['test_hours']:,} 小時的測試集，與實驗輸出一致。")


def coverage_rows(info: dict, spec: dict) -> list[list]:
    """gate 與 LSTM 需要的原始欄位，在抓到的資料裡有值的比例；沒有的欄位會用訓練資料的最後觀測或中位數補。"""
    from . import codis, predict
    names = {predict.COL_MAPPING.get(c, c): c for c in codis.COLUMNS}     # 訓練用名稱 → CoDiS 轉出的欄名
    cov = info["column_coverage"]
    rows = []
    for col in predict.gate_raw_columns(spec["gate_features"]) + ["WD02", "WD08"]:
        src = names.get(col, col)
        share = cov.get(src)
        used = "LSTM＋分類器" if col in spec["lstm_features"] or f"{col}_sin" in spec["lstm_features"] else "分類器"
        if share is None:
            status = "CoDiS 沒有此欄，沿用訓練資料最後觀測／中位數"
        elif share == 0:
            status = "這段時間都缺測，沿用訓練資料最後觀測／中位數"
        elif share >= 1:
            status = "每小時都有值"
        else:
            status = f"{share:.0%} 小時有值，缺的照訓練規則插值、向前填"
        rows.append([src, used, status])
    return rows
