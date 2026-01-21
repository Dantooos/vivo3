from __future__ import annotations

import itertools
from typing import Dict, List, Optional

import requests
from requests import RequestException


class UserAgentManager:
    def __init__(self, ua_list: List[str]):
        # Если список пуст, используем дефолтный десктопный UA
        if ua_list:
            self._cycle = itertools.cycle(ua_list)
        else:
            default_ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
            self._cycle = itertools.cycle([default_ua])

    def next(self) -> str:
        """Возвращает следующий UA, крутится по кругу."""
        return next(self._cycle)


class ProxyManager:
    def __init__(self, proxies: List[str], retries_per_request: int = 3):
        self._proxies = proxies
        self._retries = retries_per_request
        self._cycle = itertools.cycle(proxies) if proxies else None

    def next_proxy(self) -> Optional[Dict[str, str]]:
        """
        Переходит к следующему прокси и возвращает dict вида:
        {"http": proxy_str, "https": proxy_str}
        Если список пуст — возвращает None (без прокси).
        """
        if not self._cycle:
            return None
        proxy_str = next(self._cycle)
        return {"http": proxy_str, "https": proxy_str}

    def request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Обёртка над requests.request.
        - При каждом запросе выбирает следующий прокси из списка.
        - Если возникает исключение RequestException или код ответа >= 500,
          пробует ещё раз с другим прокси.
        - Количество попыток = retries_per_request (если список прокси не пуст).
        - Если прокси нет, просто делает один запрос без них.
        """
        if not self._cycle:
            return requests.request(method, url, **kwargs)

        last_exc: Optional[Exception] = None
        for _ in range(self._retries):
            proxies = self.next_proxy()
            try:
                response = requests.request(method, url, proxies=proxies, **kwargs)
                if response.status_code >= 500:
                    last_exc = RequestException(
                        f"Server error: {response.status_code}"
                    )
                    continue
                return response
            except RequestException as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        return requests.request(method, url, **kwargs)
