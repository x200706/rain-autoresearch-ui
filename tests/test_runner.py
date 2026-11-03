import os
import sys
import textwrap
import time

import pytest

from conftest import make_csv, make_station
from rainui import runner
from rainui.skill import RunConfig

FAKE_HERMES = textwrap.dedent('''
    """假的 Hermes：照真實順序寫出實驗檔案，最後補上報告。只用來測介面。"""
    import os, pathlib, shutil, sys, time
    root = pathlib.Path(sys.argv[sys.argv.index("--in") + 1])
    station = os.environ["RAIN_STATION"]
    src, dst = root / "outputs" / "467590", root / "outputs" / station
    print("args", " ".join(a for a in sys.argv[1:] if not a.startswith("sk-")), flush=True)
    time.sleep(0.5)
    shutil.copytree(src, dst)
    (dst / "learnings.md").touch()
    (dst / "ablation.tsv").touch()
    print("done", flush=True)
''')


def cfg(station="466930"):
    return RunConfig(station=station, run_name="竹子湖 第一次", model="deepseek/deepseek-v4.1-flash-1017")


def test_demo_run_is_recorded_and_finishes(rain_root, monkeypatch):
    run = runner.start_run(cfg(), mode="demo")
    assert runner.get_run(run["id"])["name"] == "竹子湖 第一次"
    monkeypatch.setattr(runner.time, "time", lambda: run["started"] + 10_000)
    done, p = runner.poll(run["id"])
    assert done["status"] == "done" and p.complete


def test_real_run_launches_hermes_and_picks_up_results(rain_root, tmp_path, monkeypatch):
    make_station(rain_root, "467590")
    fake = tmp_path / "fake_hermes.py"
    fake.write_text(FAKE_HERMES, encoding="utf-8")
    monkeypatch.setenv("HERMES_CMD", f"{sys.executable}|{fake}")
    upload = make_csv(tmp_path / "up" / "466930.csv")
    run = runner.start_run(cfg(), api_key="sk-or-v1-" + "x" * 32, mode="real", upload_path=str(upload))
    assert (rain_root / "data" / "466930.csv").exists()
    skill_file = tmp_path / "hermes_home" / "skills" / "research" / run["skill"] / "SKILL.md"
    assert skill_file.exists() and "測站：466930" in skill_file.read_text(encoding="utf-8")
    deadline = time.time() + 30
    while time.time() < deadline:
        run, p = runner.poll(run["id"])
        if run["status"] != "running":
            break
        time.sleep(0.3)
    assert run["status"] == "done" and p.complete
    log = runner.log_tail(run)
    assert "--query-file" in log and "sk-or-v1" not in log
    assert "sk-or-v1" not in (rain_root.parent / "ui_state" / "runs.json").read_text(encoding="utf-8")


def test_real_run_that_exits_without_results_is_failed(rain_root, tmp_path, monkeypatch):
    fake = tmp_path / "quit.py"
    fake.write_text("print('bye')\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_CMD", f"{sys.executable}|{fake}")
    make_csv(rain_root / "data" / "466930.csv")
    run = runner.start_run(cfg(), mode="real")
    runner._PROCS[run["id"]].wait(timeout=30)
    run, _ = runner.poll(run["id"])
    assert run["status"] == "failed"


def test_install_csv_never_overwrites_a_different_file(rain_root, tmp_path):
    make_csv(rain_root / "data" / "466930.csv", rain=(1, 2, 3))
    other = make_csv(tmp_path / "466930.csv", rain=(9, 9, 9))
    with pytest.raises(ValueError):
        runner.install_csv(str(other), "466930")
    same = make_csv(tmp_path / "same" / "466930.csv", rain=(1, 2, 3))
    assert runner.install_csv(str(same), "466930").endswith("466930.csv")


def test_notes_are_saved_per_run_and_per_station(rain_root):
    run = runner.start_run(cfg(), mode="demo")
    runner.save_notes(run["id"], "α 高時高估多")
    assert runner.get_run(run["id"])["notes"] == "α 高時高估多"
    runner.save_station_notes("467590", "恆春備註")
    assert runner.load_station_notes("467590") == "恆春備註"
    assert not (rain_root / "outputs" / "467590").exists()          # 備註不寫進實驗紀錄


def test_run_with_fewer_subgoals_finishes_when_those_stop(rain_root):
    from conftest import write_tsv
    sd = make_station(rain_root, "466930")
    rows = [{"subgoal": "under", "decision": "stop", "runs": 2}, {"subgoal": "total", "decision": "continue", "runs": 0},
            {"subgoal": "rmse", "decision": "continue", "runs": 0}]
    write_tsv(sd / "ablation.tsv", ["subgoal", "decision", "runs"], rows)
    run = runner.start_run(RunConfig(station="466930", model="m", subgoals=["under"]), mode="demo")
    assert runner.progress.detect("466930", 0.0, ["under"]).complete
    assert not runner.progress.detect("466930", 0.0, ["under", "total"]).complete
    assert run["config"]["subgoals"] == ["under"]
