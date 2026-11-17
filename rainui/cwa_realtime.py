"""氣象署開放資料平台的即時觀測，用來補 CoDiS 還沒有的「今天」。需要使用者自己的授權碼（介面輸入，不存檔、不記錄）。

- O-A0001-001「氣象觀測站-全測站逐時氣象資料」：每 10 分鐘更新，只有最新一筆。
- historyapi「短期過去資料下載」：同一資料集過去 24 小時每個整點的快照檔（XML，全台測站約 1.7 MB），
  用來拿今天稍早的整點。這支 API 只接受網址參數的授權碼（放 header 會被拒）。

只取整點快照，轉成訓練資料的欄位名稱。這個資料集沒有的欄位（露點以外的日射、地溫、雲量、能見度、
海平面氣壓等）留空，交給前處理沿用 CoDiS 最後一筆。露點由氣溫與相對溼度算出；逐時雨量由「當日累積雨量」
相鄰整點相減。
"""
import math
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

DATASET = "O-A0001-001"
DATASTORE = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{DATASET}"
HISTORY = f"https://opendata.cwa.gov.tw/historyapi/v1/getMetadata/{DATASET}"
TIMEOUT = 30


class RealtimeError(Exception):
    """授權碼錯誤、連不上或格式看不懂；訊息直接顯示給使用者（不含授權碼）。"""


def _request(url: str, key: str, params: dict | None = None, in_query: bool = False) -> requests.Response:
    """授權碼預設放 HTTP header；historyapi 只收網址參數。錯誤訊息只寫例外類型，不會帶出含授權碼的網址。"""
    params = dict(params or {})
    headers = {}
    if in_query:
        params["Authorization"] = key
    else:
        headers["Authorization"] = key
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise RealtimeError(f"連不上氣象署開放資料平台：{type(exc).__name__}") from None
    if resp.status_code in (401, 403):
        raise RealtimeError("氣象署開放資料授權碼不正確，請到 opendata.cwa.gov.tw 登入後複製授權碼")
    if resp.status_code != 200:
        raise RealtimeError(f"氣象署開放資料平台回應 {resp.status_code}")
    return resp


def _get(url: str, key: str, params: dict | None = None, in_query: bool = False):
    try:
        return _request(url, key, params, in_query).json()
    except ValueError:
        raise RealtimeError("氣象署開放資料平台回傳的不是 JSON") from None


def _xml_to_dict(elem):
    """XML 元素 → 巢狀 dict（去掉命名空間；重複的子元素只留最後一個，這裡用不到重複的那幾個）。"""
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    return {child.tag.split("}")[-1]: _xml_to_dict(child) for child in children}


def _snapshot_rows(content: bytes, station: str) -> list[dict]:
    root = ET.fromstring(content)
    rows = []
    for st in root.iter():
        if st.tag.split("}")[-1] != "Station":
            continue
        data = _xml_to_dict(st)
        if str(data.get("StationId", "")) == station:
            row = parse_station(data)
            if row:
                rows.append(row)
    return rows


def _find(obj, test):
    """遞迴找出所有符合 test 的 dict（回傳格式不同版本的巢狀層次不一樣）。"""
    if isinstance(obj, dict):
        if test(obj):
            yield obj
        for v in obj.values():
            yield from _find(v, test)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find(v, test)


def _num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v <= -90 else v       # 開放資料以 -99、-98 等表示缺測或無資料


def _key_ci(d: dict, name: str):
    for k, v in d.items():
        if k.lower() == name.lower():
            return v
    return None


def parse_station(station: dict) -> dict | None:
    """一個測站的快照 → {時間, 訓練欄位..., _daily_rain}。"""
    obs = _key_ci(station, "ObsTime") or {}
    when = _key_ci(obs, "DateTime") if isinstance(obs, dict) else None
    if not when:
        return None
    t = pd.Timestamp(when)
    if t.tzinfo is not None:
        t = t.tz_convert("Asia/Taipei").tz_localize(None)
    el = _key_ci(station, "WeatherElement") or {}
    gust = _key_ci(el, "GustInfo") or {}
    gust_at = _key_ci(gust, "Occurred_at") or {}
    now = _key_ci(el, "Now") or {}
    row = {
        "觀測時間(hour)": t,
        "測站氣壓(hPa)": _num(_key_ci(el, "AirPressure")),
        "氣溫(℃)": _num(_key_ci(el, "AirTemperature")),
        "相對溼度(%)": _num(_key_ci(el, "RelativeHumidity")),
        "風速(m/s)": _num(_key_ci(el, "WindSpeed")),
        "風向(360degree)": _num(_key_ci(el, "WindDirection")),
        "最大陣風(m/s)": _num(_key_ci(gust, "PeakGustSpeed")),
        "最大陣風風向(360degree)": _num(_key_ci(gust_at, "WindDirection")),
        "_daily_rain": _num(_key_ci(now, "Precipitation")),
    }
    row["露點溫度(℃)"] = dew_point(row["氣溫(℃)"], row["相對溼度(%)"])
    return row


