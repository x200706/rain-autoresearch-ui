"""氣象署 CoDiS（codis.cwa.gov.tw）逐時觀測：不需要金鑰，資料大約更新到前一天 24 時。

一次 POST 取回一段期間所有觀測項目，轉成訓練資料（原本取自中興大學資料庫）相同的欄位名稱，
CoDiS 的 23:59 就是隔天 00:00。對照取自先前補資料用的 station_rainfall_pipeline.ipynb。
"""
import pandas as pd
import requests
import urllib3

URL = "https://codis.cwa.gov.tw/api/station?"
TIMEOUT = 30
# 訓練資料欄位 ← (CoDiS 群組, 數值鍵)
COLUMNS = {
    "測站氣壓(hPa)": ("StationPressure", "Instantaneous"),
    "海平面氣壓(hPa)": ("SeaLevelPressure", "Instantaneous"),
    "氣溫(℃)": ("AirTemperature", "Instantaneous"),
    "露點溫度(℃)": ("DewPointTemperature", "Instantaneous"),
    "相對溼度(%)": ("RelativeHumidity", "Instantaneous"),
    "風速(m/s)": ("WindSpeed", "Mean"),
    "風向(360degree)": ("WindDirection", "Mean"),
    "WindSpeed.TenMinutelyMaximum": ("WindSpeed", "TenMinutelyMaximum"),
    "WindDirection.TenMinutelyMaximum": ("WindDirection", "TenMinutelyMaximum"),
    "最大陣風(m/s)": ("PeakGust", "Maximum"),
    "最大陣風風向(360degree)": ("PeakGust", "Direction"),
    "降水量(mm)": ("Precipitation", "Accumulation"),
    "降水時數(hr)": ("PrecipitationDuration", "Total"),
    "日照時數(hr)": ("SunshineDuration", "Total"),
    "天全空日射量(MJ/㎡)": ("GlobalSolarRadiation", "Accumulation"),
    "Visb": ("Visibility", "Instantaneous"),
    "Visibility.AutoMean": ("Visibility", "AutoMean"),
    "UVI": ("UVIndex", "Accumulation"),
    "CloudAmount": ("TotalCloudAmount", "Instantaneous"),
    "Cloud Amount": ("TotalCloudAmount", "Instantaneous"),   # 人工觀測雲量，舊資料另存一欄，同一個值
    "TotalCloudAmount.SatRetrieved": ("TotalCloudAmount", "SatRetrieved"),
    **{f"TxSoil{d}cm": (f"SoilTemperatureAt{d}cm", "Instantaneous") for d in (0, 5, 10, 20, 30, 50, 100)},
}
STATION_TYPES = {"署屬有人站": ["cwb"], "農業站": ["agr"], "署屬自動站": ["auto_C0", "auto_C1"]}


def station_types(station: str, kind: str = "") -> list[str]:
    if kind in STATION_TYPES:
        return STATION_TYPES[kind]
    if station.startswith("46"):
        return ["cwb"]
    if station.startswith("C0"):
        return ["auto_C0"]
    if station.startswith("C1"):
        return ["auto_C1"]
    return ["agr", "auto_C0", "auto_C1"]


def fetch(station: str, start: pd.Timestamp, end: pd.Timestamp, kind: str = "",
          stypes: list[str] | None = None) -> pd.DataFrame:
    """start～end（含）的逐時觀測。沒有資料回傳空表；連線錯誤直接丟出。"""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    start, end = pd.Timestamp(start).floor("h"), pd.Timestamp(end).floor("h")
    # CoDiS 把 00:00 寫成前一天 23:59，所以起點往前多查一小時、終點是 00:00 時查到 23:59
    first = start - pd.Timedelta(hours=1)
    payload = {"date": f"{end:%Y-%m-%d}T00:00:00.000+08:00", "type": "report_date", "stn_ID": station,
               "more": "", "item": "", "start": f"{first:%Y-%m-%dT%H}:00:00",
               "end": f"{end:%Y-%m-%dT%H}:00:00" if end.hour else f"{end - pd.Timedelta(minutes=1):%Y-%m-%dT%H:%M}:00"}
    for stype in stypes or station_types(station, kind):
        resp = requests.post(URL, data={**payload, "stn_type": stype}, verify=False, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data") or []
        records = data[0].get("dts", []) if data else []
        if records:
            return to_frame(records).query("`觀測時間(hour)` >= @start and `觀測時間(hour)` <= @end")
    return pd.DataFrame(columns=["觀測時間(hour)", *COLUMNS])


def to_frame(records: list) -> pd.DataFrame:
    rows = []
    for rec in records:
        t = pd.Timestamp(rec["DataTime"])
        if t.minute == 59:
            t = t + pd.Timedelta(minutes=1)
        row = {"觀測時間(hour)": t}
        for col, (group, key) in COLUMNS.items():
            row[col] = (rec.get(group) or {}).get(key)
        rows.append(row)
    frame = pd.DataFrame(rows)
    for col in COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.sort_values("觀測時間(hour)").reset_index(drop=True)
