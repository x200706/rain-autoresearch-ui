"""測站名稱、可選測站清單與上傳 CSV 的檢查。"""
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import config

NAMES = {
    "466910": "鞍部", "466930": "竹子湖", "466990": "花蓮", "467080": "宜蘭", "467350": "澎湖",
    "467410": "臺南", "467480": "嘉義", "467490": "臺中", "467571": "新竹", "467590": "恆春",
    "467610": "成功", "467650": "日月潭",
}
TIME_COL, RAIN_COL = "觀測時間(hour)", "降水量(mm)"
SUBGOAL_ORDER = ("under", "total", "rmse")
SUBGOALS = {
    "under": {"tab": "副目標：AE ≥ 20 mm 低估筆數", "short": "AE ≥ 20 mm 低估筆數",
              "desc": "AE ≥ 20 mm 的低估筆數不超過第 1 代", "metric": "count_under_ge20"},
    "total": {"tab": "副目標：AE ≥ 20 mm 高估＋低估筆數", "short": "AE ≥ 20 mm 高估＋低估筆數",
              "desc": "AE ≥ 20 mm 的高估加低估筆數不超過第 1 代", "metric": "count_big_ge20"},
    "rmse": {"tab": "副目標：整體 RMSE", "short": "整體 RMSE", "desc": "整體 RMSE 不劣於第 1 代", "metric": "overall_rmse"},
}


def label(station: str) -> str:
    name = NAMES.get(station, "")
    return f"{station} {name}".strip()


LATEST = "latest"   # is_complete／progress.detect 的預設：照這個測站最近一次介面實驗選的副目標


def run_subgoals(cfg: dict) -> list | None:
    """一次介面實驗要跑的副目標。預設副目標回傳勾選的那幾種；一句話自訂的副目標名稱由 Hermes 寫進程式，
    介面事先不知道，回傳 None。"""
    if cfg.get("sub_mode") == "semantic":
        return None
    return [s for s in SUBGOAL_ORDER if s in (cfg.get("subgoals") or [])]


def expected_subgoals(station: str) -> list | None:
    """這個測站最近一次真的實驗（展示模式不算）選的副目標；沒有介面紀錄、直接照 program.md 跑的測站是三種預設副目標。"""
    path = config.state_dir() / "runs.json"
    try:
        runs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except json.JSONDecodeError:
        runs = []
    run = next((r for r in runs if r.get("station") == station and r.get("mode") == "real"), None)
    return run_subgoals(run.get("config") or {}) if run else list(SUBGOAL_ORDER)


def subgoals_stopped(ablation: Path, expected: list | None) -> bool:
    """ablation.tsv 的 decision 欄（budget_guard.py ablation 依程式的停止規則寫出）裡，這次要跑的副目標都是 stop。
    expected 為 None（自訂副目標）時，看有紀錄（runs > 0）的副目標，至少一種且全部 stop；沒跑的預設副目標不算。"""
    if not ablation.exists():
        return False
    rows = pd.read_csv(ablation, sep="\t", dtype=str).fillna("")
    subs = rows[~rows["subgoal"].isin(["generation1", "control"])]
    if expected is None:
        ran = subs[pd.to_numeric(subs["runs"], errors="coerce").fillna(0) > 0]
        return len(ran) > 0 and bool((ran["decision"] == "stop").all())
    decision = dict(zip(subs["subgoal"], subs["decision"]))
    return bool(expected) and all(decision.get(s) == "stop" for s in expected)


def is_complete(station: str, expected=LATEST, split: str = "82") -> bool:
    """這次要跑的副目標都已停止，且學習紀錄已寫好。判定照抄 ablation.tsv 的 decision 欄，介面不自己推論；
    第 2 代就停止（best 是第 1 代）的副目標也是 stop，算完成。"""
    sd = config.station_dir(station, split)
    if not (sd / "learnings.md").exists():
        return False
    if expected == LATEST:
        expected = expected_subgoals(station)
    return subgoals_stopped(sd / "ablation.tsv", expected)


def station_choices() -> list[tuple[str, str]]:
    """下拉選單：已完成的測站，以及 data/ 有資料但還沒完成的測站。上傳的檔案不會進這份清單。"""
    out_dir, data_dir = config.outputs_dir(), config.data_dir()
    ids = set()
    if out_dir.exists():
        ids |= {p.name for p in out_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{6}", p.name)}
    if data_dir.exists():
        ids |= {p.stem for p in data_dir.glob("*.csv") if re.fullmatch(r"\d{6}", p.stem)}
    done, other = [], []
    for sid in sorted(ids):
        if is_complete(sid):
            done.append((f"{label(sid)}（已完成）", sid))
        elif (out_dir / sid).exists():
            other.append((f"{label(sid)}（未完成）", sid))
        else:
            other.append((f"{label(sid)}（尚未實驗）", sid))
    return done + other


def completed_stations() -> list[str]:
    return [sid for _, sid in station_choices() if is_complete(sid)]


@dataclass
class CsvCheck:
    name: str
    station: str = ""
    rows: int = 0
    rain: list = field(default_factory=list, repr=False)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def hours_at_least(self, threshold: float) -> int:
        return sum(1 for v in self.rain if v >= threshold)


def check_csv(path: str | Path, original_name: str | None = None) -> CsvCheck:
    """上傳檔案的格式檢查：檔名要有 6 碼站號、要有逐時時間與降水量欄位。"""
    name = original_name or Path(path).name
    found = re.search(r"(\d{6})", name)
    result = CsvCheck(name=name, station=found.group(1) if found else "")
    if not found:
        result.errors.append("檔名裡找不到 6 碼站號（例：466930.csv）")
    try:
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8-sig").lstrip("﻿")
        frame = pd.read_csv(io.StringIO(text), dtype=str)
    except Exception as exc:  # noqa: BLE001 — 任何讀檔錯誤都只回報給使用者
        result.errors.append(f"讀不到 CSV：{exc}")
        return result
    frame.columns = [c.strip().lstrip("﻿") for c in frame.columns]
    missing = [c for c in (TIME_COL, RAIN_COL) if c not in frame.columns]
    if missing:
        result.errors.append("找不到欄位：" + "、".join(missing))
        return result
    result.rows = len(frame)
    result.rain = pd.to_numeric(frame[RAIN_COL], errors="coerce").fillna(-1).tolist()
    if result.rows == 0:
        result.errors.append("檔案沒有任何資料列")
    return result
