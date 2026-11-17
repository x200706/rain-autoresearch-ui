"""線上預測：用打包好的兩階段模型（雙 LightGBM gate → LSTM）預測某一小時的雨量。

前處理逐步照抄 rain_autoresearch/train.py（欄位對照、缺測代碼、雨跡、小雨歸零、物理範圍、補值、週期特徵、
gate 的 3 小時 lag、LSTM 的連續 TIME_STEP 小時序列），差別只在補值：訓練時測試期是整段一起時間插值與向前填，
線上只有抓下來的這一小段，段內同樣插值、向前填，段首仍缺的用訓練期中位數（打包時算好存在 spec.json）。

模型檔在 deploy/<站號>/，由 tools/export_model.py 從實驗結果打包。
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

DEPLOY_DIR = config.UI_ROOT / "deploy"
LAG_HOURS = 3          # train.py CLASSIFIER_LAG_HOURS
RAIN_THRESHOLD = 0.5   # train.py RAIN_THRESHOLD
GATE_THRESHOLD = 0.5

COL_MAPPING = {
    "觀測時間(hour)": "datetime", "測站氣壓(hPa)": "PS01", "海平面氣壓(hPa)": "PS02", "氣溫(℃)": "TX01",
    "氣溫(°C)": "TX01", "露點溫度(℃)": "TD01", "露點溫度(°C)": "TD01", "相對溼度(%)": "RH01", "相對濕度(%)": "RH01",
    "風速(m/s)": "WD01", "風向(360degree)": "WD02", "最大陣風(m/s)": "WD07", "最大陣風風向(360degree)": "WD08",
    "降水量(mm)": "PP01", "降雨量(mm)": "PP01", "降水時數(hr)": "PP02", "降雨時數(hr)": "PP02",
    "全天空日射量(MJ/㎡)": "GR01", "天全空日射量(MJ/㎡)": "GR01", "全天空日射量(MJ/m2)": "GR01",
}
MISSING_VALUE_CODES = [-999.1, -9.6, -999.6, -9.5, -99.5, -999.5, -9999.5, -9.7, -99.7, -999.7, -9999.7, -99.8]
TRACE_RAIN_CODE = -9.8
HUMIDITY = {"RH01", "RelativeHumidity.Instantaneousf"}
NONNEGATIVE = {
    "PS01", "PS02", "StationPressure.Instantaneousf", "SeaLevelPressure.Instantaneousf", "VaporPressure",
    "WD01", "WD07", "PeakGust.Maximumf", "WindSpeed.Meanf", "WindSpeed.TenMinutelyMaximum",
    "WindSpeed.TenMinutelyMaximumf", "GR01", "GlobalSolarRadiation.Accumulationf", "PP02",
    "PrecipitationDuration.Totalf",
}
WIND_DIRECTION = {"WD02", "WD08", "PeakGust.Directionf", "WindDirection.Meanf", "WindDirection.TenMinutelyMaximum",
                  "WindDirection.TenMinutelyMaximumf"}
TIME_FEATURES = {"year", "hour_sin", "hour_cos", "dayofyear_sin", "dayofyear_cos", "month_sin", "month_cos"}


# ---------------------------------------------------------------- 前處理（照抄 train.py）
def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """train.py cell 9–11：欄名對照、轉數值、缺測代碼、雨跡、小雨歸零、物理範圍、降水時數二值化、補齊逐時時間軸。"""
    df = raw.copy()
    df.columns = df.columns.astype(str).str.replace("﻿", "", regex=False).str.strip()
    df = df.rename(columns={k: v for k, v in COL_MAPPING.items() if k in df.columns})
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).reset_index(drop=True)
    for col in df.columns:
        if col != "datetime":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in df.columns:
        if col == "datetime":
            continue
        values = df[col].to_numpy(dtype=float)
        bad = np.zeros(len(df), dtype=bool)
        for code in MISSING_VALUE_CODES:
            bad |= np.isclose(values, code, rtol=0.0, atol=1e-8)
        df.loc[bad, col] = np.nan
    if "PP01" not in df.columns:
        df["PP01"] = np.nan
    df.loc[np.isclose(df["PP01"].to_numpy(dtype=float), TRACE_RAIN_CODE, rtol=0.0, atol=1e-8), "PP01"] = 0.0
    df.loc[df["PP01"] < 0, "PP01"] = np.nan
    df["PP01_raw"] = df["PP01"].copy()
    df.loc[(df["PP01"] >= 0) & (df["PP01"] < RAIN_THRESHOLD), "PP01"] = 0.0
    for col in HUMIDITY | NONNEGATIVE:
        if col in df.columns:
            df.loc[df[col] < 0, col] = np.nan
    for col in WIND_DIRECTION:
        if col in df.columns:
            df.loc[(df[col] < 0) | (df[col] > 360), col] = np.nan
    if "PP02" in df.columns:
        seen = df["PP02"].notna()
        df.loc[seen, "PP02"] = (df.loc[seen, "PP02"] != 0).astype(float)
        gap = df["PP02"].isna()
        df.loc[gap & (df["PP01"] == 0), "PP02"] = 0
        df.loc[gap & df["PP01"].notna() & (df["PP01"] != 0), "PP02"] = 1
    df = df.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)
    df["datetime"] = df["datetime"].dt.floor("h")
    df = df.drop_duplicates("datetime", keep="last")
    hours = pd.date_range(df["datetime"].min(), df["datetime"].max(), freq="h")
    return df.set_index("datetime").reindex(hours).rename_axis("datetime").reset_index()


def impute(frame: pd.DataFrame, fit_mask, columns, medians: dict | None = None):
    """train.py impute_inputs：訓練、其餘各自時間插值（只補兩端之間）→ 向前填，剩下的用訓練期中位數。
    medians 給定時（線上），整段都當成非訓練期。回傳 (補好的 frame, 中位數)。"""
    out = frame.set_index("datetime").copy()
    fit_mask = np.asarray(fit_mask, dtype=bool)
    for period in (fit_mask, ~fit_mask):
        if period.any():
            part = out.loc[period, columns]
            out.loc[period, columns] = part.interpolate(method="time", limit_area="inside").ffill().to_numpy()
    if medians is None:
        medians = out.loc[fit_mask, columns].median(numeric_only=True).to_dict()
    for col in columns:
        m = medians.get(col, np.nan)
        if out[col].isna().any() and not pd.isna(m):
            out[col] = out[col].fillna(m)
    return out.reset_index(), {k: (None if pd.isna(v) else float(v)) for k, v in medians.items()}


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """train.py cell 15 的週期特徵。"""
    df = df.copy()
    dt = df["datetime"]
    if "WD02" in df.columns:
        df["WD02_sin"], df["WD02_cos"] = np.sin(2 * np.pi * df["WD02"] / 360), np.cos(2 * np.pi * df["WD02"] / 360)
    if "WD08" in df.columns:
        df["WD08_sin"], df["WD08_cos"] = np.sin(2 * np.pi * df["WD08"] / 360), np.cos(2 * np.pi * df["WD08"] / 360)
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * dt.dt.hour / 24), np.cos(2 * np.pi * dt.dt.hour / 24)
    days = np.where(dt.dt.is_leap_year, 366.0, 365.0)
    df["dayofyear_sin"] = np.sin(2 * np.pi * dt.dt.dayofyear / days)
    df["dayofyear_cos"] = np.cos(2 * np.pi * dt.dt.dayofyear / days)
    df["month_sin"], df["month_cos"] = np.sin(2 * np.pi * dt.dt.month / 12), np.cos(2 * np.pi * dt.dt.month / 12)
    return df


def gate_raw_columns(gate_features: list) -> list:
    """gate 特徵去掉 lag 與週期特徵後的原始欄位（順序同 gate）。"""
    return [f for f in gate_features if "_lag" not in f and f not in TIME_FEATURES
            and not f.endswith(("_sin", "_cos"))]


def build_features(raw: pd.DataFrame, spec: dict, fit_mask=None):
    """清理 → 補值 → 週期特徵。fit_mask 為 None 表示線上（用 spec 的中位數）；回傳 (feature_df, 中位數)。"""
    df = clean(raw)
    needed = set(gate_raw_columns(spec["gate_features"])) | set(spec["lstm_features"]) | {"WD02", "WD08"}
    for col in needed - TIME_FEATURES - {f for f in needed if f.endswith(("_sin", "_cos"))}:
        if col not in df.columns:
            df[col] = np.nan
    if spec.get("drop_columns"):
        df = df.drop(columns=[c for c in spec["drop_columns"] if c in df.columns])
    cols = [c for c in df.columns if c not in {"datetime", "PP01", "PP01_raw"} and pd.api.types.is_numeric_dtype(df[c])]
    online = fit_mask is None
    mask = np.zeros(len(df), dtype=bool) if online else fit_mask(df["datetime"])
    if online:
        # 段首缺值：訓練資料整段向前填時會沿用這欄最後一筆觀測，線上照做；沒有最後一筆才用訓練期中位數
        df = df.set_index("datetime")
        for col, value in (spec.get("last_observed") or {}).items():
            if col in df.columns and value is not None and df[col].isna().any():
                first = df[col].first_valid_index()
                head = df.index < first if first is not None else np.ones(len(df), dtype=bool)
                df.loc[head, col] = value
        df = df.reset_index()
    df, medians = impute(df, mask, cols, spec["medians"] if online else None)
    # gate 輸入的 PP01 另外補值（標籤與 LSTM 仍用未補的 PP01）
    pp, pp_med = impute(df[["datetime", "PP01"]], mask, ["PP01"], {"PP01": spec["pp01_median"]} if online else None)
    df["PP01_gate"] = pp["PP01"].to_numpy()
    medians["__PP01__"] = pp_med["PP01"]
    return add_time_features(df), medians


def gate_matrix(df: pd.DataFrame, gate_features: list) -> pd.DataFrame:
    """第 i 列 = 用第 i 小時（含前 3 小時 lag）預測第 i+1 小時；欄位順序與訓練時相同。"""
    base_cols = [f for f in gate_features if "_lag" not in f]
    base = pd.DataFrame({c: (df["PP01_gate"] if c == "PP01" else df[c]) for c in base_cols})
    lag_cols = [c for c in base_cols if c not in TIME_FEATURES]
    parts = [base]
    for lag in range(1, LAG_HOURS + 1):
        shifted = base[lag_cols].shift(lag)
        shifted.columns = [f"{c}_lag{lag}" for c in lag_cols]
        parts.append(shifted)
    return pd.concat(parts, axis=1)[gate_features]


def gate_proba(gate: dict, X: pd.DataFrame) -> np.ndarray:
    """train.py cell 30：classifier1 與 classifier2（undersampling ensemble）的 confidence PK。"""
    c1 = gate["classifier1"].predict_proba(X)
    p1 = c1[:, 1]
    models = gate["classifier2_ensemble"][: gate["best_n_classifier2"]]
    allp = np.array([m.predict_proba(X)[:, 1] for m in models])
    pos = allp >= 0.5
    pos_n, neg_n = pos.sum(axis=0), (~pos).sum(axis=0)
    avg_pos = np.divide(np.where(pos, allp, 0).sum(axis=0), pos_n, out=np.zeros(len(X)), where=pos_n != 0)
    avg_neg = np.divide(np.where(~pos, 1 - allp, 0).sum(axis=0), neg_n, out=np.zeros(len(X)), where=neg_n != 0)
    p2 = np.where(avg_pos >= avg_neg, avg_pos, 1.0 - avg_neg)
    pred1, pred2 = (p1 >= 0.5).astype(int), (p2 >= gate["clf2_threshold"]).astype(int)
    conf1 = c1[np.arange(len(X)), pred1]
    conf2 = np.where(pred2 == 1, p2, 1.0 - p2)
    return np.where(pred1 == pred2, p1, np.where(conf1 >= conf2, p1, p2))


# ---------------------------------------------------------------- 模型
def available() -> list[str]:
    return sorted(p.name for p in DEPLOY_DIR.iterdir() if (p / "spec.json").exists()) if DEPLOY_DIR.exists() else []


def load_spec(station: str) -> dict:
    return json.loads((DEPLOY_DIR / station / "spec.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_models(station: str):
    import joblib
    import os
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    from tensorflow.keras.models import load_model
    d = DEPLOY_DIR / station
    return (joblib.load(d / "gate.joblib"), load_model(d / "lstm.keras", compile=False),
            joblib.load(d / "feature_scaler.joblib"), joblib.load(d / "pp01_scaler.joblib"))


def predict_frame(df: pd.DataFrame, spec: dict, targets) -> pd.DataFrame:
    """對 targets（逐時時間）做兩階段預測。df 是 build_features 的結果，必須涵蓋目標前 TIME_STEP 與 3 小時 lag。"""
    gate, lstm, feat_scaler, pp_scaler = load_models(spec["station"])
    ts, feats = spec["time_step"], spec["lstm_features"]
    index = pd.Series(np.arange(len(df)), index=df["datetime"])
    targets = pd.DatetimeIndex(targets)
    rows = index.reindex(targets).to_numpy()

    X = gate_matrix(df, spec["gate_features"])
    out = pd.DataFrame({"datetime": targets})
    prev = rows - 1
    ok_gate = ~np.isnan(rows) & (prev >= LAG_HOURS)
    proba = np.full(len(targets), np.nan)
    if ok_gate.any():
        Xi = X.iloc[prev[ok_gate].astype(int)]
        good = ~Xi.isna().any(axis=1).to_numpy()
        vals = np.full(len(Xi), np.nan)
        if good.any():
            vals[good] = gate_proba(gate, Xi[good])
        proba[ok_gate] = vals
    out["rain_proba"] = proba
    out["has_rain_pred"] = (proba >= GATE_THRESHOLD).astype(int)

    scaling = [f for f in feats if f != "PP01"]
    scaled = pd.DataFrame(feat_scaler.transform(df[scaling]), columns=scaling)
    pp = df["PP01"].fillna(0.0).to_numpy()
    scaled_pp = np.zeros(len(df))
    if (pp != 0).any():
        scaled_pp[pp != 0] = pp_scaler.transform(pd.DataFrame({"PP01": pp[pp != 0]})).ravel()
    scaled["PP01"] = scaled_pp
    matrix = scaled[feats].to_numpy(dtype=np.float32)
    missing = np.concatenate([[0], np.cumsum(df["PP01"].isna().to_numpy(dtype=np.int64))])

    seqs, pos = [], []
    for i, r in enumerate(rows):
        if np.isnan(r) or out.at[i, "has_rain_pred"] != 1:
            continue
        r = int(r)
        if r - ts < 0 or missing[r] - missing[r - ts] > 0:
            continue
        seqs.append(matrix[r - ts:r])
        pos.append(i)
    out["pred"] = 0.0
    out["lstm_sequence_available"] = False
    if seqs:
        mm = pp_scaler.inverse_transform(lstm.predict(np.asarray(seqs), verbose=0)).ravel()
        out.loc[pos, "pred"] = np.maximum(mm, 0.0)
        out.loc[pos, "lstm_sequence_available"] = True
    out.loc[np.isnan(proba), "pred"] = np.nan
    actual = df.set_index("datetime")["PP01_raw"]
    out["actual"] = actual.reindex(targets).to_numpy()
    return out


MAX_SEARCH_TIME_STEP = 24   # genome.py 的 TIME_STEP 候選最大值；換成搜尋空間內任何模型都抓得夠


def lookback_hours(spec: dict) -> int:
    """預測一小時要往前抓多少小時：較佳化搜尋的最大序列長度、這個模型的序列長度與 gate lag 取大者，再多留一天給補值。"""
    return max(MAX_SEARCH_TIME_STEP, spec["time_step"], LAG_HOURS + 1) + 24


class ForecastError(Exception):
    """抓不到資料或時間超出可預測範圍；訊息直接顯示給使用者。"""


def forecast(station: str, target, context: int = 24, key: str = "") -> tuple[pd.DataFrame, dict]:
    """預測 target 這一小時（只用 target 之前的觀測），並附上前 context−1 小時的預測當對照。
    資料當場抓、不存檔：CoDiS 到前一天 24 時；有氣象署開放資料授權碼時，今天的整點由開放資料補上。
    回傳 (逐時預測, 摘要)。"""
    from . import codis, cwa_realtime
    spec = load_spec(station)
    target = pd.Timestamp(target).floor("h")
    first_target = target - pd.Timedelta(hours=context - 1)
    start = first_target - pd.Timedelta(hours=lookback_hours(spec))
    try:
        raw = codis.fetch(station, start, target)
    except Exception as exc:  # noqa: BLE001 — 連線問題直接告訴使用者
        raise ForecastError(f"連不上氣象署 CoDiS：{exc}") from exc
    observed = raw.dropna(subset=["降水量(mm)"]) if len(raw) else raw
    if observed.empty:
        raise ForecastError(f"CoDiS 沒有 {start:%Y-%m-%d %H:%M} 到 {target:%Y-%m-%d %H:%M} 的觀測")
    codis_last = pd.Timestamp(observed["觀測時間(hour)"].max())
    last, realtime_hours, notes = codis_last, 0, []
    if target - pd.Timedelta(hours=1) > codis_last:
        if not key.strip():
            raise ForecastError(f"CoDiS 目前只到 {codis_last:%Y-%m-%d %H:%M}，最晚能預測 "
                                f"{codis_last + pd.Timedelta(hours=1):%Y-%m-%d %H:%M}；要預測更晚的時間，"
                                "請在上方輸入氣象署開放資料授權碼")
        try:
            rt, notes = cwa_realtime.fetch(key.strip(), station, codis_last, target)
        except cwa_realtime.RealtimeError as exc:
            raise ForecastError(str(exc)) from None
        rt = rt[rt["觀測時間(hour)"] > codis_last].dropna(axis=1, how="all")
        realtime_hours = int((rt["觀測時間(hour)"] < target).sum())
        raw = pd.concat([raw[raw["觀測時間(hour)"] <= codis_last], rt], ignore_index=True)
        if len(rt):
            last = pd.Timestamp(rt["觀測時間(hour)"].max())
        if target - pd.Timedelta(hours=1) > last:
            raise ForecastError(f"氣象署開放資料目前只到 {last:%Y-%m-%d %H:%M}，最晚能預測 "
                                f"{last + pd.Timedelta(hours=1):%Y-%m-%d %H:%M}")
    if pd.Timestamp(raw["觀測時間(hour)"].max()) < target:      # 目標還沒有觀測：補一列空白，只當時間軸
        raw = pd.concat([raw, pd.DataFrame({"觀測時間(hour)": [target]})], ignore_index=True)
    df, _ = build_features(raw, spec)
    frame = predict_frame(df, spec, pd.date_range(first_target, target, freq="h"))
    before = raw[pd.to_datetime(raw["觀測時間(hour)"]) < target]
    sources = {}
    for col in raw.columns:
        if col == "觀測時間(hour)":
            continue
        sources[col] = float(pd.to_numeric(before[col], errors="coerce").notna().mean()) if len(before) else 0.0
    row = frame.iloc[-1]
    info = {"station": station, "target": target, "rain_proba": float(row["rain_proba"]),
            "has_rain": bool(row["has_rain_pred"]), "pred": float(row["pred"]),
            "actual": None if pd.isna(row["actual"]) else float(row["actual"]),
            "lstm_available": bool(row["lstm_sequence_available"]), "fetched_from": start, "last_observed": last,
            "codis_last": codis_last, "realtime_hours": realtime_hours, "notes": notes,
            "hours_fetched": int(len(before)), "time_step": spec["time_step"], "column_coverage": sources}
    return frame, info
