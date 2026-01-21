from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

from lxml import html

import db
from config import AppConfig, load_config
from ua_proxy import ProxyManager, UserAgentManager

BASE_DIR = Path(__file__).resolve().parent


def _extract_idphone(url: str) -> Optional[str]:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    value = qs.get("idphone", [None])[0]
    return value


def _parse_list_page(content: str, base_url: str) -> List[Tuple[str, Optional[str]]]:
    tree = html.fromstring(content)
    ad_links = tree.xpath("//h2[@class='nadpis']/a")
    idphone_links = tree.xpath(
        "//td[@class='listadvlevo1']/a[contains(@href, 'idphone=')]"
    )

    ad_urls = [urljoin(base_url, link.get("href")) for link in ad_links]
    idphones = [_extract_idphone(link.get("href", "")) for link in idphone_links]

    pairs: List[Tuple[str, Optional[str]]] = []
    for index, ad_url in enumerate(ad_urls):
        idphone = idphones[index] if index < len(idphones) else None
        pairs.append((ad_url, idphone))
    return pairs


def get_seller_ads_count(
    country: str,
    idphone: str,
    proxy_manager: ProxyManager,
    ua_manager: UserAgentManager,
    timeout: int,
) -> Optional[int]:
    if not idphone:
        return None
    base = "https://www.bazos.cz" if country == "cz" else "https://www.bazos.sk"
    url = f"{base}/hodnoceni.php?idphone={idphone}"
    headers = {"User-Agent": ua_manager.next()}
    try:
        response = proxy_manager.request_with_retry(
            "GET", url, headers=headers, timeout=timeout
        )
    except Exception:
        return None

    # TODO: уточнить выражение под реальные форматы страницы
    match = re.search(r"Počet inzerátů:\s*(\d+)", response.text)
    if not match:
        match = re.search(r"Inzerátů:\s*(\d+)", response.text)
    if match:
        return int(match.group(1))
    return None


def parse_ad_details(
    ad_url: str,
    country: str,
    category: str,
    idphone: Optional[str],
    proxy_manager: ProxyManager,
    ua_manager: UserAgentManager,
    timeout: int,
) -> dict:
    headers = {"User-Agent": ua_manager.next()}
    response = proxy_manager.request_with_retry(
        "GET", ad_url, headers=headers, timeout=timeout
    )
    tree = html.fromstring(response.text)

    title_list = tree.xpath("//h1[@class='nadpisdetail']/text()")
    title = title_list[0].strip() if title_list else None

    price_text = "".join(tree.xpath("//td[@class='listaprava']//b/text()"))
    price_digits = re.sub(r"\D", "", price_text)
    price = int(price_digits) if price_digits else None

    views_match = re.search(
        r">Vidělo:</td><td[^<>]*?>(.*?)</td>", response.text
    )
    views = None
    if views_match:
        views_digits = re.sub(r"\D", "", views_match.group(1))
        views = int(views_digits) if views_digits else None

    created_match = re.search(
        r"<span class=\"velikost10\">(.*?)</span>", response.text
    )
    created_at = created_match.group(1).strip() if created_match else None

    seller_name_list = tree.xpath("//span[@class='jmeno']/b/text()")
    seller_name = seller_name_list[0].strip() if seller_name_list else None

    has_field = 1 if tree.xpath("//input[contains(@id, 'teloverit')]") else 0

    seller_ads = get_seller_ads_count(
        country, idphone or "", proxy_manager, ua_manager, timeout
    )

    return {
        "url": ad_url,
        "country": country,
        "category": category,
        "title": title,
        "price": price,
        "views": views,
        "seller_ads": seller_ads,
        "has_field": has_field,
        "created_at": created_at,
        "seller_name": seller_name,
    }


def ad_passes_filters(data: dict, cfg: AppConfig) -> tuple[bool, str]:
    if cfg.require_field and data.get("has_field") == 0:
        return False, "нет поля teloverit"
    seller_ads = data.get("seller_ads")
    if seller_ads is None or seller_ads > cfg.max_seller_ads:
        return (
            False,
            f"seller_ads={seller_ads} > max_seller_ads={cfg.max_seller_ads}",
        )
    views = data.get("views")
    if views is None or views > cfg.max_views:
        if views is None:
            return False, "views не распознаны"
        return False, f"views={views} > max_views={cfg.max_views}"
    price = data.get("price")
    if price is None:
        return False, "price не распознана"
    if not (cfg.min_price <= price <= cfg.max_price):
        return (
            False,
            f"price={price} вне диапазона {cfg.min_price}-{cfg.max_price}",
        )
    return True, "ok"


def parser_loop(stop_event: threading.Event, log_callback: Callable[[str], None]) -> None:
    while not stop_event.is_set():
        cfg = load_config()
        categories_dir = Path(cfg.categories_dir)
        if not categories_dir.is_absolute():
            categories_dir = BASE_DIR / categories_dir
        if not categories_dir.exists():
            log_callback(f"Папка категорий не найдена: {categories_dir}")
            stop_event.wait(cfg.parser_interval_seconds)
            continue

        ua_manager = UserAgentManager(cfg.user_agents)
        proxy_manager = ProxyManager(cfg.proxies, cfg.proxy_retries)

        txt_files = sorted(categories_dir.glob("*.txt"))
        if not txt_files:
            log_callback("Файлы категорий не найдены.")

        for txt_file in txt_files:
            category = txt_file.stem
            urls = [line.strip() for line in txt_file.read_text(encoding="utf-8").splitlines()]
            urls = [url for url in urls if url]
            for url in urls:
                country = "cz" if ".cz" in url else "sk"
                headers = {"User-Agent": ua_manager.next()}
                try:
                    response = proxy_manager.request_with_retry(
                        "GET", url, headers=headers, timeout=cfg.request_timeout
                    )
                except Exception as exc:
                    log_callback(f"Ошибка запроса списка: {url} ({exc})")
                    continue

                pairs = _parse_list_page(response.text, url)
                log_callback(
                    f"Категория {category}: найдено {len(pairs)} объявлений."
                )

                for ad_url, idphone in pairs:
                    try:
                        data = parse_ad_details(
                            ad_url,
                            country,
                            category,
                            idphone,
                            proxy_manager,
                            ua_manager,
                            cfg.request_timeout,
                        )
                    except Exception as exc:
                        log_callback(f"Ошибка парсинга {ad_url}: {exc}")
                        continue

                    ok, reason = ad_passes_filters(data, cfg)
                    if ok:
                        inserted = db.insert_ad_if_new(data)
                        if inserted:
                            log_callback(
                                "✅ Добавлено: "
                                f"price={data.get('price')} "
                                f"views={data.get('views')} "
                                f"seller_ads={data.get('seller_ads')} | {ad_url}"
                            )
                        else:
                            log_callback(f"↩️ Уже в базе: {ad_url}")
                    else:
                        log_callback(f"❌ Не прошло: {reason} | {ad_url}")

        log_callback("Цикл парсера завершён, ожидание...")
        stop_event.wait(cfg.parser_interval_seconds)
