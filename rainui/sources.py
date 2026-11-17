"""測站清單（氣象署 hdps 現存測站表）與 CoDiS 2009 年至今的逐時資料下載。"""
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import pandas as pd
import requests

from . import config

STATION_TABLE_URL = "https://hdps.cwa.gov.tw/static/state.html"
HISTORY_START = pd.Timestamp("2009-01-01")
BUNDLED = config.UI_ROOT / "data" / "cwa_stations.csv"
# 選單第一層：站種；署屬自動站依站號再分自動氣象站（C0）與自動雨量站（其他）
KINDS = ["有人站", "自動氣象站", "自動雨量站", "農業站"]


def _kind(row) -> str:
    if row["站種"] == "署屬有人站":
        return "有人站"
    if row["站種"] == "農業站":
        return "農業站"
    return "自動氣象站" if str(row["站號"]).startswith("C0") else "自動雨量站"


def parse_table(html_text: str) -> pd.DataFrame:
    """state.html 第一張表（現存測站）→ 站號、站名、站種、城市、分類。"""
    from bs4 import BeautifulSoup
    table = BeautifulSoup(html_text, "html.parser").find("table")
    rows = [[td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
    head, body = rows[0], [r for r in rows[1:] if len(r) >= 3]
    frame = pd.DataFrame([r[:len(head)] + [""] * (len(head) - len(r)) for r in body], columns=head)
    frame = frame.rename(columns={"測站ID": "站號", "測站 ID": "站號", "測站名稱": "站名", "測站類型": "站種", "縣市": "城市"})
    frame = frame[["站號", "站名", "站種", "城市"]].copy()
    frame["站號"] = frame["站號"].str.strip()
    frame["分類"] = frame.apply(_kind, axis=1)
    return frame.drop_duplicates("站號").reset_index(drop=True)


@lru_cache(maxsize=1)
def station_table() -> pd.DataFrame:
    """先抓氣象署現存測站表，抓不到用 repo 裡的備份（data/cwa_stations.csv）。"""
    try:
        resp = requests.get(STATION_TABLE_URL, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return parse_table(resp.text)
    except Exception:  # noqa: BLE001 — 離線或網站改版時用備份
        return pd.read_csv(BUNDLED, dtype=str, encoding="utf-8")


def stations_of(kind: str) -> list[tuple[str, str]]:
    table = station_table()
    rows = table[table["分類"] == kind]
    return [(f"{r.站號} {r.站名}", r.站號) for r in rows.itertuples()]


def name_of(station: str) -> str:
    try:
        match = station_table().loc[lambda t: t["站號"] == station, "站名"]
    except Exception:  # noqa: BLE001
        return ""
    return match.iloc[0] if len(match) else ""


def _station_type(station: str) -> list[str]:
    """CoDiS 的測站類別：用最近一個月試出這個站在哪一類，之後每個月都只查這一類。"""
    from . import codis
    end = pd.Timestamp.now().normalize()
    for stype in codis.station_types(station):
        if len(codis.fetch(station, end - pd.Timedelta(days=30), end, stypes=[stype])):
            return [stype]
    return []


def codis_download(station: str, end: pd.Timestamp | None = None, progress=None) -> str:
    """從 CoDiS 抓 2009-01-01 到昨天 24 時的逐時資料，存到介面的 runs/codis/<站號>.csv，回傳路徑。
    CoDiS 一次最多回傳約一個月，所以逐月抓（平行 6 個）。抓不到資料就丟出 ValueError，訊息直接顯示給使用者。"""
    from . import codis
    end = pd.Timestamp(end) if end is not None else pd.Timestamp.now().normalize()
    try:
        stypes = _station_type(station)
        if not stypes:
            raise ValueError(f"CoDiS 沒有 {station} 的資料，這個測站不能用")
        months = pd.date_range(HISTORY_START, end, freq="MS")
        spans = [(m, min(m + pd.offsets.MonthBegin(1), end)) for m in months]
        done, parts = 0, []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for part in pool.map(lambda span: codis.fetch(station, span[0], span[1], stypes=stypes), spans):
                parts.append(part)
                done += 1
                if progress:
                    progress(done / len(spans))
    except requests.RequestException as exc:
        raise ValueError(f"連不上 CoDiS：{type(exc).__name__}") from None
    frame = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame()
    if frame.empty:
        raise ValueError(f"CoDiS 沒有 {station} 的資料，這個測站不能用")
    frame = frame.drop_duplicates("觀測時間(hour)").sort_values("觀測時間(hour)")
    frame["觀測時間(hour)"] = frame["觀測時間(hour)"].dt.strftime("%Y-%m-%d %H:%M:%S")
    folder = config.state_dir() / "codis"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{station}.csv"
    tmp = path.with_suffix(f".{time.time_ns()}.part")
    frame.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)
    return str(path)