def dew_point(temp, rh):
    """Magnus 公式（Alduchov & Eskridge 1996 係數）。"""
    if temp is None or rh is None or rh <= 0:
        return None
    gamma = math.log(rh / 100.0) + 17.625 * temp / (243.04 + temp)
    return round(243.04 * gamma / (17.625 - gamma), 1)


def _station_rows(payload, station: str) -> list[dict]:
    rows = []
    for st in _find(payload, lambda d: str(_key_ci(d, "StationId") or "") == station):
        row = parse_station(st)
        if row:
            rows.append(row)
    return rows


def latest(key: str, station: str) -> list[dict]:
    return _station_rows(_get(DATASTORE, key, {"StationId": station}), station)


def history(key: str, station: str, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """start～end 之間每個整點的快照（平台只留過去 24 小時）。一個快照檔包含全部測站，平行下載。"""
    meta = _get(HISTORY, key, {"format": "JSON", "timeFrom": f"{start:%Y-%m-%dT%H:%M:%S}",
                               "timeTo": f"{end + pd.Timedelta(hours=1):%Y-%m-%dT%H:%M:%S}"}, in_query=True)
    files = {}
    for item in _find(meta, lambda d: _key_ci(d, "ProductURL") and _key_ci(d, "DateTime")):
        t = pd.Timestamp(_key_ci(item, "DateTime"))
        if t.tzinfo is not None:
            t = t.tz_convert("Asia/Taipei").tz_localize(None)
        if t.minute == 0 and start <= t <= end:
            files[t] = _key_ci(item, "ProductURL")
    if not files:
        return []
    with ThreadPoolExecutor(max_workers=6) as pool:
        parts = pool.map(lambda url: _snapshot_rows(_request(url, key, in_query=True).content, station),
                         [files[t] for t in sorted(files)])
        return [row for part in parts for row in part]


def fetch(key: str, station: str, start, end) -> tuple[pd.DataFrame, list[str]]:
    """start～end（含）的整點觀測，欄位同訓練資料；start 那一小時只用來算逐時雨量的起點。
    回傳 (資料, 提醒)。過去快照拿不到時只用最新一筆，並在提醒裡說明。"""
    start, end = pd.Timestamp(start).floor("h"), pd.Timestamp(end).floor("h")
    notes = []
    try:
        rows = history(key, station, start, end)
    except RealtimeError as exc:
        if "授權碼" in str(exc):
            raise
        rows = []
        notes.append(f"拿不到今日稍早的整點快照（{exc}），只用最新一筆")
    rows += latest(key, station)
    if not rows:
        raise RealtimeError(f"氣象署開放資料沒有測站 {station} 在 {start:%m-%d %H:%M} 之後的觀測")
    frame = pd.DataFrame(rows)
    frame = frame[frame["觀測時間(hour)"].dt.minute == 0]
    frame = frame.drop_duplicates("觀測時間(hour)", keep="last").sort_values("觀測時間(hour)")
    frame = frame[(frame["觀測時間(hour)"] >= start) & (frame["觀測時間(hour)"] <= end)].reset_index(drop=True)
    # 當日累積雨量 → 逐時雨量：和前一整點相減；累積值變小代表換日歸零，當小時就是累積值本身
    acc = frame["_daily_rain"]
    prev_ok = frame["觀測時間(hour)"].diff() == pd.Timedelta(hours=1)
    diff = acc - acc.shift(1)
    rain = diff.where(diff >= 0, acc)
    frame["降水量(mm)"] = rain.where(prev_ok)
    frame["降水時數(hr)"] = (frame["降水量(mm)"] > 0).astype(float).where(frame["降水量(mm)"].notna())
    return frame.drop(columns="_daily_rain"), notes
