from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable, Dict, List

from selenium import webdriver

import db
from config import AppConfig


def create_driver_for_profile(cfg: AppConfig, profile_id: int) -> webdriver.Remote:
    """
    Создаёт Remote WebDriver, подключённый к Selenium-хабу Incogniton.
    """
    options = webdriver.ChromeOptions()
    # TODO: настроить привязку к профилю Incogniton
    # options.add_experimental_option("incogniton:profileId", profile_id)

    return webdriver.Remote(command_executor=cfg.selenium_hub_url, options=options)


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

    def run(self) -> None:
        profile_id = int(self.profile_config.get("profile_id", 0))
        if not self.profile_config.get("enabled", True):
            self.log_callback(f"[Profile {profile_id}] выключен, пропуск.")
            return

        driver = None
        try:
            driver = create_driver_for_profile(self.cfg, profile_id)
            min_delay = int(self.profile_config.get("min_delay", 60))
            max_delay = int(self.profile_config.get("max_delay", 120))

            while not self.stop_event.is_set():
                next_item = db.get_next_ad_for_profile(profile_id)
                if not next_item:
                    time.sleep(60)
                    continue

                ad_id, url = next_item
                self.log_callback(f"[Profile {profile_id}] открываю URL {url}")
                try:
                    driver.get(url)
                    db.mark_ad_opened(ad_id)
                except Exception as exc:
                    db.mark_ad_error(ad_id, str(exc))
                    self.log_callback(f"[Profile {profile_id}] ошибка: {exc}")

                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)
        finally:
            if driver:
                driver.quit()


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
