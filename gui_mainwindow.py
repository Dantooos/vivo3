from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List

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
from config import AppConfig, load_config, save_config
from parser import parser_loop
from workers import start_workers

BASE_DIR = Path(__file__).resolve().parent


class MainWindow(QMainWindow):
    log_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bazos Parser")
        self.resize(1000, 700)

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
        self._init_log_tab()
        self._init_db_tab()
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

        layout.addWidget(QLabel("Повторов при ошибке прокси:"))
        self.proxy_retries_spin = QSpinBox()
        self.proxy_retries_spin.setMaximum(10)
        layout.addWidget(self.proxy_retries_spin)

        layout.addWidget(QLabel("HTTP таймаут (сек):"))
        self.request_timeout_spin = QSpinBox()
        self.request_timeout_spin.setMaximum(120)
        layout.addWidget(self.request_timeout_spin)

        layout.addStretch()
        self.tabs.addTab(self.ua_proxy_tab, "User-Agent / Proxy")

    def _init_profiles_tab(self) -> None:
        self.profiles_tab = QWidget()
        layout = QVBoxLayout(self.profiles_tab)

        self.profiles_table = QTableWidget(0, 4)
        self.profiles_table.setHorizontalHeaderLabels(
            ["Включён", "ID профиля", "min_delay", "max_delay"]
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

        self.tabs.addTab(self.profiles_tab, "Профили браузера")

    def _init_general_tab(self) -> None:
        self.general_tab = QWidget()
        layout = QVBoxLayout(self.general_tab)

        layout.addWidget(QLabel("Selenium hub URL"))
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

    def _init_log_tab(self) -> None:
        self.log_tab = QWidget()
        layout = QVBoxLayout(self.log_tab)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        self.tabs.addTab(self.log_tab, "Лог")

    def _init_db_tab(self) -> None:
        self.db_tab = QWidget()
        layout = QVBoxLayout(self.db_tab)

        stats_layout = QHBoxLayout()
        self.db_total_label = QLabel("Total: 0")
        self.db_new_label = QLabel("New: 0")
        self.db_in_progress_label = QLabel("InProgress: 0")
        self.db_opened_label = QLabel("Opened: 0")
        self.db_error_label = QLabel("Error: 0")
        stats_layout.addWidget(self.db_total_label)
        stats_layout.addWidget(self.db_new_label)
        stats_layout.addWidget(self.db_in_progress_label)
        stats_layout.addWidget(self.db_opened_label)
        stats_layout.addWidget(self.db_error_label)
        layout.addLayout(stats_layout)

        self.db_table = QTableWidget(0, 9)
        self.db_table.setHorizontalHeaderLabels(
            [
                "id",
                "country",
                "category",
                "price",
                "views",
                "seller_ads",
                "status",
                "first_seen",
                "url",
            ]
        )
        self.db_table.horizontalHeader().setStretchLastSection(True)
        self.db_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.db_table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.db_table)

        controls_layout = QHBoxLayout()
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self._refresh_db_view)
        copy_btn = QPushButton("Скопировать URL")
        copy_btn.clicked.connect(self._copy_selected_url)
        open_btn = QPushButton("Открыть URL")
        open_btn.clicked.connect(self._open_selected_url)
        controls_layout.addWidget(refresh_btn)
        controls_layout.addWidget(copy_btn)
        controls_layout.addWidget(open_btn)
        layout.addLayout(controls_layout)

        self.tabs.addTab(self.db_tab, "База")

        self.db_timer = QTimer(self)
        self.db_timer.setInterval(3000)
        self.db_timer.timeout.connect(self._refresh_db_view)
        self.db_timer.start()

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

    def _refresh_db_view(self) -> None:
        counts = db.get_counts_by_status()
        self.db_total_label.setText(f"Total: {counts.get('total', 0)}")
        self.db_new_label.setText(f"New: {counts.get('new', 0)}")
        self.db_in_progress_label.setText(
            f"InProgress: {counts.get('in_progress', 0)}"
        )
        self.db_opened_label.setText(f"Opened: {counts.get('opened', 0)}")
        self.db_error_label.setText(f"Error: {counts.get('error', 0)}")

        rows = db.get_recent_ads()
        self.db_table.setRowCount(0)
        for row_data in rows:
            ad_id, url, price, views, seller_ads, country, category, status, first_seen = (
                row_data
            )
            row = self.db_table.rowCount()
            self.db_table.insertRow(row)
            self.db_table.setItem(row, 0, QTableWidgetItem(str(ad_id)))
            self.db_table.setItem(row, 1, QTableWidgetItem(country or ""))
            self.db_table.setItem(row, 2, QTableWidgetItem(category or ""))
            self.db_table.setItem(row, 3, QTableWidgetItem(str(price or "")))
            self.db_table.setItem(row, 4, QTableWidgetItem(str(views or "")))
            self.db_table.setItem(row, 5, QTableWidgetItem(str(seller_ads or "")))
            self.db_table.setItem(row, 6, QTableWidgetItem(status or ""))
            self.db_table.setItem(row, 7, QTableWidgetItem(first_seen or ""))
            self.db_table.setItem(row, 8, QTableWidgetItem(url or ""))

    def _get_selected_url(self) -> str | None:
        row = self.db_table.currentRow()
        if row < 0:
            return None
        item = self.db_table.item(row, 8)
        if not item:
            return None
        return item.text().strip() or None

    def _copy_selected_url(self) -> None:
        url = self._get_selected_url()
        if not url:
            return
        QApplication.clipboard().setText(url)

    def _open_selected_url(self) -> None:
        url = self._get_selected_url()
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

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

        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(enabled_item.flags() | Qt.ItemIsUserCheckable)
        enabled_item.setCheckState(
            Qt.Checked if (profile or {}).get("enabled", True) else Qt.Unchecked
        )
        self.profiles_table.setItem(row, 0, enabled_item)

        profile_id_item = QTableWidgetItem(str((profile or {}).get("profile_id", 1)))
        self.profiles_table.setItem(row, 1, profile_id_item)

        min_delay_item = QTableWidgetItem(str((profile or {}).get("min_delay", 60)))
        self.profiles_table.setItem(row, 2, min_delay_item)

        max_delay_item = QTableWidgetItem(str((profile or {}).get("max_delay", 120)))
        self.profiles_table.setItem(row, 3, max_delay_item)

    def _remove_selected_profile(self) -> None:
        row = self.profiles_table.currentRow()
        if row >= 0:
            self.profiles_table.removeRow(row)

    def _collect_profiles(self) -> List[Dict[str, Any]]:
        profiles: List[Dict[str, Any]] = []
        for row in range(self.profiles_table.rowCount()):
            enabled = self.profiles_table.item(row, 0).checkState() == Qt.Checked
            profile_id = int(self.profiles_table.item(row, 1).text())
            min_delay = int(self.profiles_table.item(row, 2).text())
            max_delay = int(self.profiles_table.item(row, 3).text())
            profiles.append(
                {
                    "enabled": enabled,
                    "profile_id": profile_id,
                    "min_delay": min_delay,
                    "max_delay": max_delay,
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
