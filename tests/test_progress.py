import json
import os
import time

from conftest import RESULT_COLUMNS, make_station, write_tsv
from rainui import progress


def test_stages_follow_the_files(rain_root):
    sd = rain_root / "outputs" / "466930"
    assert progress.detect("466930").stage == "spec"
    (sd / "experiments" / "g00_gate").mkdir(parents=True)
    assert progress.detect("466930").stage == "prep"
    (sd / "experiments" / "g00_gate" / "processed.csv").write_text("x", encoding="utf-8")
    assert progress.detect("466930").stage == "gate"
    (sd / "gate.json").write_text("{}", encoding="utf-8")
    assert progress.detect("466930").stage == "card"
    (sd / "station_card.json").write_text("{}", encoding="utf-8")
    assert progress.detect("466930").stage == "control"
    (sd / "control.json").write_text(json.dumps({}), encoding="utf-8")
    p = progress.detect("466930")
    assert p.stage == "loop" and p.subgoal == "under"


def test_loop_reports_subgoal_generation_and_step(rain_root):
    sd = rain_root / "outputs" / "466930"
    for name in ("gate.json", "station_card.json", "control.json"):
        sd.mkdir(parents=True, exist_ok=True)
        (sd / name).write_text("{}", encoding="utf-8")
    sdir = sd / "subgoal_total"
    write_tsv(sdir / "results.tsv", RESULT_COLUMNS, [{"generation": 1, "candidate": 1}, {"generation": 2, "candidate": 1}])
    (sdir / "experiments" / "g03_c1").mkdir(parents=True)          # 有目錄但還沒有 result.json → 訓練中
    p = progress.detect("466930")
    assert (p.subgoal, p.step, p.generation, p.runs) == ("total", "train", 2, 2)
    (sdir / "experiments" / "g03_c1" / "metrics").mkdir()
    (sdir / "experiments" / "g03_c1" / "metrics" / "result.json").write_text("{}", encoding="utf-8")
    (sdir / "roulette").mkdir()
    (sdir / "roulette" / "g04.json").write_text("{}", encoding="utf-8")
    later = time.time() + 10
    os.utime(sdir / "roulette" / "g04.json", (later, later))
    p = progress.detect("466930")
    assert (p.step, p.generation) == ("breed", 4)


def test_old_report_does_not_count_as_finished_for_a_new_run(rain_root):
    make_station(rain_root, "467590")
    assert progress.detect("467590", started=0).complete
    assert not progress.detect("467590", started=time.time() + 60).complete


def test_flow_highlights_current_node_and_loop_step():
    p = progress.Progress("loop", subgoal="total", step="train", generation=5, detail="x")
    html = progress.flow_html(p)
    assert html.count("fl-done") >= 5 and "fl-loop fl-now" in html
    assert 'fl-step fl-step-now">訓練 LSTM' in html and "第 5 代" in html
    assert 'fl-chip fl-chip-now">AE ≥ 20 mm 高估＋低估筆數' in html


def test_demo_progress_walks_through_every_stage_and_ends():
    seen = {progress.demo_progress(t).stage for t in range(0, 200, 2)}
    assert seen == {key for key, _, _ in progress.STAGES}
    assert progress.demo_progress(10_000).complete
