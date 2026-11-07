"""讀 outputs/<station>/ 的實驗結果（只讀）。找不到 rain_autoresearch 時改讀原型附的 data/experiments.js。"""
import csv
import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config
from .stations import SUBGOAL_ORDER, label

NUMERIC = ("mae_ge40mm", "count_under_ge20", "count_over_ge20", "count_big_ge20", "overall_rmse", "overall_mae")


def num(value):
    try:
        return None if value in ("", "NA", None) else float(value)
    except (TypeError, ValueError):
        return None


def _tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines(), delimiter="\t"))


def run_label(row: dict) -> str:
    return f"g{int(row['generation']):02d}_c{int(row['candidate'])}"


def _stamp(station: str) -> float:
    """快取鍵：這個測站任何紀錄檔改動，都會讓下一次讀取重新載入。"""
    sd = config.outputs_dir() / station
    files = [sd / "ablation.tsv", sd / "learnings.md", sd / "control.json"]
    files += [sd / f"subgoal_{s}" / "results.tsv" for s in SUBGOAL_ORDER]
    return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)


def load_station(station: str) -> dict | None:
    if (config.outputs_dir() / station).exists():
        return _load_live(station, _stamp(station), str(config.outputs_dir()))
    return load_bundle().get(station)


@lru_cache(maxsize=32)
def _load_live(station: str, _stamp_value: float, _root: str) -> dict:
    sd = config.outputs_dir() / station
    read = lambda name: (sd / name).read_text(encoding="utf-8") if (sd / name).exists() else ""
    control = json.loads(read("control.json") or "{}")
    ablation = _tsv(sd / "ablation.tsv")
    out = {"id": station, "label": label(station), "split": "82", "card": read("station_card.md"),
           "learnings": read("learnings.md"), "control": control, "ablation": ablation, "subgoals": {}, "live": True}
    by_sub = {a["subgoal"]: a for a in ablation}
    for s in SUBGOAL_ORDER:
        sdir = sd / f"subgoal_{s}"
        rows = _tsv(sdir / "results.tsv")
        conv = [{"g": int(c["generation"]), "pass": num(c.get("gen_min_mae_ge40mm_guard_pass")),
                 "best": num(c.get("best_so_far_mae_ge40mm"))} for c in _tsv_csv(sdir / "convergence.csv")]
        best = by_sub.get(s, {}).get("best_run") or next(
            (run_label(r) for r in reversed(rows) if r.get("is_new_best") == "true"), "")
        best_row = next((r for r in rows if run_label(r) == best), None)
        out["subgoals"][s] = {
            "rows": rows, "conv": conv, "best_run": best,
            "decision": by_sub.get(s, {}).get("decision") or ("" if not rows else "continue"),
            "message": by_sub.get(s, {}).get("message", ""),
            "best_row": best_row,
            "artifact": str(config.rain_root() / best_row["artifact_dir"]) if best_row else "",
        }
    # 第 1 代與對照組，供數字卡比較
    g1 = next(iter(out["subgoals"]["under"]["rows"]), None)
    out["generation1"] = {k: num(g1.get(k)) for k in NUMERIC} if g1 else {}
    out["control_metrics"] = {k: num(control.get(k)) for k in NUMERIC}
    return out


def _tsv_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))


@lru_cache(maxsize=1)
def load_bundle() -> dict:
    """data/experiments.js（GitHub Pages 原型的資料）轉成與即時資料相同的形狀。"""
    path = config.bundle_path()
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    data = json.loads(text[text.index("=") + 1:].strip().rstrip(";"))
    out = {}
    for sid, e in data.items():
        by_sub = {a["subgoal"]: a for a in e.get("ablation", [])}
        station = {"id": sid, "label": label(sid), "split": e.get("split", "82"), "card": e.get("card", ""),
                   "learnings": e.get("learnings", ""), "control": e.get("control", {}),
                   "ablation": e.get("ablation", []), "subgoals": {}, "live": False}
        for s in SUBGOAL_ORDER:
            sg = e["subgoals"][s]
            rows = [{"generation": str(r["g"]), "candidate": str(r["c"]), "genome": r["genome"], "cache_of": r["cache"],
                     "LSTM_LAYERS": r["L"], "LSTM_UNITS": r["U"], "TIME_STEP": r["TS"], "BATCH_SIZE": r["B"],
                     "WMAE_ALPHA": r["a"], "mae_ge40mm": r["mae"], "count_under_ge20": r["under"],
                     "count_over_ge20": r["over"], "overall_rmse": r["rmse"], "overall_mae": r.get("maeAll"),
                     "status": r["status"], "is_new_best": "true" if r.get("best") else "false"} for r in sg["rows"]]
            best = by_sub.get(s, {}).get("best_run", "")
            station["subgoals"][s] = {"rows": rows, "conv": sg["conv"], "best_run": best,
                                      "decision": by_sub.get(s, {}).get("decision", ""),
                                      "message": by_sub.get(s, {}).get("message", ""),
                                      "best_row": next((r for r in rows if run_label(r) == best), None),
                                      # build_data.py 複製的預測檔（相對於本 repo）；舊版資料沒有這欄
                                      "artifact": str(config.UI_ROOT / sg["artifact"]) if sg.get("artifact") else ""}
        g1 = by_sub.get("generation1", {})
        station["generation1"] = {k: num(g1.get(k)) for k in NUMERIC}
        ctl = by_sub.get("control", {})
        station["control_metrics"] = {k: num(ctl.get(k)) for k in NUMERIC}
        out[sid] = station
    return out


