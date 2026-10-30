"""把 rain_autoresearch 的 outputs/<station>/ 轉成原型用的 data/experiments.js。

用法（在本 repo 根目錄）：
    python tools/build_data.py D:/rain_autoresearch/outputs 466910 467490 467571 467590 467650

讀 station_card.md、learnings.md、ablation.tsv、control.json，
以及三種副目標的 convergence.csv 與 results.tsv（皆為訓練期指標）。
另把每種副目標 best run 的預測圖（訓練集、測試集與測試集局部放大）
複製到 data/plots/<station>/，這些圖是全部停止後才產生的最終評估。
"""
import csv
import json
import shutil
import sys
from pathlib import Path

NAMES = {"466910": "鞍部", "467490": "臺中", "467571": "新竹", "467590": "恆春", "467650": "日月潭"}
SUBGOALS = ["under", "total", "rmse"]
DEST = Path(__file__).resolve().parent.parent / "data"
# (標籤, 檔名樣式)；局部放大的日期區間依測站而定，用 glob 找
PLOTS = [("訓練集全期", "train_full_prediction.png"), ("測試集全期", "test_full_prediction.png"),
         ("測試集局部放大", "test_20*_prediction.png"), ("測試集最後兩個月", "test_last_two_months_prediction.png")]


def num(v):
    return None if v in ("", "NA", None) else float(v)


def station(root: Path, sid: str) -> dict:
    d = root / sid
    read = lambda p: (d / p).read_text(encoding="utf-8")
    out = {
        "id": sid, "name": NAMES.get(sid, ""), "split": "82",
        "card": read("station_card.md"), "learnings": read("learnings.md"),
        "ablationText": read("ablation.tsv"),
        "control": json.loads(read("control.json")),
        "ablation": list(csv.DictReader(read("ablation.tsv").splitlines(), delimiter="\t")),
        "subgoals": {},
    }
    for s in SUBGOALS:
        sd = d / f"subgoal_{s}"
        conv = list(csv.DictReader((sd / "convergence.csv").read_text(encoding="utf-8").splitlines()))
        rows = list(csv.DictReader((sd / "results.tsv").read_text(encoding="utf-8").splitlines(), delimiter="\t"))
        out["subgoals"][s] = {
            "conv": [{"g": int(c["generation"]), "pass": num(c["gen_min_mae_ge40mm_guard_pass"]),
                      "best": float(c["best_so_far_mae_ge40mm"]), "progress": c["progress"] == "True"} for c in conv],
            "rows": [{"g": int(x["generation"]), "c": int(x["candidate"]), "genome": x["genome"], "cache": x["cache_of"],
                      "L": x["LSTM_LAYERS"], "U": x["LSTM_UNITS"], "TS": x["TIME_STEP"], "B": x["BATCH_SIZE"],
                      "a": x["WMAE_ALPHA"], "mae": num(x["mae_ge40mm"]), "under": num(x["count_under_ge20"]),
                      "over": num(x["count_over_ge20"]), "rmse": num(x["overall_rmse"]), "maeAll": num(x["overall_mae"]),
                      "sec": num(x["runtime_sec"]), "status": x["status"], "best": x["is_new_best"] == "true"} for x in rows],
        }
    # 每種副目標 best run 的預測圖；沿用快取的 run 圖在 artifact_dir（可能在別的副目標底下）
    for s in SUBGOALS:
        best = next(a["best_run"] for a in out["ablation"] if a["subgoal"] == s)
        g, c = (int(v) for v in best[1:].split("_c"))
        rows = csv.DictReader((d / f"subgoal_{s}" / "results.tsv").read_text(encoding="utf-8").splitlines(), delimiter="	")
        art = next(x["artifact_dir"] for x in rows if int(x["generation"]) == g and int(x["candidate"]) == c)
        src = root.parent / art / "plots"
        key = "_".join(Path(art).parts[2:]).replace("_experiments", "")
        plots = []
        for label, pat in PLOTS:
            f = next(iter(sorted(src.glob(pat))), None)
            if f is None:
                continue
            rel = Path("plots") / sid / key / f.name
            (DEST / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, DEST / rel)
            plots.append({"label": label, "src": "data/" + rel.as_posix(), "run": best})
        out["subgoals"][s]["plots"] = plots
    # ablation.tsv 沒記 overall_mae：從 control.json 或該副目標 results.tsv 的 best_run 補上
    def run_mae(sub, run):
        g, c = (int(v) for v in run[1:].split("_c"))
        return next((r["maeAll"] for r in out["subgoals"][sub]["rows"] if r["g"] == g and r["c"] == c), None)
    for a in out["ablation"]:
        if a["subgoal"] == "control":
            v = out["control"].get("overall_mae")
        else:
            v = run_mae("under" if a["subgoal"] == "generation1" else a["subgoal"], a["best_run"])
        a["overall_mae"] = "" if v is None else repr(v)
    cols = list(out["ablation"][0].keys())
    cols.remove("overall_mae")
    cols.insert(cols.index("overall_rmse"), "overall_mae")
    out["ablationText"] = "\n".join(["\t".join(cols)] + ["\t".join(a[k] or "" for k in cols) for a in out["ablation"]]) + "\n"
    return out


def main():
    root, ids = Path(sys.argv[1]), sys.argv[2:]
    data = {sid: station(root, sid) for sid in ids}
    dest = DEST / "experiments.js"
    dest.write_text("// 由 tools/build_data.py 從 outputs/<station>/ 產生\nwindow.EXPERIMENTS = "
                    + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"wrote {dest} ({dest.stat().st_size:,} bytes, stations: {', '.join(ids)})")


if __name__ == "__main__":
    main()
