"""把資料轉成畫面片段（HTML 字串、清單）。不碰 Gradio，方便單元測試。"""
import html
import time

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
        ("未經較佳化兩階段分類器對照", fmt(s["g1"].get("mae_ge40mm")),
         "純 MAE 對照組 " + fmt(s["control"].get("mae_ge40mm"))),
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
        items.append({"key": f"run:{run['id']}", "title": run["name"],
                      "tags": [(stations.label(run["station"]), "station"), (status, kind), (when, "muted")]})
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
    if source == "upload":
        if not upload:
            return '<div class="chip muted">尚未上傳</div>'
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
