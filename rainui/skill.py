"""介面設定 → Hermes 技能（SKILL.md）、啟動指令、設定指紋與欄位檢查。全是純函式，方便測試。"""
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from .stations import SUBGOAL_ORDER, SUBGOALS

DEFAULT_TEMPLATE = "\n".join([
    "# Rain Autoresearch：Agent 實驗指引",
    "",
    "測站：[[STATION]]　切分：RAIN_SPLIT=[[SPLIT]]　實驗名稱：[[RUN_NAME]]",
    "",
    "## 0. 必讀",
    "1. 主目標：[[MAIN_GOAL]]",
    "2. 副目標：",
    "[[SUB_GOALS]]",
    "3. 只看訓練期；test 只在全部停止後讀一次寫報告。",
    "4. 子代由 genome.py breed 決定，你不自己挑親代或參數值。",
    "",
    "## 3. 分代流程",
    "- 每種副目標最多 [[MAX_GEN]] 代；連續 [[PATIENCE]] 代主目標沒進步就停止。",
    "- 第 1 代跑預設值，第 2 代跑四個角落，第 3 代起每代產生 [[CHILDREN]] 個子代。",
    "- 同一代最多同時訓練 [[PARALLEL]] 個槽位。",
    "- 每次訓練後 budget_guard.py record，是否停止以程式輸出為準。",
    "",
    "（其餘規則沿用 program.md）",
])
TOKENS = ("STATION", "SPLIT", "RUN_NAME", "MAIN_GOAL", "SUB_GOALS", "MAX_GEN", "PATIENCE", "CHILDREN", "PARALLEL")
REQUIRED_TOKENS = ("MAIN_GOAL", "SUB_GOALS")
METRICS = {"mae": "MAE，越低越好", "rmse": "RMSE，越低越好", "under": "低估筆數，越少越好"}
DEFAULT_GOAL = {"metric": "mae", "threshold": 40.0, "sub_mode": "preset", "subgoals": list(SUBGOAL_ORDER)}


@dataclass
class RunConfig:
    station: str = ""
    split: str = "82"
    run_name: str = ""
    model: str = ""
    metric: str = "mae"
    threshold: float = 40.0
    sub_mode: str = "preset"            # preset：預設三種擇一或多選；semantic：一句話描述
    subgoals: list = field(default_factory=lambda: list(SUBGOAL_ORDER))
    sub_text: str = ""
    max_gen: int = 20
    patience: int = 3
    children: int = 8
    parallel: int = 3
    template: str = DEFAULT_TEMPLATE

    def to_dict(self):
        return asdict(self)


def goal_key(cfg: RunConfig) -> str:
    base = "count_under" if cfg.metric == "under" else cfg.metric
    return f"{base}_ge{_num(cfg.threshold)}mm"


def goal_desc(cfg: RunConfig) -> str:
    return f"訓練期實際雨量 ≥ {_num(cfg.threshold)} mm 時段的 {METRICS.get(cfg.metric, cfg.metric)}"


def _num(value) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def is_default_goal(cfg: RunConfig) -> bool:
    return (cfg.metric == DEFAULT_GOAL["metric"] and float(cfg.threshold) == DEFAULT_GOAL["threshold"]
            and cfg.sub_mode == "preset" and sorted(cfg.subgoals) == sorted(DEFAULT_GOAL["subgoals"]))


def subgoal_lines(cfg: RunConfig) -> str:
    if cfg.sub_mode == "semantic":
        return ("   - 使用者描述：「" + (cfg.sub_text.strip() or "（尚未填寫）") + "」\n"
                "   - 請把這段描述轉成可由程式檢查的副目標條件，先回報再開始。")
    if not cfg.subgoals:
        return "   - （未勾選）"
    return "\n".join(f"   - `{s}`：{SUBGOALS[s]['desc']}（各跑一次完整搜尋）"
                     for s in SUBGOAL_ORDER if s in cfg.subgoals)


def override_section(cfg: RunConfig) -> str:
    """主／副目標和 program.md 預設不同時，要求 Hermes 先改程式再開始；這一節優先於 program.md。"""
    if is_default_goal(cfg):
        return ""
    lines = [
        "## 介面覆寫（優先級最高）",
        "本次的主目標或副目標由介面指定，與 program.md 的預設（主目標 ≥ 40 mm 的 MAE、三種副目標）不同。"
        "本節優先於 program.md 與程式中的預設值。",
        f"- 主目標：`{goal_key(cfg)}` = {goal_desc(cfg)}",
        "- 副目標：",
        subgoal_lines(cfg),
        "",
        "開始任何訓練前：",
        "1. 修改對應程式，讓程式計算與判定的就是上面的目標：`budget_guard.py` 的主目標"
        "（`PRIMARY_MM` 與主目標指標）、`SUBGOALS`，以及 `program.md` 第 0 節的說明。",
        "2. 只跑上面列出的副目標，順序依 under → total → rmse。",
        "3. 執行 `python tests/test_budget_guard.py`，全部通過後回報修改了哪些檔案與差異，再開始實驗。",
        "4. 之後是否繼續、誰是 best，一律以修改後的程式輸出為準。",
        "",
    ]
    return "\n".join(lines)


