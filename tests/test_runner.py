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


def test_log_decoding_handles_utf8_and_windows_big5():
    assert runner.decode_line("讀取 program.md".encode("utf-8")) == "讀取 program.md"
    assert runner.decode_line("讀取 program.md".encode("cp950")) == "讀取 program.md"


FAKE_BIG5_HERMES = textwrap.dedent('''
    """假的 Hermes：像 Windows 上用 -I 啟動的 Python 一樣，輸出 cp950，不理 PYTHONIOENCODING。"""
    import sys
    sys.stdout.buffer.write("Session: sess-123\\n".encode("cp950"))
    sys.stdout.buffer.write(("我先讀取 program.md " + " ".join(sys.argv[1:])).encode("cp950") + b"\\n")
    sys.stdout.flush()
''')


def _wait_exit(run_id):
    runner._PROCS[run_id].wait(timeout=30)
    for _ in range(50):                        # 等讀取執行緒把最後幾行寫完
        if "program.md" in (runner.log_tail(runner.get_run(run_id)) or ""):
            break
        time.sleep(0.1)


def test_continue_reuses_the_record_and_resumes_a_short_session(rain_root, tmp_path, monkeypatch):
    fake = tmp_path / "big5_hermes.py"
    fake.write_text(FAKE_BIG5_HERMES, encoding="utf-8")
    monkeypatch.setenv("HERMES_CMD", f"{sys.executable}|{fake}")
    make_csv(rain_root / "data" / "466930.csv")
    (rain_root / "outputs" / "466930" / "experiments" / "g00_gate").mkdir(parents=True)   # 做到一半
    assert runner.can_continue("466930")
    run = runner.start_run(cfg(), mode="real")
    _wait_exit(run["id"])
    log = runner.log_tail(runner.get_run(run["id"]))
    assert "我先讀取 program.md" in log                     # cp950 輸出也不會變亂碼
    assert "中斷後續跑" in (tmp_path / "ui_state" / run["id"] / "prompt.txt").read_text(encoding="utf-8")
    runner.poll(run["id"])
    assert runner.get_run(run["id"])["status"] == "failed"   # 沒做完就結束
    assert runner.continue_target("466930")["id"] == run["id"]

    again = runner.continue_run(run["id"], cfg())
    assert again["id"] == run["id"] and again["status"] == "running" and again["resumes"] == 1
    assert [r["id"] for r in runner.load_runs()] == [run["id"]]          # 沒有新增一筆
    _wait_exit(run["id"])
    log = runner.log_tail(runner.get_run(run["id"]))
    assert "第 1 次接續（接續舊對話 sess-123）" in log and "--resume sess-123" in log
    skill = (tmp_path / "ui_state" / run["id"] / "SKILL.md").read_text(encoding="utf-8")
    assert "## 中斷後續跑" in skill


def test_long_session_is_not_resumed(rain_root, tmp_path, monkeypatch):
    fake = tmp_path / "big5_hermes.py"
    fake.write_text(FAKE_BIG5_HERMES, encoding="utf-8")
    monkeypatch.setenv("HERMES_CMD", f"{sys.executable}|{fake}")
    monkeypatch.setattr(runner, "RESUME_SESSION_MAX_BYTES", 10)
    make_csv(rain_root / "data" / "466930.csv")
    (rain_root / "outputs" / "466930").mkdir(parents=True)
    run = runner.start_run(cfg(), mode="real")
    _wait_exit(run["id"])
    runner.poll(run["id"])
    runner.continue_run(run["id"], cfg())
    _wait_exit(run["id"])
    log = runner.log_tail(runner.get_run(run["id"]))
    assert "第 1 次接續（開新對話）" in log and "--resume" not in log.split("第 1 次接續")[1]


def test_continue_looks_at_the_split_directory(rain_root):
    (rain_root / "outputs" / "467350_split73" / "experiments").mkdir(parents=True)
    assert runner.can_continue("467350", "73") and not runner.can_continue("467350", "82")
    assert runner.progress.detect("467350", split="73").stage == "prep"
    assert runner.progress.detect("467350", split="82").stage == "spec"
