"""把 rain_autoresearch 的 outputs/<station>/ 轉成原型用的 data/experiments.js。

用法（在本 repo 根目錄）：
    python tools/build_data.py D:/rain_autoresearch/outputs 467590 467571 467490

只讀訓練期紀錄：station_card.md、learnings.md、ablation.tsv、control.json，
以及三種副目標的 convergence.csv 與 results.tsv。
"""
import csv
import json
import sys
from pathlib import Path

NAMES = {"467590": "恆春", "467490": "臺中"}
SUBGOALS = ["under", "total", "rmse"]


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
                      "over": num(x["count_over_ge20"]), "rmse": num(x["overall_rmse"]), "sec": num(x["runtime_sec"]),
                      "status": x["status"], "best": x["is_new_best"] == "true"} for x in rows],
        }
    return out


def main():
    root, ids = Path(sys.argv[1]), sys.argv[2:]
    data = {sid: station(root, sid) for sid in ids}
    dest = Path(__file__).resolve().parent.parent / "data" / "experiments.js"
    dest.write_text("// 由 tools/build_data.py 從 outputs/<station>/ 產生\nwindow.EXPERIMENTS = "
                    + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"wrote {dest} ({dest.stat().st_size:,} bytes, stations: {', '.join(ids)})")


if __name__ == "__main__":
    main()