def render(cfg: RunConfig) -> str:
    values = {"STATION": cfg.station, "SPLIT": cfg.split, "RUN_NAME": cfg.run_name or "（未命名）",
              "MAIN_GOAL": f"`{goal_key(cfg)}` = {goal_desc(cfg)}", "SUB_GOALS": subgoal_lines(cfg),
              "MAX_GEN": cfg.max_gen, "PATIENCE": cfg.patience, "CHILDREN": cfg.children, "PARALLEL": cfg.parallel}
    body = re.sub(r"\[\[([A-Z_]+)\]\]", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
                  cfg.template.replace("\r", ""))
    section = override_section(cfg)
    if section:
        first, _, rest = body.partition("\n")
        body = f"{first}\n\n{section}{rest.lstrip()}"
    return body


def skill_name(cfg: RunConfig) -> str:
    slug = re.sub(r"[^0-9a-z]+", "-", (cfg.run_name or "").lower()).strip("-")
    return f"rain-autoresearch-{cfg.station}" + (f"-{slug}" if slug else "")


def skill_markdown(cfg: RunConfig) -> str:
    return (f"---\nname: {skill_name(cfg)}\n"
            f"description: 依介面設定在測站 {cfg.station} 執行 LSTM 副目標消融實驗\n---\n\n{render(cfg)}\n")


def strip_frontmatter(text: str) -> str:
    """去掉 SKILL.md 開頭給 Hermes 讀的 --- name／description --- 檔頭。"""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def query_text(cfg: RunConfig) -> str:
    return f"依技能 {skill_name(cfg)} 在測站 {cfg.station} 執行副目標消融實驗；完成後依 program.md 第 5 節寫報告與學習紀錄。"


def hermes_args(cfg: RunConfig, root: str, query_file: str, api_key: str = "") -> list[str]:
    args = ["chat", "--provider", "openrouter", "-m", cfg.model, "-s", skill_name(cfg), "--yolo", "-Q",
            "--format", "stream-json", "--in", root, "--query-file", query_file]
    if api_key:
        args += ["--api-key", api_key]
    return args


def shell_preview(cfg: RunConfig, root: str) -> str:
    """給人看的指令；API Key 一律遮起來。"""
    name = skill_name(cfg)
    return "\n".join([
        "# 1. 介面把技能寫進 Hermes 的技能目錄",
        f"#    <HERMES_HOME>/skills/research/{name}/SKILL.md",
        "# 2. 帶著技能與模型啟動代理",
        "hermes chat --provider openrouter \\",
        f"    -m {cfg.model} \\",
        f"    -s {name} --yolo -Q --format stream-json \\",
        f"    --in {root} \\",
        "    --query-file prompt.txt --api-key ****",
    ])


def canonical(cfg: RunConfig) -> str:
    """決定「設定是否完全相同」的內容；模型、實驗名稱、平行數不影響結果，不算在內。"""
    return json.dumps({
        "station": cfg.station, "split": cfg.split, "metric": cfg.metric, "threshold": float(cfg.threshold),
        "sub_mode": cfg.sub_mode, "subgoals": sorted(cfg.subgoals) if cfg.sub_mode == "preset" else [],
        "sub_text": cfg.sub_text.strip() if cfg.sub_mode == "semantic" else "",
        "max_gen": int(cfg.max_gen), "patience": int(cfg.patience), "children": int(cfg.children),
        "template": cfg.template.replace("\r", "").strip(),
    }, ensure_ascii=False, sort_keys=True)


def fingerprint(cfg: RunConfig) -> str:
    return hashlib.sha256(canonical(cfg).encode("utf-8")).hexdigest()


def default_config(station: str, split: str = "82") -> RunConfig:
    """已完成測站當初跑的設定（program.md 預設）。"""
    return RunConfig(station=station, split=split)


KEY_PATTERN = re.compile(r"^sk-or-(v1-)?[A-Za-z0-9]{16,}$")


def field_errors(cfg: RunConfig, api_key: str, source_error: str = "") -> dict:
    """各欄位的檢查結果：{欄位: (等級, 訊息)}。等級 err 會擋住開始，warn 只提醒。"""
    errors = {}
    if api_key.strip() and not KEY_PATTERN.match(api_key.strip()):
        errors["key"] = ("err", "Key 格式應為 sk-or-v1-…")
    if not cfg.model.strip():
        errors["model"] = ("err", "請選擇代理模型")
    if source_error:
        errors["file"] = ("err", source_error)
    elif not cfg.station:
        errors["file"] = ("err", "請選擇測站或上傳 CSV")
    if cfg.sub_mode == "preset" and not cfg.subgoals:
        errors["sub"] = ("err", "至少勾一種副目標")
    elif cfg.sub_mode == "semantic" and not cfg.sub_text.strip():
        errors["sub"] = ("err", "請填寫副目標描述")
    try:
        if float(cfg.threshold) <= 0:
            errors["goal"] = ("err", "雨量門檻要大於 0")
    except (TypeError, ValueError):
        errors["goal"] = ("err", "雨量門檻要是數字")
    bad = [name for name, value, low in (("最多代數", cfg.max_gen, 2), ("早停", cfg.patience, 1),
                                         ("每代子代", cfg.children, 2), ("同時訓練", cfg.parallel, 1))
           if not _int_at_least(value, low)]
    if bad:
        errors["evo"] = ("err", "、".join(bad) + " 要是正整數（最多代數至少 2）")
    missing = [t for t in REQUIRED_TOKENS if f"[[{t}]]" not in cfg.template]
    if missing:
        errors["tpl"] = ("err", "模板缺少 " + "、".join(f"[[{t}]]" for t in missing))
    return errors


def _int_at_least(value, low) -> bool:
    try:
        return float(value).is_integer() and int(value) >= low
    except (TypeError, ValueError):
        return False


def blocking(errors: dict) -> bool:
    return any(level == "err" for level, _ in errors.values())
