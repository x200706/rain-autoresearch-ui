"""OpenRouter 模型清單：即時抓公開 API（不需要 Key），抓不到才用內建清單。"""
import json
import time
import urllib.request

from . import config

FALLBACK = [config.DEFAULT_MODEL, "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro-0813",
            "anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro", "nousresearch/hermes-4-405b"]
_CACHE: dict = {"at": 0.0, "ids": None}


def fetch(timeout: float = 8.0, ttl: float = 3600.0) -> tuple[list[str], bool]:
    """回傳（模型 id 清單，是否來自 OpenRouter）。預設模型一定排第一個。"""
    if _CACHE["ids"] and time.time() - _CACHE["at"] < ttl:
        return _CACHE["ids"], True
    try:
        with urllib.request.urlopen(config.OPENROUTER_MODELS_URL, timeout=timeout) as resp:
            ids = sorted({m["id"] for m in json.load(resp).get("data", []) if m.get("id")})
    except Exception:  # noqa: BLE001 — 離線或被擋都退回內建清單
        return _with_default(FALLBACK), False
    if not ids:
        return _with_default(FALLBACK), False
    _CACHE.update(at=time.time(), ids=_with_default(ids))
    return _CACHE["ids"], True


def _with_default(ids: list[str]) -> list[str]:
    return [config.DEFAULT_MODEL] + [i for i in ids if i != config.DEFAULT_MODEL]
