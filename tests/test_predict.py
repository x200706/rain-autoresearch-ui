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


def _station(t, rain, temp=20.0, rh=90.0):
    return {"StationName": "鞍部", "StationId": "466910", "ObsTime": {"DateTime": f"{t}+08:00"},
            "WeatherElement": {"Now": {"Precipitation": rain}, "WindDirection": 180, "WindSpeed": 2.0,
                               "AirTemperature": temp, "RelativeHumidity": rh, "AirPressure": 922.5,
                               "GustInfo": {"PeakGustSpeed": 5.1, "Occurred_at": {"WindDirection": 170}}}}


def test_realtime_hourly_rain_from_daily_total_and_dew_point(monkeypatch):
    from rainui import cwa_realtime
    snaps = [_station("2026-11-17T00:00:00", 12.0), _station("2026-11-17T01:00:00", 0.5),
             _station("2026-11-17T01:10:00", 0.5), _station("2026-11-17T02:00:00", 3.0),
             _station("2026-11-17T03:00:00", -99)]
    monkeypatch.setattr(cwa_realtime, "history", lambda *a: [cwa_realtime.parse_station(s) for s in snaps[:4]])
    monkeypatch.setattr(cwa_realtime, "latest", lambda *a: [cwa_realtime.parse_station(snaps[4])])
    frame, notes = cwa_realtime.fetch("k", "466910", "2026-11-17 00:00", "2026-11-17 03:00")
    assert list(frame["觀測時間(hour)"].dt.hour) == [0, 1, 2, 3]          # 01:10 不是整點，不取
    rain = frame["降水量(mm)"].tolist()
    assert np.isnan(rain[0]) and rain[1:3] == [0.5, 2.5] and np.isnan(rain[3])   # 換日歸零、缺測
    assert frame.loc[1, "露點溫度(℃)"] == pytest.approx(18.4, abs=0.1)
    assert frame.loc[1, "最大陣風風向(360degree)"] == 170 and not notes


def test_forecast_needs_a_key_for_today_and_merges_realtime_with_it(monkeypatch):
    from rainui import cwa_realtime
    if not predict.available():
        pytest.skip("deploy/ 沒有模型")
    sid = predict.available()[0]
    times = pd.date_range("2026-11-14 00:00", "2026-11-17 00:00", freq="h")
    monkeypatch.setattr(codis, "fetch", lambda *a, **k: pd.DataFrame({"觀測時間(hour)": times, "降水量(mm)": 0.0,
                                                                        "氣溫(℃)": 15.0}))
    with pytest.raises(predict.ForecastError, match="請在上方輸入氣象署開放資料授權碼"):
        predict.forecast(sid, "2026-11-17 19:00")
    today = pd.date_range("2026-11-17 00:00", "2026-11-17 18:00", freq="h")
    rt = pd.DataFrame({"觀測時間(hour)": today, "降水量(mm)": 0.0, "氣溫(℃)": 16.0})
    monkeypatch.setattr(cwa_realtime, "fetch", lambda *a, **k: (rt, []))
    frame, info = predict.forecast(sid, "2026-11-17 19:00", key="k")
    assert info["realtime_hours"] == 18 and info["last_observed"] == pd.Timestamp("2026-11-17 18:00")
    assert frame["datetime"].iloc[-1] == pd.Timestamp("2026-11-17 19:00") and not np.isnan(info["rain_proba"])


def test_snapshot_xml_is_read_like_the_json_api():
    from rainui import cwa_realtime
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<cwaopendata xmlns="urn:cwa:gov:tw:cwacommon:0.1"><dataset>
 <Station><StationName>淡水</StationName><StationId>466900</StationId></Station>
 <Station><StationName>鞍部</StationName><StationId>466910</StationId>
  <ObsTime><DateTime>2026-11-17T00:00:00+08:00</DateTime></ObsTime>
  <WeatherElement><Now><Precipitation>2.0</Precipitation></Now><WindDirection>190.0</WindDirection>
   <WindSpeed>0.9</WindSpeed><AirTemperature>16.3</AirTemperature><RelativeHumidity>100</RelativeHumidity>
   <AirPressure>923.4</AirPressure><GustInfo><PeakGustSpeed>-99</PeakGustSpeed>
   <Occurred_at><WindDirection>-99</WindDirection></Occurred_at></GustInfo></WeatherElement>
 </Station></dataset></cwaopendata>""".encode("utf-8")
    rows = cwa_realtime._snapshot_rows(xml, "466910")
    assert len(rows) == 1
    row = rows[0]
    assert row["觀測時間(hour)"] == pd.Timestamp("2026-11-17 00:00") and row["_daily_rain"] == 2.0
    assert row["測站氣壓(hPa)"] == 923.4 and row["最大陣風(m/s)"] is None and row["露點溫度(℃)"] == 16.3
