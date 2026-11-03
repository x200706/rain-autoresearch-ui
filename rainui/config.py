"""路徑與執行模式。全部讀環境變數，測試可以改指向暫存目錄。"""
import os
import shutil
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash-1017"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


_ROOT_OVERRIDE: dict = {"path": None}


def rain_root() -> Path:
    """rain_autoresearch 專案根目錄（program.md、train.py、outputs/、data/ 所在）。介面上改過就用介面的值。"""
    if _ROOT_OVERRIDE["path"]:
        return _ROOT_OVERRIDE["path"]
    return Path(os.environ.get("RAIN_AUTORESEARCH_ROOT") or UI_ROOT.parent / "rain_autoresearch")


def set_rain_root(path: str) -> str:
    """介面設定實驗專案路徑；回傳錯誤訊息（空字串表示成功）。找不到 program.md 就不切換。"""
    target = Path(path.strip().strip('"')).expanduser()
    if not path.strip():
        _ROOT_OVERRIDE["path"] = None
        return ""
    if not (target / "program.md").exists():
        return f"{target} 裡找不到 program.md"
    _ROOT_OVERRIDE["path"] = target
    return ""


def outputs_dir() -> Path:
    return rain_root() / "outputs"


def station_dir(station: str, split: str = "82") -> Path:
    """一次實驗的紀錄目錄，與 budget_guard.py 相同：8:2 是 outputs/<站號>，其他切分是 outputs/<站號>_split<切分>。"""
    return outputs_dir() / (station if str(split) == "82" else f"{station}_split{split}")


def data_dir() -> Path:
    return rain_root() / "data"


def state_dir() -> Path:
    """介面自己的紀錄（實驗名稱、備註、Hermes 輸出）；不寫進 outputs/，避免動到實驗紀錄。"""
    path = Path(os.environ.get("RAIN_UI_STATE_DIR") or UI_ROOT / "runs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundle_path() -> Path:
    """GitHub Pages 原型用的資料檔；本機沒有 rain_autoresearch 時改讀這份。"""
    return UI_ROOT / "data" / "experiments.js"


def hermes_command() -> list[str] | None:
    """Hermes CLI。HERMES_CMD 可指定（測試用假指令），否則找 PATH 或預設安裝位置。"""
    custom = os.environ.get("HERMES_CMD")
    if custom:
        return custom.split("|")
    found = shutil.which("hermes")
    if found:
        return [found]
    for candidate in (Path.home() / "Hermes" / "bin" / "hermes.cmd", Path.home() / ".hermes" / "bin" / "hermes"):
        if candidate.exists():
            return [str(candidate)]
    return None


def hermes_home() -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"])
    for candidate in (Path.home() / "Hermes", Path.home() / ".hermes"):
        if candidate.exists():
            return candidate
    return Path.home() / ".hermes"


def run_mode() -> str:
    """real：真的啟動 Hermes；demo：只播放等待動畫。RAIN_UI_MODE 可強制指定。"""
    forced = os.environ.get("RAIN_UI_MODE", "").strip().lower()
    if forced in ("real", "demo"):
        return forced
    return "real" if hermes_command() and (rain_root() / "program.md").exists() else "demo"
