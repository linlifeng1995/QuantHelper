"""路径与全局常量。复用 web_app 的目录布局以保证旧缓存兼容。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"
CACHE_DIR = OUTPUT_DIR / "cache"
DB_FILE = CACHE_DIR / "myquant.db"
WATCHLIST_LEGACY_FILE = CACHE_DIR / "watchlist.json"
WATCHLIST_BACKUP_FILE = CACHE_DIR / "watchlist.json.bak"

CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_dotenv(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env", override=True)

# Agent / Kimi config
AGENT_DEFAULT_PROVIDER = os.getenv("AGENT_DEFAULT_PROVIDER", "kimi").strip().lower()

KIMI_API_KEY = os.getenv("KIMI_API_KEY", "").strip()
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1").strip()
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-8k").strip()
KIMI_TIMEOUT_SEC = int(os.getenv("KIMI_TIMEOUT_SEC", "30"))
KIMI_MAX_OUTPUT_TOKENS = int(os.getenv("KIMI_MAX_OUTPUT_TOKENS", "4096"))
KIMI_TEMPERATURE = float(os.getenv("KIMI_TEMPERATURE", "0.3"))

# Agent / DeepSeek config (OpenAI-compatible endpoint)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
DEEPSEEK_TIMEOUT_SEC = int(os.getenv("DEEPSEEK_TIMEOUT_SEC", "30"))
DEEPSEEK_MAX_OUTPUT_TOKENS = int(os.getenv("DEEPSEEK_MAX_OUTPUT_TOKENS", "4096"))
DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3"))

AGENT_ACCESS_TOKEN = os.getenv("AGENT_ACCESS_TOKEN", "").strip()
AGENT_RATE_LIMIT_PER_MINUTE = int(os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "30"))
