"""線上預測：CoDiS 轉換、前處理與可預測範圍。模型推論的正確性由 tools/export_model.py 重算整段測試集核對。"""
import numpy as np
import pandas as pd
import pytest

from rainui import codis, predict, sources


def test_codis_midnight_is_next_day_and_fields_use_training_names():
    recs = [{"DataTime": "2026-11-15T23:00:00", "Precipitation": {"Accumulation": -9.8}, "AirTemperature": {"Instantaneous": 15.5}},
            {"DataTime": "2026-11-15T23:59:00", "Precipitation": {"Accumulation": 1.5},
             "TotalCloudAmount": {"Instantaneous": 8}}]
    frame = codis.to_frame(recs)
    assert list(frame["觀測時間(hour)"]) == [pd.Timestamp("2026-11-15 23:00"), pd.Timestamp("2026-11-16 00:00")]
    assert frame["降水量(mm)"].tolist() == [-9.8, 1.5]
    assert frame.loc[1, "Cloud Amount"] == 8 and frame.loc[1, "CloudAmount"] == 8


def test_clean_follows_training_rules():
    raw = pd.DataFrame({"觀測時間(hour)": ["2025-01-01 00:00:00", "2025-01-01 01:00:00", "2025-01-01 03:00:00"],
                        "降水量(mm)": [-9.8, 0.3, 12.0], "相對溼度(%)": [-99.8, 90, 95], "降水時數(hr)": [None, 0.2, 1]})
    df = predict.clean(raw)
    assert len(df) == 4                                    # 缺的 02 時補成空白列
    assert df["PP01"].tolist()[:2] == [0.0, 0.0]           # 雨跡與 < 0.5 mm 歸零
    assert df["PP01_raw"].tolist()[1] == 0.3               # 評估用的原始值保留小雨
    assert np.isnan(df.loc[0, "RH01"])                     # 缺測代碼
    assert df["PP02"].tolist()[:2] == [0.0, 1.0]           # 降水時數二值化，缺值依雨量補


def test_forecast_refuses_a_time_later_than_codis_has(monkeypatch):
    times = pd.date_range("2026-11-15 00:00", "2026-11-17 00:00", freq="h")
    monkeypatch.setattr(codis, "fetch", lambda *a, **k: pd.DataFrame({"觀測時間(hour)": times, "降水量(mm)": 0.0}))
    if not predict.available():
        pytest.skip("deploy/ 沒有模型")
    sid = predict.available()[0]
    with pytest.raises(predict.ForecastError, match="最晚能預測 2026-11-17 01:00"):
        predict.forecast(sid, "2026-11-17 05:00")


def test_station_table_groups_by_kind():
    html = ("<table><tr><th>站號</th><th>站名</th><th>站種</th><th>城市</th></tr>"
            "<tr><td>466910</td><td>鞍部</td><td>署屬有人站</td><td>臺北市</td></tr>"
            "<tr><td>C0A870</td><td>甲</td><td>署屬自動站</td><td>新北市</td></tr>"
            "<tr><td>C1A630</td><td>乙</td><td>署屬自動站</td><td>新北市</td></tr>"
            "<tr><td>72C440</td><td>丙</td><td>農業站</td><td>臺中市</td></tr></table>")
    table = sources.parse_table(html)
    assert dict(zip(table["站號"], table["分類"])) == {"466910": "有人站", "C0A870": "自動氣象站",
                                                       "C1A630": "自動雨量站", "72C440": "農業站"}