def stats(station: dict, sub: str) -> dict:
    """數字卡需要的值（副目標的 best 對照第 1 代與對照組）。"""
    sg = station["subgoals"][sub]
    best = sg["best_row"] or {}
    by_sub = {a["subgoal"]: a for a in station.get("ablation", [])}
    ab = by_sub.get(sub, {})
    rows = sg["rows"]
    return {
        "best_run": sg["best_run"] or "–",
        "mae": num(best.get("mae_ge40mm")), "overall_mae": num(best.get("overall_mae")),
        "overall_rmse": num(best.get("overall_rmse")),
        "g1": station.get("generation1", {}), "control": station.get("control_metrics", {}),
        "generations": int(ab["generations"]) if ab.get("generations") else (max((int(r["generation"]) for r in rows), default=0)),
        "runs": int(ab["runs"]) if ab.get("runs") else len(rows),
        "trained": int(ab["trained_runs"]) if ab.get("trained_runs") else sum(1 for r in rows if not r.get("cache_of")),
        "guard_fail": sum(1 for r in rows if r.get("status") == "guard_fail"),
        "message": sg.get("message", ""), "decision": sg.get("decision", ""),
    }


def results_table(station: dict, sub: str, generation: str = "全部") -> pd.DataFrame:
    sg = station["subgoals"][sub]
    best = sg["best_run"]
    records = []
    for r in sg["rows"]:
        if generation != "全部" and f"第 {int(r['generation'])} 代" != generation:
            continue
        lb = run_label(r)
        alpha = r.get("WMAE_ALPHA")
        status = "★ best" if lb == best else (f"快取 {re.sub(r'^subgoal_', '', r['cache_of'])}" if r.get("cache_of")
                                              else {"guard_fail": "副目標攔截", "ok": "通過", "best": "當時最佳",
                                                    "baseline": "基準", "crash": "失敗"}.get(r.get("status"), r.get("status", "")))
        records.append({
            "run": lb, "層": r.get("LSTM_LAYERS"), "單元": r.get("LSTM_UNITS"), "步長": r.get("TIME_STEP"),
            "批次": r.get("BATCH_SIZE"), "α": "WMAE 原始研究" if alpha in ("NA", None, "") else alpha,
            "MAE≥40": _fmt(r.get("mae_ge40mm"), 2), "低估": _fmt(r.get("count_under_ge20"), 0),
            "高估": _fmt(r.get("count_over_ge20"), 0), "整體 MAE": _fmt(r.get("overall_mae"), 3),
            "整體 RMSE": _fmt(r.get("overall_rmse"), 3), "狀態": status,
        })
    return pd.DataFrame.from_records(records, columns=["run", "層", "單元", "步長", "批次", "α", "MAE≥40", "低估", "高估",
                                                       "整體 MAE", "整體 RMSE", "狀態"])


def generation_choices(station: dict, sub: str) -> list[str]:
    gens = sorted({int(r["generation"]) for r in station["subgoals"][sub]["rows"]})
    return ["全部"] + [f"第 {g} 代" for g in gens]


def ablation_table(station: dict) -> pd.DataFrame:
    keep = ["subgoal", "decision", "runs", "trained_runs", "guard_fail_runs", "generations", "best_run", "mae_ge40mm",
            "count_under_ge20", "count_over_ge20", "overall_mae", "overall_rmse"]
    rows = []
    for a in station.get("ablation", []):
        row = {k: a.get(k, "") for k in keep}
        if not row["overall_mae"]:
            row["overall_mae"] = _overall_mae(station, a)
        for k in ("mae_ge40mm", "overall_mae", "overall_rmse"):
            row[k] = _fmt(row[k], 3)
        rows.append(row)
    return pd.DataFrame.from_records(rows, columns=keep)


def _overall_mae(station: dict, a: dict) -> str:
    if a.get("subgoal") == "control":
        return str(station.get("control", {}).get("overall_mae", ""))
    sub = "under" if a.get("subgoal") == "generation1" else a.get("subgoal")
    sg = station["subgoals"].get(sub)
    row = next((r for r in sg["rows"] if run_label(r) == a.get("best_run")), None) if sg else None
    return str(row.get("overall_mae", "")) if row else ""


def _fmt(value, digits):
    v = num(value)
    if v is None:
        return "NA"
    return str(int(round(v))) if digits == 0 else f"{v:.{digits}f}"


def predictions(artifact: str, split: str) -> pd.DataFrame | None:
    """best run 的逐時預測。連續都是 0 的時段只留頭尾兩點，畫出來的線與原始資料一樣，資料量少很多。"""
    if not artifact:
        return None
    name = f"{split}_two_stage_predictions.csv"
    path = Path(artifact) / "predictions" / name
    if not path.exists():
        path = Path(artifact) / name                        # 展示資料：data/predictions/<station>/<run>/
    if not path.exists():
        return None
    return _predictions(str(path), path.stat().st_mtime)


@lru_cache(maxsize=12)
def _predictions(path: str, _mtime: float) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=["datetime", "actual", "pred"], encoding="utf-8-sig")
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    return compress_zero_runs(frame)


def compress_zero_runs(frame: pd.DataFrame) -> pd.DataFrame:
    zero = (frame["actual"] == 0) & (frame["pred"] == 0)
    inner = zero & zero.shift(1, fill_value=False) & zero.shift(-1, fill_value=False)
    return frame[~inner].reset_index(drop=True)
