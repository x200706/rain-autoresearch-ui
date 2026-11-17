"""把一個測站某副目標的最佳兩階段模型打包到 deploy/<站號>/，給線上預測用（別台電腦 git pull 就能跑）。

用法（在本 repo 根目錄，需要 rain_autoresearch 的 outputs 與 data）：
    python tools/export_model.py D:/rain_autoresearch 466910 --subgoal under

打包內容：gate.joblib（凍結的雙 LightGBM gate）、lstm.keras、兩個 scaler，以及 spec.json
（特徵順序、TIME_STEP、訓練期中位數、測試集指標）。打包後用同一套前處理重算整段測試集，
和實驗輸出的 test_two_stage_predictions.csv 比對，不一致就不寫出。
"""
import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

UI_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(UI_ROOT))
from rainui import predict  # noqa: E402


def pod_far(frame: pd.DataFrame, thr: float) -> dict:
    obs, fc = frame["actual"] >= thr, frame["pred"] >= thr
    hits = int((obs & fc).sum())
    return {"threshold": thr, "observed": int(obs.sum()), "forecast": int(fc.sum()), "hits": hits,
            "pod": hits / obs.sum() if obs.sum() else None, "far": 1 - hits / fc.sum() if fc.sum() else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("station")
    ap.add_argument("--subgoal", default="under")
    args = ap.parse_args()
    root, sid = Path(args.root), args.station
    sd = root / "outputs" / sid
    ablation = list(csv.DictReader((sd / "ablation.tsv").read_text(encoding="utf-8").splitlines(), delimiter="\t"))
    best = next(a for a in ablation if a["subgoal"] == args.subgoal)
    run = best["best_run"]
    rows = csv.DictReader((sd / f"subgoal_{args.subgoal}" / "results.tsv").read_text(encoding="utf-8").splitlines(),
                          delimiter="\t")
    g, c = (int(v) for v in run[1:].split("_c"))
    art = root / next(r["artifact_dir"] for r in rows if int(r["generation"]) == g and int(r["candidate"]) == c)
    lstm_dir = art / "models" / "lstm_final"
    order = json.loads(next(lstm_dir.glob("lstm_feature_order_*.json")).read_text(encoding="utf-8"))
    gate_path = root / json.loads((sd / "gate.json").read_text(encoding="utf-8"))["path"]

    dest = UI_ROOT / "deploy" / sid
    tmp = dest.with_name(sid + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copyfile(gate_path, tmp / "gate.joblib")
    shutil.copyfile(next(lstm_dir.glob("rain_event_lstm_*.keras")), tmp / "lstm.keras")
    shutil.copyfile(next(lstm_dir.glob("feature_scaler_*.joblib")), tmp / "feature_scaler.joblib")
    shutil.copyfile(next(lstm_dir.glob("pp01_scaler_*.joblib")), tmp / "pp01_scaler.joblib")

    import joblib
    gate = joblib.load(tmp / "gate.joblib")
    train_end = pd.Timestamp(order["train_end"])
    raw = pd.read_csv(root / "data" / f"{sid}.csv", encoding="utf-8-sig", low_memory=False)
    cleaned = predict.clean(raw)
    drop = [c for c in cleaned.columns if c not in {"datetime", "PP01", "PP01_raw"} and cleaned[c].isna().all()]
    spec = {"station": sid, "subgoal": args.subgoal, "run": run, "genome": best["best_genome"],
            "lstm_layers": int(best["LSTM_LAYERS"]), "lstm_units": int(best["LSTM_UNITS"]),
            "batch_size": int(best["BATCH_SIZE"]), "wmae_alpha": best["WMAE_ALPHA"],
            "time_step": int(order["time_step"]), "lstm_features": order["features"],
            "gate_features": list(gate["features"]), "train_start": order["train_start"],
            "train_end": order["train_end"], "test_start": order["test_start"], "test_end": order["test_end"],
            "drop_columns": drop, "medians": {}, "pp01_median": None}
    df, medians = predict.build_features(raw, spec, fit_mask=lambda dt: (dt <= train_end).to_numpy())
    spec["pp01_median"] = medians.pop("__PP01__")
    spec["medians"] = medians
    # 每欄最後一筆觀測：線上抓的那一小段開頭缺值時，照訓練資料的向前填沿用這個值
    spec["last_observed"] = {c: float(cleaned[c].dropna().iloc[-1]) for c in medians
                             if c in cleaned.columns and cleaned[c].notna().any()}

    # 用 tmp 的模型重算測試集，和實驗輸出比對
    ref = pd.read_csv(art / "predictions" / "test_two_stage_predictions.csv", encoding="utf-8-sig",
                      parse_dates=["datetime"])
    mine = predict.predict_frame(df, dict(spec, station=tmp.name), ref["datetime"])
    predict.load_models.cache_clear()
    gate_diff = float(np.nanmax(np.abs(mine["rain_proba"].to_numpy() - ref["rain_proba"].to_numpy())))
    pred_diff = float(np.nanmax(np.abs(mine["pred"].to_numpy() - ref["pred"].to_numpy())))
    flips = int((mine["has_rain_pred"].to_numpy() != ref["has_rain_pred"].to_numpy()).sum())
    print(f"測試集 {len(ref):,} 小時：gate 機率最大差 {gate_diff:.2e}、gate 判定不同 {flips} 筆、雨量最大差 {pred_diff:.4f} mm")
    if flips or pred_diff > 0.01:
        shutil.rmtree(tmp)
        raise SystemExit("重算結果與實驗輸出不一致，不寫出")
    spec["verification"] = {"test_hours": len(ref), "gate_proba_max_abs_diff": gate_diff,
                            "pred_max_abs_diff_mm": pred_diff}
    spec["test_metrics"] = [pod_far(ref, 10.0), pod_far(ref, 40.0)]
    (tmp / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    print(f"已打包 {dest}（{run}，TIME_STEP {spec['time_step']}）")


if __name__ == "__main__":
    main()
