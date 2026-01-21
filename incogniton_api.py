from __future__ import annotations

from typing import Any, Dict, List

import requests


def _get_json(url: str, timeout: int = 10) -> Any:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def list_profiles(api_base: str, timeout: int = 10) -> List[Dict[str, Any]]:
    url = f"{api_base}/profile/all"
    data = _get_json(url, timeout=timeout)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, list):
        return data
    return []


def get_status(api_base: str, profile_id: str, timeout: int = 10) -> Dict[str, Any]:
    url = f"{api_base}/profile/status/{profile_id}"
    data = _get_json(url, timeout=timeout)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, dict):
        return data
    return {}


def launch_selenium(api_base: str, profile_id: str, timeout: int = 20) -> Dict[str, Any]:
    url = f"{api_base}/automation/launch/python/{profile_id}"
    data = _get_json(url, timeout=timeout)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, dict):
        return data
    return {}


def stop_profile(api_base: str, profile_id: str, timeout: int = 10) -> Dict[str, Any]:
    url = f"{api_base}/profile/stop/{profile_id}"
    data = _get_json(url, timeout=timeout)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, dict):
        return data
    return {}
