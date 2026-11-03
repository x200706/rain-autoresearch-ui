"""每個測試都在暫存的 rain_autoresearch 目錄裡跑，不碰真正的實驗紀錄。"""
import json
import sys
from pathlib import Path

import pytest

UI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_ROOT))

RESULT_COLUMNS = ["generation", "candidate", "genome", "cache_of", "artifact_dir", "LSTM_LAYERS", "LSTM_UNITS", "TIME_STEP",
                  "BATCH_SIZE", "WMAE_ALPHA", "mae_ge40mm", "count_under_ge20", "count_over_ge20", "count_big_ge20",
                  "overall_rmse", "overall_mae", "status", "is_new_best"]


def write_tsv(path: Path, header: list, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(header)] + ["\t".join(str(r.get(h, "")) for h in header) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_csv(path: Path, rain=(0, 0, 45, 12, 0), header=("觀測時間(hour)", "降水量(mm)")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header)] + [f"2020-01-01 {i:02d}:00,{v}" for i, v in enumerate(rain)]
    path.write_text("﻿" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_station(root: Path, sid: str, complete: bool = True) -> Path:
    """一個做完（或做到一半）的假測站：三種副目標各兩代、預測檔、消融表與學習紀錄。"""
    sd = root / "outputs" / sid
    (sd / "experiments" / "g00_gate").mkdir(parents=True)
    (sd / "gate.json").write_text("{}", encoding="utf-8")
    (sd / "station_card.json").write_text("{}", encoding="utf-8")
    (sd / "station_card.md").write_text(f"# 測站資訊卡：{sid}\n\n| 項目 | 數值 |\n|---|---|\n| ≥ 40 mm 時數 | 3 |\n", encoding="utf-8")
    (sd / "control.json").write_text(json.dumps({"mae_ge40mm": 40.0, "overall_rmse": 1.5, "overall_mae": 0.2}),
                                     encoding="utf-8")
    ablation = [{"subgoal": "generation1", "best_run": "g01_c1", "mae_ge40mm": 30.0, "overall_rmse": 2.0},
                {"subgoal": "control", "best_run": "control_mae", "mae_ge40mm": 40.0, "overall_rmse": 1.5}]
    for s in ("under", "total", "rmse"):
        sdir = sd / f"subgoal_{s}"
        art = sdir / "experiments" / "g02_c1"
        (art / "metrics").mkdir(parents=True)
        (art / "metrics" / "result.json").write_text("{}", encoding="utf-8")
        preds = "datetime,actual,feature_index,pred\n" + "".join(
            f"2020-01-01 {h:02d}:00,{a},{h},{p}\n" for h, (a, p) in enumerate([(0, 0), (0, 0), (0, 0), (5, 3), (0, 0), (0, 0)]))
        (art / "predictions").mkdir()
        for split in ("train", "test"):
            (art / "predictions" / f"{split}_two_stage_predictions.csv").write_text(preds, encoding="utf-8")
        rows = [
            {"generation": 1, "candidate": 1, "genome": "0" * 14, "artifact_dir": f"outputs/{sid}/subgoal_{s}/experiments/g01_c1",
             "LSTM_LAYERS": 2, "LSTM_UNITS": 96, "TIME_STEP": 6, "BATCH_SIZE": 32, "WMAE_ALPHA": "NA", "mae_ge40mm": 30.0,
             "count_under_ge20": 50, "count_over_ge20": 20, "count_big_ge20": 70, "overall_rmse": 2.0, "overall_mae": 0.5,
             "status": "baseline", "is_new_best": "true"},
            {"generation": 2, "candidate": 1, "genome": "1" * 14, "artifact_dir": f"outputs/{sid}/subgoal_{s}/experiments/g02_c1",
             "LSTM_LAYERS": 4, "LSTM_UNITS": 256, "TIME_STEP": 24, "BATCH_SIZE": 512, "WMAE_ALPHA": 1.5, "mae_ge40mm": 12.0,
             "count_under_ge20": 10, "count_over_ge20": 900, "count_big_ge20": 910, "overall_rmse": 3.5, "overall_mae": 0.9,
             "status": "best", "is_new_best": "true"},
        ]
        write_tsv(sdir / "results.tsv", RESULT_COLUMNS, rows)
        (sdir / "convergence.csv").write_text(
            "generation,gen_min_mae_ge40mm_guard_pass,best_so_far_mae_ge40mm\n1,30.0,30.0\n2,12.0,12.0\n", encoding="utf-8")
        ablation.append({"subgoal": s, "decision": "stop" if complete or s != "rmse" else "continue",
                         "message": "STOP: 3 consecutive generations without primary-objective progress", "runs": 2,
                         "trained_runs": 2, "guard_fail_runs": 0, "generations": 2, "best_run": "g02_c1",
                         "mae_ge40mm": 12.0, "overall_rmse": 3.5})
    write_tsv(sd / "ablation.tsv", ["subgoal", "rule", "decision", "message", "runs", "trained_runs", "guard_fail_runs",
                                    "generations", "best_run", "mae_ge40mm", "count_under_ge20", "count_over_ge20",
                                    "overall_rmse"], ablation)
    (sd / "learnings.md").write_text("# 學習紀錄\n只用訓練期指標。\n", encoding="utf-8")
    return sd


@pytest.fixture()
def rain_root(tmp_path, monkeypatch):
    root = tmp_path / "rain_autoresearch"
    (root / "data").mkdir(parents=True)
    (root / "outputs").mkdir()
    (root / "program.md").write_text("# 規則\n", encoding="utf-8")
    monkeypatch.setenv("RAIN_AUTORESEARCH_ROOT", str(root))
    monkeypatch.setenv("RAIN_UI_STATE_DIR", str(tmp_path / "ui_state"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
    monkeypatch.delenv("RAIN_UI_MODE", raising=False)
    monkeypatch.delenv("HERMES_CMD", raising=False)
    from rainui import results
    results._load_live.cache_clear()
    results.load_bundle.cache_clear()
    return root
