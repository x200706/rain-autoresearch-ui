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
        ("最佳模型整體 MAE", fmt(s["overall_mae"], 3),
         f"第 1 代 {fmt(s['g1'].get('overall_mae'), 3)}・對照 {fmt(s['control'].get('overall_mae'), 3)}"),
        ("最佳模型整體 RMSE", fmt(s["overall_rmse"], 3),
         f"第 1 代 {fmt(s['g1'].get('overall_rmse'), 3)}・對照 {fmt(s['control'].get('overall_rmse'), 3)}"),
    ]
    test = results.predictions(station["subgoals"][sub]["artifact"], "test")
    for thr in (10.0, 40.0):
        cards.append((f"測試集 ≥ {thr:g} mm POD / FAR", *pod_far_text(results.pod_far(test, thr))))
    body = "".join(f'<div class="stat"><span class="stat-k">{html.escape(k)}</span>'
                   f'<span class="stat-v{" stat-v-sm" if "/" in v else ""}">{html.escape(v)}</span>'
                   f'<span class="stat-s">{html.escape(sub_)}</span></div>' for k, v, sub_ in cards)
    note = ""
    if s["message"]:
        msg = (s["message"].replace("STOP: 3 consecutive generations without primary-objective progress", "連續 3 代主目標沒進步")
               .replace("STOP: ", ""))
        note = f'<div class="stop-note">停止原因：{html.escape(msg)}</div>'
    elif s["decision"] == "continue":
        note = '<div class="stop-note warn">這個副目標還沒跑完</div>'
    return f'<div class="stats">{body}</div>{note}'


def pod_far_text(m: dict | None) -> tuple[str, str]:
    """(卡片數字, 說明)：POD / FAR，說明寫觀測與命中的小時數。"""
    if m is None:
        return "–", "沒有測試集預測檔"
    pod = "–" if m["pod"] is None else f'{m["pod"]:.2f}'
    far = "–" if m["far"] is None else f'{m["far"]:.2f}'
    return f"{pod} / {far}", f'觀測 {m["observed"]} 小時、命中 {m["hits"]} 小時'


def conv_head_html(station: dict | None = None, sub: str = "") -> str:
    """收斂圖卡片標題；右側用文字寫代數與訓練次數。"""
    extra = ""
    if station is not None:
        s = results.stats(station, sub)
        extra = (f'<span class="muted conv-meta">{s["generations"] or "–"} 代・訓練 {s["runs"] or "–"} 次'
                 f'（實際訓練 {s["trained"]} 次）</span>')
    return f'<div class="card-h"><h3>收斂圖</h3><span class="muted">訓練期 ≥ 40 mm MAE（mm）</span>{extra}</div>'


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
    if source == "codis":
        if not upload:
            return '<div class="chip muted">尚未抓取</div>'
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
    cards = [
        (f"{target:%Y-%m-%d %H:00} 雨量預測", amount, f"第一階段判定{verdict}（LGBM 有雨機率 {info['rain_proba']:.2f}）"),
        ("同時段觀測", actual, "有歷史資料才會顯示"),
    ]
    body = "".join(f'<div class="stat{" stat-pred" if i == 0 else ""}"><span class="stat-k">{html.escape(k)}</span>'
                   f'<span class="stat-v">{html.escape(v)}</span>'
                   f'<span class="stat-s">{html.escape(s)}</span></div>' for i, (k, v, s) in enumerate(cards))
    note = "".join(f'<div class="stop-note warn">{html.escape(n)}</div>' for n in info.get("notes", []))
    if info.get("realtime_hours"):
        note += ('<div class="stop-note warn">⚠️ 缺值警告：今日的整點只有氣溫、溼度、氣壓、風與雨量，'
                 '其他欄位沿用昨日最後一筆（見下方模型輸入狀況）</div>')
    if info["has_rain"] and not info["lstm_available"]:
        note = (f'<div class="stop-note warn">判定有雨，但前 {info["time_step"]} 小時有雨量缺測，'
                '第二階段無法預測雨量，暫以 0 mm 表示</div>')
    return f'<div class="stats">{body}</div>{note}'


def forecast_model_md(spec: dict) -> str:
    return (f"{stations.label(spec['station'])}，副目標「{SUBGOALS[spec['subgoal']]['short']}」的最佳基因 "
            f"{spec['run']}（{spec['lstm_layers']} 層 × {spec['lstm_units']} 單元、序列 {spec['time_step']} 小時、"
            f"α = {spec['wmae_alpha']}）")


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
