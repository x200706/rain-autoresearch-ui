"""啟動 Hermes、追蹤進度、保存實驗名稱與備註。介面的紀錄放在 runs/，不動 outputs/ 的實驗紀錄。"""
import filecmp
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import config, progress
from .skill import RunConfig, hermes_args, query_text, skill_markdown, skill_name

_LOCK = threading.Lock()
_PROCS: dict[str, subprocess.Popen] = {}


def _registry_path() -> Path:
    return config.state_dir() / "runs.json"


def load_runs() -> list[dict]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_runs(runs: list[dict]) -> None:
    path = _registry_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def get_run(run_id: str) -> dict | None:
    return next((r for r in load_runs() if r["id"] == run_id), None)


def _update(run_id: str, **fields) -> dict | None:
    with _LOCK:
        runs = load_runs()
        for r in runs:
            if r["id"] == run_id:
                r.update(fields)
                _save_runs(runs)
                return r
    return None


def install_csv(upload_path: str, station: str) -> str:
    """真的實驗要讀 data/<station>.csv：不存在才複製；已有不同內容的檔案就拒絕，不覆寫。"""
    target = config.data_dir() / f"{station}.csv"
    if target.exists():
        if filecmp.cmp(upload_path, target, shallow=False):
            return str(target)
        raise ValueError(f"data/{station}.csv 已存在且內容不同，不覆寫；請先確認要用哪一份")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(upload_path, target)
    return str(target)


def start_run(cfg: RunConfig, api_key: str = "", mode: str | None = None, upload_path: str = "") -> dict:
    mode = mode or config.run_mode()
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    run_dir = config.state_dir() / run_id
    run_dir.mkdir(parents=True)
    record = {"id": run_id, "name": cfg.run_name or f"{cfg.station} {time.strftime('%m-%d %H:%M')}",
              "station": cfg.station, "mode": mode, "model": cfg.model, "started": time.time(), "ended": None,
              "status": "running", "notes": "", "config": cfg.to_dict(), "skill": skill_name(cfg),
              "log": str(run_dir / "hermes.log"), "pid": None}
    (run_dir / "SKILL.md").write_text(skill_markdown(cfg), encoding="utf-8")
    if mode == "real":
        cmd = config.hermes_command()
        if not cmd:
            raise RuntimeError("找不到 Hermes CLI；設定 HERMES_CMD 或改用展示模式")
        if upload_path:
            install_csv(upload_path, cfg.station)
        if not (config.data_dir() / f"{cfg.station}.csv").exists():
            raise ValueError(f"data/{cfg.station}.csv 不存在：請上傳這個測站的 CSV")
        skill_dir = config.hermes_home() / "skills" / "research" / skill_name(cfg)
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_markdown(cfg), encoding="utf-8")
        query = run_dir / "prompt.txt"
        query.write_text(query_text(cfg), encoding="utf-8")
        env = {**os.environ, "RAIN_STATION": cfg.station, "RAIN_SPLIT": cfg.split, "PYTHONIOENCODING": "utf-8"}
        log = open(run_dir / "hermes.log", "w", encoding="utf-8")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(cmd + hermes_args(cfg, str(config.rain_root()), str(query), api_key),
                                cwd=config.rain_root(), env=env, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")
        _PROCS[run_id] = proc
        record["pid"] = proc.pid
    else:
        (run_dir / "hermes.log").write_text("展示模式：沒有啟動 Hermes，也不會訓練模型。\n", encoding="utf-8")
    with _LOCK:
        runs = load_runs()
        runs.insert(0, record)
        _save_runs(runs)
    return record


def poll(run_id: str) -> tuple[dict | None, progress.Progress]:
    """更新並回傳實驗狀態。完成條件由 outputs/ 的檔案決定，不靠 Hermes 自己說完成。"""
    run = get_run(run_id)
    if run is None:
        return None, progress.Progress()
    if run["mode"] == "demo":
        p = progress.demo_progress(time.time() - run["started"])
        if p.complete and run["status"] == "running":
            run = _update(run_id, status="done", ended=time.time())
        return run, p
    p = progress.detect(run["station"], run["started"])
    if run["status"] != "running":
        return run, p
    proc = _PROCS.get(run_id)
    alive = proc.poll() is None if proc else _pid_alive(run.get("pid"))
    if p.complete:
        run = _update(run_id, status="done", ended=time.time())
    elif not alive:
        code = proc.returncode if proc else None
        run = _update(run_id, status="failed", ended=time.time(), exit_code=code)
    return run, p


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_run(run_id: str) -> dict | None:
    run = get_run(run_id)
    if not run or run["status"] != "running":
        return run
    if run["mode"] == "real" and run.get("pid"):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(run["pid"]), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(run["pid"], signal.SIGTERM)
            except OSError:
                pass
    return _update(run_id, status="stopped", ended=time.time())


def delete_run(run_id: str) -> None:
    """刪掉介面的實驗紀錄（名稱、備註、Hermes 輸出）；還在跑就先停。outputs/ 的實驗結果不在這裡刪。"""
    stop_run(run_id)
    with _LOCK:
        _save_runs([r for r in load_runs() if r["id"] != run_id])
    shutil.rmtree(config.state_dir() / run_id, ignore_errors=True)


def delete_station(station: str) -> bool:
    """刪除 outputs/<站號>（使用者在介面上確認過才會呼叫）與這個測站的備註。回傳是否有東西被刪。"""
    source = config.outputs_dir() / station
    notes = station_notes_path(station)
    if notes.exists():
        notes.unlink()
    if not source.exists():
        return False
    shutil.rmtree(source)
    return True


def save_notes(run_id: str, notes: str) -> dict | None:
    return _update(run_id, notes=notes)


def station_notes_path(station: str) -> Path:
    return config.state_dir() / "notes" / f"{station}.md"


def load_station_notes(station: str) -> str:
    path = station_notes_path(station)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_station_notes(station: str, notes: str) -> None:
    path = station_notes_path(station)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(notes, encoding="utf-8")


def log_tail(run: dict, lines: int = 40) -> str:
    path = Path(run.get("log") or "")
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])
