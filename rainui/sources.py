"""測站清單（氣象署 hdps 現存測站表）與中興大學歷史氣象資料庫下載。"""
import io
import time
from datetime import date
from functools import lru_cache

import pandas as pd
import requests

from . import config

STATION_TABLE_URL = "https://hdps.cwa.gov.tw/static/state.html"
NCHU_URL = "https://mycolab.pp.nchu.edu.tw/historical_weather/index.php"
NCHU_START = "20090101"
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


def nchu_download(station: str, end: date | None = None) -> str:
    """從中興大學資料庫抓 2009-01-01 到今天的逐時資料，存到介面的 runs/nchu/<站號>.csv，回傳路徑。
    抓不到或回傳空資料就丟出 ValueError，訊息直接顯示給使用者。"""
    end = end or date.today()
    try:
        resp = requests.get(NCHU_URL, params={"station_id": station, "startdate": NCHU_START,
                                              "enddate": end.strftime("%Y%m%d")}, timeout=600)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"連不上中興大學資料庫：{exc}") from exc
    content = resp.content
    head = content.lstrip()[:100].lower()
    if not content.strip() or head.startswith((b"<!doctype html", b"<html")):
        raise ValueError(f"中興大學資料庫沒有 {station} 的資料，這個測站不能用")
    try:
        frame = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig", low_memory=False)
    except Exception:  # noqa: BLE001
        raise ValueError(f"中興大學資料庫回傳的 {station} 資料讀不懂，這個測站不能用") from None
    if frame.empty:
        raise ValueError(f"中興大學資料庫沒有 {station} 的資料，這個測站不能用")
    folder = config.state_dir() / "nchu"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{station}.csv"
    tmp = path.with_suffix(f".{time.time_ns()}.part")
    tmp.write_bytes(content)
    tmp.replace(path)
    return str(path)
