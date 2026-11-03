"""啟動 Hermes、追蹤進度、保存實驗名稱與備註。介面的紀錄放在 runs/，不動 outputs/ 的實驗紀錄。"""
import filecmp
import json
import locale
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import config, progress
from .skill import RunConfig, hermes_args, query_text, skill_markdown, skill_name
from .stations import is_complete, run_subgoals

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
    resume = can_continue(cfg.station, cfg.split)
    record["resumes"] = 0
    (run_dir / "SKILL.md").write_text(skill_markdown(cfg, resume), encoding="utf-8")
    if mode == "real":
        if upload_path:
            install_csv(upload_path, cfg.station)
        record["pid"] = _launch(run_id, cfg, api_key, resume=resume)
    else:
        (run_dir / "hermes.log").write_text("展示模式：沒有啟動 Hermes，也不會訓練模型。\n", encoding="utf-8")
    with _LOCK:
        runs = load_runs()
        runs.insert(0, record)
        _save_runs(runs)
    return record


# 上一次的 Hermes 輸出不超過這個大小，才接續舊對話（--resume）；對話越長，重讀一次越貴，
# 超過就開新對話，照 program.md 的「中斷後續跑」從實驗紀錄接著做。
RESUME_SESSION_MAX_BYTES = 200_000


def can_continue(station: str, split: str = "82") -> bool:
    """這個測站在這個切分已有實驗紀錄但還沒完成：再按開始就是接續，不是從頭來。"""
    return bool(station) and config.station_dir(station, split).exists() and not is_complete(station, split=split)


def continue_target(station: str, split: str = "82") -> dict | None:
    """要接續的介面紀錄：這個測站、這個切分最近一筆被停止或失敗的實驗。"""
    return next((r for r in load_runs() if r["station"] == station and r["status"] in ("stopped", "failed")
                 and str((r.get("config") or {}).get("split", "82")) == str(split)), None)


def continue_run(run_id: str, cfg: RunConfig, api_key: str = "") -> dict:
    """接續被中斷的實驗：沿用同一筆紀錄（名稱、備註），技能加上「中斷後續跑」，Hermes 從實驗紀錄接著做。"""
    run = get_run(run_id)
    run_dir = config.state_dir() / run_id
    count = int(run.get("resumes") or 0) + 1
    (run_dir / "SKILL.md").write_text(skill_markdown(cfg, resume=True), encoding="utf-8")
    fields = {"status": "running", "ended": None, "resumes": count, "config": cfg.to_dict(), "model": cfg.model}
    if run["mode"] == "real":
        log = Path(run["log"])
        session = session_id(run) if log.exists() and log.stat().st_size <= RESUME_SESSION_MAX_BYTES else ""
        fields["pid"] = _launch(run_id, cfg, api_key, resume=True, session=session, note=f"第 {count} 次接續")
    else:
        fields["started"] = time.time()
    return _update(run_id, **fields)


def _launch(run_id: str, cfg: RunConfig, api_key: str, resume: bool, session: str = "", note: str = "") -> int:
    cmd = config.hermes_command()
    if not cmd:
        raise RuntimeError("找不到 Hermes CLI；設定 HERMES_CMD 或改用展示模式")
    if not (config.data_dir() / f"{cfg.station}.csv").exists():
        raise ValueError(f"data/{cfg.station}.csv 不存在：請上傳這個測站的 CSV")
    run_dir = config.state_dir() / run_id
    skill_dir = config.hermes_home() / "skills" / "research" / skill_name(cfg)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill_markdown(cfg, resume), encoding="utf-8")
    query = run_dir / "prompt.txt"
    query.write_text(query_text(cfg, resume), encoding="utf-8")
    # 請子程式用 UTF-8 輸出；就算它不理（例如用 -I 啟動的 Python），讀取端也會自己判斷編碼
    env = {**os.environ, "RAIN_STATION": cfg.station, "RAIN_SPLIT": cfg.split,
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "LANG": os.environ.get("LANG") or "C.UTF-8"}
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(cmd + hermes_args(cfg, str(config.rain_root()), str(query), api_key, session),
                            cwd=config.rain_root(), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")
    log_path = run_dir / "hermes.log"
    mode = "a" if note else "w"
    with open(log_path, mode, encoding="utf-8") as handle:
        if note:
            handle.write(f"\n===== {note}（{'接續舊對話 ' + session if session else '開新對話'}）=====\n")
    threading.Thread(target=_pump, args=(proc.stdout, log_path), daemon=True).start()
    _PROCS[run_id] = proc
    return proc.pid


def decode_line(raw: bytes) -> str:
    """不論在 Windows、Linux 或 Docker：先試 UTF-8，不行再試系統編碼（例如 Windows 繁中的 cp950），最後才用替代字元。"""
    for encoding in ("utf-8", locale.getpreferredencoding(False), "cp950", "gb18030"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _pump(stream, log_path: Path) -> None:
    """一行一行讀 Hermes 的輸出，轉成 UTF-8 寫進 log。"""
    with open(log_path, "a", encoding="utf-8") as handle:
        for raw in iter(stream.readline, b""):
            handle.write(decode_line(raw.rstrip(b"\r\n")) + "\n")
            handle.flush()
    stream.close()


def session_id(run: dict) -> str:
    """從 Hermes 輸出找對話 ID（`Session: <id>` 或 stream-json 的 session_id）。"""
    path = Path(run.get("log") or "")
    if not path.exists():
        return ""
    found = ""
    for line in _read_lines(path):
        match = re.search(r"^Session:\s*(\S+)", line) or re.search(r'"session_id":\s*"([^"]+)"', line)
        if match:
            found = match.group(1)
    return found


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
    p = progress.detect(run["station"], run["started"], run_subgoals(run.get("config") or {}),
                        split=str((run.get("config") or {}).get("split", "82")))
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


def _read_lines(path: Path) -> list[str]:
    """逐行判斷編碼；舊版直接寫入的 log（Windows 上是 cp950）也讀得出來。"""
    return [decode_line(raw) for raw in path.read_bytes().splitlines()]


def log_tail(run: dict, lines: int = 40) -> str:
    path = Path(run.get("log") or "")
    if not path.exists():
        return ""
    return "\n".join(_read_lines(path)[-lines:])
