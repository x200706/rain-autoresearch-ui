"""從 outputs/<station>/ 的檔案判斷實驗走到哪一步，並畫成簡化的論文流程圖（圖 3.4）。"""
import csv
import html
import re
from dataclasses import dataclass
from pathlib import Path

from . import config
from .stations import LATEST, SUBGOAL_ORDER, SUBGOALS, expected_subgoals, subgoals_stopped

STAGES = [
    ("spec", "讀取規範", "program.md 與技能"),
    ("prep", "資料前處理", "清理、切分、特徵"),
    ("gate", "第一階段 LightGBM", "訓練後凍結"),
    ("card", "測站資訊卡", "WMAE 權重"),
    ("control", "對照組", "預設參數＋純 MAE"),
    ("loop", "代理迴圈", "三種副目標輪流搜尋"),
    ("report", "彙整報告", "消融比較與學習紀錄"),
]
LOOP_STEPS = [("breed", "產生子代"), ("train", "訓練 LSTM"), ("judge", "評估與紀錄")]
STAGE_INDEX = {key: i for i, (key, _, _) in enumerate(STAGES)}


@dataclass
class Progress:
    stage: str = "spec"
    subgoal: str = ""
    step: str = ""
    generation: int = 0
    runs: int = 0
    complete: bool = False
    detail: str = ""


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines(), delimiter="\t"))


def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


def detect(station: str, started: float = 0.0, expected=LATEST, split: str = "82") -> Progress:
    """started 之後才出現或更新的「完成」檔案才算數，避免舊紀錄讓新實驗一開始就顯示完成。
    expected：這次要跑的副目標（stations.run_subgoals）；預設照這個測站最近一次介面實驗。"""
    sd = config.station_dir(station, split)          # 7:3 等其他切分的紀錄在 outputs/<站號>_split<切分>
    if not sd.exists():
        return Progress("spec", detail="讀取 program.md 與介面產生的技能")
    gate_dir = sd / "experiments" / "g00_gate"
    if not (sd / "gate.json").exists():
        if (gate_dir / "processed.csv").exists():
            return Progress("gate", detail="訓練雙 LightGBM 有雨／無雨分類器")
        return Progress("prep", detail="全域資料前處理")
    if not (sd / "station_card.json").exists():
        return Progress("card", detail="統計各雨量區間時數，計算 WMAE 權重")
    if not (sd / "control.json").exists():
        return Progress("control", detail="預設參數＋純 MAE 訓練一次")
    learnings, ablation = sd / "learnings.md", sd / "ablation.tsv"
    if expected == LATEST:
        expected = expected_subgoals(station)
    if _mtime(learnings) > started and _mtime(ablation) > started and subgoals_stopped(ablation, expected):
        return Progress("report", complete=True, detail="報告與學習紀錄已完成")
    if _mtime(ablation) > started:
        return Progress("report", detail="彙整消融比較表與學習紀錄")
    current = next((s for s in reversed(SUBGOAL_ORDER) if (sd / f"subgoal_{s}").exists()), "under")
    sdir = sd / f"subgoal_{current}"
    rows = _rows(sdir / "results.tsv")
    gen = max((int(r["generation"]) for r in rows), default=1)
    roulettes = sorted((sdir / "roulette").glob("g*.json")) if (sdir / "roulette").exists() else []
    if roulettes:
        gen = max(gen, int(re.sub(r"\D", "", roulettes[-1].stem)))
    experiments = sdir / "experiments"
    running = [p for p in experiments.iterdir() if p.is_dir() and not (p / "metrics" / "result.json").exists()] \
        if experiments.exists() else []
    if running:
        step = "train"
    elif roulettes and _mtime(roulettes[-1]) > _mtime(sdir / "results.tsv"):
        step = "breed"
    else:
        step = "judge"
    return Progress("loop", subgoal=current, step=step, generation=gen, runs=len(rows),
                    detail=f"{SUBGOALS[current]['tab']}・第 {gen} 代・已紀錄 {len(rows)} 次")


def demo_progress(elapsed: float, seconds_per_step: float = 4.0) -> Progress:
    """展示模式沒有真的訓練，依經過時間走完一輪流程。"""
    tick = int(elapsed // seconds_per_step)
    linear = ["spec", "prep", "gate", "card", "control"]
    if tick < len(linear):
        return Progress(linear[tick], detail="展示模式：" + STAGES[tick][1])
    tick -= len(linear)
    loop_ticks = len(SUBGOAL_ORDER) * 2 * len(LOOP_STEPS)        # 每種副目標示範兩代
    if tick < loop_ticks:
        sub = SUBGOAL_ORDER[tick // (2 * len(LOOP_STEPS))]
        gen = 3 + (tick // len(LOOP_STEPS)) % 2
        step = LOOP_STEPS[tick % len(LOOP_STEPS)][0]
        return Progress("loop", subgoal=sub, step=step, generation=gen,
                        detail=f"展示模式：{SUBGOALS[sub]['tab']}・第 {gen} 代")
    if tick == loop_ticks:
        return Progress("report", detail="展示模式：彙整報告")
    return Progress("report", complete=True, detail="展示結束：沒有真的訓練，所以沒有新結果")


def flow_html(p: Progress) -> str:
    """簡化流程圖：已完成的節點打勾、目前節點高亮；代理迴圈畫成三個節點繞成的圈。"""
    current = STAGE_INDEX.get(p.stage, 0)
    nodes = []
    for i, (key, title, sub) in enumerate(STAGES):
        state = "done" if (i < current or p.complete) else ("now" if i == current else "todo")
        if key == "loop":
            nodes.append(_loop_node(p, state))
            continue
        mark = "✓" if state == "done" else str(i + 1)
        nodes.append(f'<div class="fl-node fl-{state}"><span class="fl-num">{mark}</span>'
                     f'<span class="fl-title">{html.escape(title)}</span><span class="fl-sub">{html.escape(sub)}</span></div>')
    bar = '<div class="fl-arrow" aria-hidden="true"></div>'.join(nodes)
    status = "完成" if p.complete else html.escape(p.detail)
    return f'<div class="flow" role="img" aria-label="實驗進度：{status}"><div class="fl-row">{bar}</div>' \
           f'<div class="fl-status">{status}</div></div>'


def _loop_node(p: Progress, state: str) -> str:
    steps = []
    for key, title in LOOP_STEPS:
        active = state == "now" and p.step == key
        steps.append(f'<span class="fl-step{" fl-step-now" if active else ""}">{title}</span>')
    subs = []
    for s in SUBGOAL_ORDER:
        done = state == "done" or (state == "now" and SUBGOAL_ORDER.index(s) < SUBGOAL_ORDER.index(p.subgoal or "under"))
        now = state == "now" and s == p.subgoal
        cls = "fl-chip-now" if now else ("fl-chip-done" if done else "")
        subs.append(f'<span class="fl-chip {cls}">{html.escape(SUBGOALS[s]["short"])}</span>')
    gen = f'<span class="fl-gen">第 {p.generation} 代</span>' if state == "now" and p.generation else ""
    return (f'<div class="fl-node fl-loop fl-{state}"><span class="fl-title">代理迴圈 {gen}</span>'
            f'<div class="fl-ring"><svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="16"/></svg>'
            f'<div class="fl-steps">{"".join(steps)}</div></div><div class="fl-chips">{"".join(subs)}</div></div>')
