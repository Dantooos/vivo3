from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent


@dataclass
class AppConfig:
    categories_dir: str = "categories"
    parser_interval_seconds: int = 300

    # Фильтры
    max_seller_ads: int = 1
    max_views: int = 50
    min_price: int = 100
    max_price: int = 100000
    require_field: bool = True

    # HTTP
    request_timeout: int = 15

    # User-agent'ы и прокси
    user_agents: List[str] = field(default_factory=list)
    proxies: List[str] = field(default_factory=list)
    proxy_retries: int = 3

    # Selenium / Incogniton
    selenium_hub_url: str = "http://127.0.0.1:4444/wd/hub"

    # Профили браузера
    browser_profiles: List[Dict[str, Any]] = field(default_factory=list)


def _resolve_path(path: str) -> Path:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = BASE_DIR / cfg_path
    return cfg_path


def load_config(path: str = "config.json") -> AppConfig:
    cfg_path = _resolve_path(path)
    if not cfg_path.exists():
        return AppConfig()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    return AppConfig(**data)


def save_config(cfg: AppConfig, path: str = "config.json") -> None:
    cfg_path = _resolve_path(path)
    cfg_path.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
