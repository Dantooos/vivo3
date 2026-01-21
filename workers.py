from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

import db
import incogniton_api
from config import AppConfig


def _extract_webdriver_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in ["webdriverUrl", "webDriverUrl", "seleniumUrl", "url"]:
        value = payload.get(key)
        if value:
            return value
    return None


def create_driver_for_profile(
    cfg: AppConfig, profile_id: str, disable_images: bool
) -> webdriver.Remote:
    """
    Создаёт Remote WebDriver, подключённый к Incogniton.
    """
    options = webdriver.ChromeOptions()
    if disable_images:
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.stylesheets": 1,
            "profile.managed_default_content_settings.cookies": 1,
            "profile.managed_default_content_settings.javascript": 1,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_argument("--blink-settings=imagesEnabled=false")

    launch_payload = incogniton_api.launch_selenium(
        cfg.incogniton_api_base_url, profile_id
    )
    webdriver_url = _extract_webdriver_url(launch_payload)
    if not webdriver_url:
        webdriver_url = cfg.selenium_hub_url

    return webdriver.Remote(command_executor=webdriver_url, options=options)


class BrowserWorker(threading.Thread):
    def __init__(
        self,
        cfg: AppConfig,
        profile_config: Dict[str, Any],
        stop_event: threading.Event,
        log_callback: Callable[[str], None],
    ):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.profile_config = profile_config
        self.stop_event = stop_event
        self.log_callback = log_callback
        self.driver: Optional[webdriver.Remote] = None

    def _create_driver(self) -> None:
        profile_id = str(self.profile_config.get("profile_id", ""))
        disable_images = bool(self.profile_config.get("disable_images", False))
        self.driver = create_driver_for_profile(self.cfg, profile_id, disable_images)

    def _restart_driver(self, error: Exception) -> None:
        self.log_callback(f"[Profile {self.profile_config.get('profile_id')}] перезапуск driver: {error}")
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = None
        time.sleep(3)
        self._create_driver()

    def run(self) -> None:
        profile_id = str(self.profile_config.get("profile_id", ""))
        if not self.profile_config.get("enabled", True):
            self.log_callback(f"[Profile {profile_id}] выключен, пропуск.")
            return

        start_after = int(self.profile_config.get("start_after_sec", 0))
        min_delay = int(self.profile_config.get("min_delay", 60))
        max_delay = int(self.profile_config.get("max_delay", 120))
        countries = self.profile_config.get("countries") or []
        categories = self.profile_config.get("categories") or []

        if start_after > 0:
            self.log_callback(f"[Profile {profile_id}] старт через {start_after} сек.")
            self.stop_event.wait(start_after)

        try:
            self._create_driver()
            while not self.stop_event.is_set():
                next_item = db.get_next_queue_item(
                    profile_id, countries=countries, categories=categories
                )
                if not next_item:
                    time.sleep(60)
                    continue

                (url,) = next_item
                self.log_callback(f"[Profile {profile_id}] открываю URL {url}")
                try:
                    if not self.driver:
                        self._create_driver()
                    self.driver.execute_script("window.open(arguments[0], '_blank');", url)
                    db.mark_queue_opened(url)
                except WebDriverException as exc:
                    db.mark_queue_error(url, str(exc))
                    self._restart_driver(exc)
                except Exception as exc:
                    db.mark_queue_error(url, str(exc))
                    self.log_callback(f"[Profile {profile_id}] ошибка: {exc}")

                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)
        finally:
            if self.driver:
                self.driver.quit()


def start_workers(
    cfg: AppConfig,
    stop_event: threading.Event,
    log_callback: Callable[[str], None],
) -> List[BrowserWorker]:
    workers: List[BrowserWorker] = []
    for profile_config in cfg.browser_profiles:
        worker = BrowserWorker(cfg, profile_config, stop_event, log_callback)
        worker.start()
        workers.append(worker)
    return workers
