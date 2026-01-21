from __future__ import annotations

import csv
import threading
from pathlib import Path
from typing import Any, Dict, List

import requests
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QListWidget,
)

import db
import incogniton_api
from config import AppConfig, load_config, save_config
from parser import parser_loop
from workers import start_workers

BASE_DIR = Path(__file__).resolve().parent


class MainWindow(QMainWindow):
    log_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bazos Parser")
        self.resize(1100, 800)

        db.init_db()

        self.cfg = load_config()
        self.stop_event: threading.Event | None = None
        self.parser_thread: threading.Thread | None = None
        self.workers: List[threading.Thread] = []

        self.tabs = QTabWidget()

        central = QWidget()
        self.main_layout = QVBoxLayout(central)
        self.main_layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self._init_categories_tab()
        self._init_filters_tab()
        self._init_ua_proxy_tab()
        self._init_profiles_tab()
        self._init_general_tab()
        self._init_queue_tab()
        self._init_log_tab()
        self._init_controls()

        self.log_signal.connect(self._append_log)
        self._load_config_into_ui()

    def _init_categories_tab(self) -> None:
        self.categories_tab = QWidget()
        layout = QVBoxLayout(self.categories_tab)

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Папка категорий:"))
        self.categories_dir_edit = QLineEdit()
        path_layout.addWidget(self.categories_dir_edit)
        browse_btn = QPushButton("Обзор")
        browse_btn.clicked.connect(self._browse_categories_dir)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        self.categories_list = QListWidget()
        layout.addWidget(self.categories_list)

        refresh_btn = QPushButton("Обновить список")
        refresh_btn.clicked.connect(self._refresh_categories_list)
        layout.addWidget(refresh_btn)

        self.tabs.addTab(self.categories_tab, "Категории")

    def _init_filters_tab(self) -> None:
        self.filters_tab = QWidget()
        layout = QVBoxLayout(self.filters_tab)

        self.max_seller_ads_spin = QSpinBox()
        self.max_seller_ads_spin.setMaximum(10000)
        layout.addWidget(QLabel("Макс. объявлений продавца"))
        layout.addWidget(self.max_seller_ads_spin)

        self.max_views_spin = QSpinBox()
        self.max_views_spin.setMaximum(1000000)
        layout.addWidget(QLabel("Макс. просмотров"))
        layout.addWidget(self.max_views_spin)

        self.min_price_spin = QSpinBox()
        self.min_price_spin.setMaximum(10**9)
        layout.addWidget(QLabel("Мин. цена"))
        layout.addWidget(self.min_price_spin)

        self.max_price_spin = QSpinBox()
        self.max_price_spin.setMaximum(10**9)
        layout.addWidget(QLabel("Макс. цена"))
        layout.addWidget(self.max_price_spin)

        self.require_field_check = QCheckBox("Требовать спец. поле (teloverit)")
        layout.addWidget(self.require_field_check)

        layout.addStretch()
        self.tabs.addTab(self.filters_tab, "Фильтры")

    def _init_ua_proxy_tab(self) -> None:
        self.ua_proxy_tab = QWidget()
        layout = QVBoxLayout(self.ua_proxy_tab)

        layout.addWidget(QLabel("User-Agent'ы (по одному на строку):"))
        self.ua_text = QPlainTextEdit()
        layout.addWidget(self.ua_text)

        layout.addWidget(QLabel("Прокси (по одному на строку):"))
        self.proxy_text = QPlainTextEdit()
        layout.addWidget(self.proxy_text)

        controls_layout = QHBoxLayout()
        self.proxy_retries_spin = QSpinBox()
        self.proxy_retries_spin.setMaximum(10)
        self.request_timeout_spin = QSpinBox()
        self.request_timeout_spin.setMaximum(120)
        controls_layout.addWidget(QLabel("Повторов при ошибке прокси:"))
        controls_layout.addWidget(self.proxy_retries_spin)
        controls_layout.addWidget(QLabel("HTTP таймаут (сек):"))
        controls_layout.addWidget(self.request_timeout_spin)
        layout.addLayout(controls_layout)

        check_btn = QPushButton("Проверить прокси")
        check_btn.clicked.connect(self._check_proxies)
        layout.addWidget(check_btn)

        layout.addStretch()
        self.tabs.addTab(self.ua_proxy_tab, "User-Agent / Proxy")

    def _init_profiles_tab(self) -> None:
        self.profiles_tab = QWidget()
        layout = QVBoxLayout(self.profiles_tab)

        layout.addWidget(QLabel("Профили в работе"))
        self.profiles_table = QTableWidget(0, 8)
        self.profiles_table.setHorizontalHeaderLabels(
            [
                "Включён",
                "ID профиля",
                "start_after_sec",
                "min_delay",
                "max_delay",
                "disable_images",
                "countries",
                "categories",
            ]
        )
        self.profiles_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.profiles_table)

        button_layout = QHBoxLayout()
        add_btn = QPushButton("Добавить профиль")
        add_btn.clicked.connect(self._add_profile_row)
        remove_btn = QPushButton("Удалить профиль")
        remove_btn.clicked.connect(self._remove_selected_profile)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(remove_btn)
        layout.addLayout(button_layout)

        layout.addWidget(QLabel("Профили из Incogniton"))
        self.incogniton_table = QTableWidget(0, 4)
        self.incogniton_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Group", "Status"]
        )
        self.incogniton_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.incogniton_table)

        incogniton_buttons = QHBoxLayout()
        refresh_btn = QPushButton("Обновить из Incogniton")
        refresh_btn.clicked.connect(self._refresh_incogniton_profiles)
        add_selected_btn = QPushButton("Добавить выбранный в работу")
        add_selected_btn.clicked.connect(self._add_selected_incogniton_profile)
        add_launched_btn = QPushButton("Добавить все запущенные")
        add_launched_btn.clicked.connect(self._add_launched_profiles)
        incogniton_buttons.addWidget(refresh_btn)
        incogniton_buttons.addWidget(add_selected_btn)
        incogniton_buttons.addWidget(add_launched_btn)
        layout.addLayout(incogniton_buttons)

        self.tabs.addTab(self.profiles_tab, "Профили браузера")

    def _init_general_tab(self) -> None:
        self.general_tab = QWidget()
        layout = QVBoxLayout(self.general_tab)

        layout.addWidget(QLabel("Incogniton API Base URL"))
        self.incogniton_api_edit = QLineEdit()
        layout.addWidget(self.incogniton_api_edit)

        layout.addWidget(QLabel("Selenium hub URL (fallback)"))
        self.selenium_url_edit = QLineEdit()
        layout.addWidget(self.selenium_url_edit)

        layout.addWidget(QLabel("Интервал парсера (сек)"))
        self.parser_interval_spin = QSpinBox()
        self.parser_interval_spin.setMaximum(10**6)
        layout.addWidget(self.parser_interval_spin)

        save_btn = QPushButton("Сохранить настройки")
        save_btn.clicked.connect(self._save_config)
        layout.addWidget(save_btn)

        layout.addStretch()
        self.tabs.addTab(self.general_tab, "Общие")

    def _init_queue_tab(self) -> None:
        self.queue_tab = QWidget()
        layout = QVBoxLayout(self.queue_tab)

        stats_layout = QHBoxLayout()
        self.seen_total_label = QLabel("Seen: 0")
        self.queue_total_label = QLabel("Queue total: 0")
        self.queue_new_label = QLabel("New: 0")
        self.queue_sent_label = QLabel("Sent: 0")
        self.queue_opened_label = QLabel("Opened: 0")
        self.queue_error_label = QLabel("Error: 0")
        stats_layout.addWidget(self.seen_total_label)
        stats_layout.addWidget(self.queue_total_label)
        stats_layout.addWidget(self.queue_new_label)
        stats_layout.addWidget(self.queue_sent_label)
        stats_layout.addWidget(self.queue_opened_label)
        stats_layout.addWidget(self.queue_error_label)
        layout.addLayout(stats_layout)

        self.queue_table = QTableWidget(0, 6)
        self.queue_table.setHorizontalHeaderLabels(
            ["url", "status", "added_ts", "profile_id", "sent_ts", "opened_ts"]
        )
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        self.queue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.queue_table.setSelectionMode(QTableWidget.ExtendedSelection)
        layout.addWidget(self.queue_table)

        controls_layout = QHBoxLayout()
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self._refresh_queue_view)
        clear_btn = QPushButton("Очистить очередь")
        clear_btn.clicked.connect(self._clear_queue)
        export_btn = QPushButton("Экспорт CSV")
        export_btn.clicked.connect(self._export_queue_csv)
        copy_btn = QPushButton("Скопировать выделенные url")
        copy_btn.clicked.connect(self._copy_selected_queue_urls)
        controls_layout.addWidget(refresh_btn)
        controls_layout.addWidget(clear_btn)
        controls_layout.addWidget(export_btn)
        controls_layout.addWidget(copy_btn)
        layout.addLayout(controls_layout)

        self.tabs.addTab(self.queue_tab, "База/Очередь")

        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(3000)
        self.queue_timer.timeout.connect(self._refresh_queue_view)
        self.queue_timer.start()

    def _init_log_tab(self) -> None:
        self.log_tab = QWidget()
        layout = QVBoxLayout(self.log_tab)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        self.tabs.addTab(self.log_tab, "Лог")

    def _init_controls(self) -> None:
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        start_btn = QPushButton("Старт")
        start_btn.clicked.connect(self._start_processing)
        stop_btn = QPushButton("Стоп")
        stop_btn.clicked.connect(self._stop_processing)
        exit_btn = QPushButton("Выход")
        exit_btn.clicked.connect(self.close)
        control_layout.addWidget(start_btn)
        control_layout.addWidget(stop_btn)
        control_layout.addWidget(exit_btn)

        self.main_layout.addWidget(control_widget)

    def _browse_categories_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выбор папки категорий")
        if path:
            self.categories_dir_edit.setText(path)
            self._refresh_categories_list()

    def _refresh_categories_list(self) -> None:
        self.categories_list.clear()
        path = Path(self.categories_dir_edit.text())
        if not path.is_absolute():
            path = BASE_DIR / path
        if not path.exists():
            return
        for txt_file in sorted(path.glob("*.txt")):
            self.categories_list.addItem(txt_file.name)

    def _append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def _check_proxies(self) -> None:
        proxies = [
            line.strip()
            for line in self.proxy_text.toPlainText().splitlines()
            if line.strip()
        ]
        if not proxies:
            self._append_log("Прокси не заданы.")
            return
        timeout = self.request_timeout_spin.value()
        for proxy in proxies:
            try:
                response = requests.get(
                    "https://httpbin.org/ip",
                    proxies={"http": proxy, "https": proxy},
                    timeout=timeout,
                )
                self._append_log(
                    f"Прокси {proxy}: {response.status_code} {response.text.strip()}"
                )
            except Exception as exc:
                self._append_log(f"Прокси {proxy}: ошибка {exc}")

    def _refresh_incogniton_profiles(self) -> None:
        self.incogniton_table.setRowCount(0)
        api_base = self.incogniton_api_edit.text().strip()
        if not api_base:
            return
        try:
            profiles = incogniton_api.list_profiles(api_base)
        except Exception as exc:
            self._append_log(f"Incogniton API ошибка: {exc}")
            return

        for profile in profiles:
            profile_id = str(profile.get("id") or profile.get("profileId") or "")
            name = profile.get("name", "")
            group = profile.get("group", "")
            status = profile.get("status", "")
            row = self.incogniton_table.rowCount()
            self.incogniton_table.insertRow(row)
            self.incogniton_table.setItem(row, 0, QTableWidgetItem(profile_id))
            self.incogniton_table.setItem(row, 1, QTableWidgetItem(str(name)))
            self.incogniton_table.setItem(row, 2, QTableWidgetItem(str(group)))
            self.incogniton_table.setItem(row, 3, QTableWidgetItem(str(status)))

    def _add_selected_incogniton_profile(self) -> None:
        row = self.incogniton_table.currentRow()
        if row < 0:
            return
        profile_id_item = self.incogniton_table.item(row, 0)
        if not profile_id_item:
            return
        self._add_profile_row({"profile_id": profile_id_item.text(), "enabled": True})

    def _add_launched_profiles(self) -> None:
        for row in range(self.incogniton_table.rowCount()):
            status_item = self.incogniton_table.item(row, 3)
            profile_id_item = self.incogniton_table.item(row, 0)
            if not status_item or not profile_id_item:
                continue
            status = status_item.text().lower()
            if status in {"launched", "ready"}:
                self._add_profile_row({"profile_id": profile_id_item.text(), "enabled": True})

    def _refresh_queue_view(self) -> None:
        seen_total = db.get_seen_count()
        queue_counts = db.get_queue_counts()
        self.seen_total_label.setText(f"Seen: {seen_total}")
        self.queue_total_label.setText(f"Queue total: {queue_counts.get('total', 0)}")
        self.queue_new_label.setText(f"New: {queue_counts.get('new', 0)}")
        self.queue_sent_label.setText(f"Sent: {queue_counts.get('sent', 0)}")
        self.queue_opened_label.setText(f"Opened: {queue_counts.get('opened', 0)}")
        self.queue_error_label.setText(f"Error: {queue_counts.get('error', 0)}")

        rows = db.get_recent_queue()
        self.queue_table.setRowCount(0)
        for row_data in rows:
            url, status, added_ts, profile_id, sent_ts, opened_ts = row_data
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            self.queue_table.setItem(row, 0, QTableWidgetItem(url or ""))
            self.queue_table.setItem(row, 1, QTableWidgetItem(status or ""))
            self.queue_table.setItem(row, 2, QTableWidgetItem(added_ts or ""))
            self.queue_table.setItem(row, 3, QTableWidgetItem(profile_id or ""))
            self.queue_table.setItem(row, 4, QTableWidgetItem(sent_ts or ""))
            self.queue_table.setItem(row, 5, QTableWidgetItem(opened_ts or ""))

    def _clear_queue(self) -> None:
        db.clear_queue()
        self._refresh_queue_view()

    def _export_queue_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт CSV", "queue.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        rows = db.get_recent_queue()
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["url", "status", "added_ts", "profile_id", "sent_ts", "opened_ts"])
            writer.writerows(rows)
        self._append_log(f"CSV сохранён: {path}")

    def _copy_selected_queue_urls(self) -> None:
        urls: List[str] = []
        for item in self.queue_table.selectedItems():
            if item.column() == 0:
                urls.append(item.text())
        if urls:
            QApplication.clipboard().setText("\n".join(urls))

    def _load_config_into_ui(self) -> None:
        cfg = self.cfg
        self.categories_dir_edit.setText(cfg.categories_dir)
        self.max_seller_ads_spin.setValue(cfg.max_seller_ads)
        self.max_views_spin.setValue(cfg.max_views)
        self.min_price_spin.setValue(cfg.min_price)
        self.max_price_spin.setValue(cfg.max_price)
        self.require_field_check.setChecked(cfg.require_field)
        self.ua_text.setPlainText("\n".join(cfg.user_agents))
        self.proxy_text.setPlainText("\n".join(cfg.proxies))
        self.proxy_retries_spin.setValue(cfg.proxy_retries)
        self.request_timeout_spin.setValue(cfg.request_timeout)
        self.incogniton_api_edit.setText(cfg.incogniton_api_base_url)
        self.selenium_url_edit.setText(cfg.selenium_hub_url)
        self.parser_interval_spin.setValue(cfg.parser_interval_seconds)
        self._load_profiles(cfg.browser_profiles)
        self._refresh_categories_list()

    def _load_profiles(self, profiles: List[Dict[str, Any]]) -> None:
        self.profiles_table.setRowCount(0)
        for profile in profiles:
            self._add_profile_row(profile)

    def _add_profile_row(self, profile: Dict[str, Any] | None = None) -> None:
        row = self.profiles_table.rowCount()
        self.profiles_table.insertRow(row)
        profile = profile or {}

        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(enabled_item.flags() | Qt.ItemIsUserCheckable)
        enabled_item.setCheckState(
            Qt.Checked if profile.get("enabled", True) else Qt.Unchecked
        )
        self.profiles_table.setItem(row, 0, enabled_item)

        profile_id_item = QTableWidgetItem(str(profile.get("profile_id", "")))
        self.profiles_table.setItem(row, 1, profile_id_item)

        start_after_item = QTableWidgetItem(str(profile.get("start_after_sec", 0)))
        self.profiles_table.setItem(row, 2, start_after_item)

        min_delay_item = QTableWidgetItem(str(profile.get("min_delay", 60)))
        self.profiles_table.setItem(row, 3, min_delay_item)

        max_delay_item = QTableWidgetItem(str(profile.get("max_delay", 120)))
        self.profiles_table.setItem(row, 4, max_delay_item)

        disable_images_item = QTableWidgetItem()
        disable_images_item.setFlags(disable_images_item.flags() | Qt.ItemIsUserCheckable)
        disable_images_item.setCheckState(
            Qt.Checked if profile.get("disable_images", False) else Qt.Unchecked
        )
        self.profiles_table.setItem(row, 5, disable_images_item)

        countries_item = QTableWidgetItem(",".join(profile.get("countries", [])))
        self.profiles_table.setItem(row, 6, countries_item)

        categories_item = QTableWidgetItem(",".join(profile.get("categories", [])))
        self.profiles_table.setItem(row, 7, categories_item)

    def _remove_selected_profile(self) -> None:
        row = self.profiles_table.currentRow()
        if row >= 0:
            self.profiles_table.removeRow(row)

    def _collect_profiles(self) -> List[Dict[str, Any]]:
        profiles: List[Dict[str, Any]] = []
        for row in range(self.profiles_table.rowCount()):
            enabled = self.profiles_table.item(row, 0).checkState() == Qt.Checked
            profile_id = self.profiles_table.item(row, 1).text().strip()
            start_after = int(self.profiles_table.item(row, 2).text())
            min_delay = int(self.profiles_table.item(row, 3).text())
            max_delay = int(self.profiles_table.item(row, 4).text())
            disable_images = (
                self.profiles_table.item(row, 5).checkState() == Qt.Checked
            )
            countries = [
                value.strip()
                for value in self.profiles_table.item(row, 6).text().split(",")
                if value.strip()
            ]
            categories = [
                value.strip()
                for value in self.profiles_table.item(row, 7).text().split(",")
                if value.strip()
            ]
            profiles.append(
                {
                    "enabled": enabled,
                    "profile_id": profile_id,
                    "start_after_sec": start_after,
                    "min_delay": min_delay,
                    "max_delay": max_delay,
                    "disable_images": disable_images,
                    "countries": countries,
                    "categories": categories,
                }
            )
        return profiles

    def _collect_config_from_ui(self) -> AppConfig:
        return AppConfig(
            categories_dir=self.categories_dir_edit.text().strip() or "categories",
            parser_interval_seconds=self.parser_interval_spin.value(),
            max_seller_ads=self.max_seller_ads_spin.value(),
            max_views=self.max_views_spin.value(),
            min_price=self.min_price_spin.value(),
            max_price=self.max_price_spin.value(),
            require_field=self.require_field_check.isChecked(),
            request_timeout=self.request_timeout_spin.value(),
            user_agents=[
                line.strip()
                for line in self.ua_text.toPlainText().splitlines()
                if line.strip()
            ],
            proxies=[
                line.strip()
                for line in self.proxy_text.toPlainText().splitlines()
                if line.strip()
            ],
            proxy_retries=self.proxy_retries_spin.value(),
            incogniton_api_base_url=self.incogniton_api_edit.text().strip(),
            selenium_hub_url=self.selenium_url_edit.text().strip(),
            browser_profiles=self._collect_profiles(),
        )

    def _save_config(self) -> None:
        self.cfg = self._collect_config_from_ui()
        save_config(self.cfg)
        self._append_log("Конфигурация сохранена.")

    def _start_processing(self) -> None:
        if self.stop_event and not self.stop_event.is_set():
            self._append_log("Процессы уже запущены.")
            return

        self._save_config()
        self.stop_event = threading.Event()

        log_callback = lambda msg: self.log_signal.emit(msg)

        self.parser_thread = threading.Thread(
            target=parser_loop,
            args=(self.stop_event, log_callback),
            daemon=True,
        )
        self.parser_thread.start()

        self.workers = start_workers(self.cfg, self.stop_event, log_callback)
        self._append_log("Парсер и воркеры запущены.")

    def _stop_processing(self) -> None:
        if not self.stop_event:
            return
        self.stop_event.set()
        if self.parser_thread:
            self.parser_thread.join(timeout=1)
        for worker in self.workers:
            worker.join(timeout=1)
        self._append_log("Остановка процессов завершена.")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_processing()
        event.accept()
