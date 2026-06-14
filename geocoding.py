"""Configurable reverse geocoding with a small in-memory coordinate cache."""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReverseGeocoder:
    def __init__(
        self,
        provider: str = "",
        url: str = "",
        api_key: str = "",
        user_agent: str = "RTLS-Monitoring/1.0",
        cache_size: int = 1000,
    ) -> None:
        self.provider = provider.strip().lower()
        self.url = url.strip()
        self.api_key = api_key.strip()
        self.user_agent = user_agent.strip() or "RTLS-Monitoring/1.0"
        self.cache_size = max(1, cache_size)
        self.cache: OrderedDict[tuple[float, float], dict] = OrderedDict()
        self.lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "ReverseGeocoder":
        try:
            cache_size = int(os.environ.get("RTLS_GEOCODER_CACHE_SIZE", "1000"))
        except ValueError:
            cache_size = 1000
        return cls(
            provider=os.environ.get("RTLS_GEOCODER_PROVIDER", ""),
            url=os.environ.get("RTLS_GEOCODER_URL", ""),
            api_key=os.environ.get("RTLS_GEOCODER_API_KEY", ""),
            user_agent=os.environ.get(
                "RTLS_GEOCODER_USER_AGENT", "RTLS-Monitoring/1.0"
            ),
            cache_size=cache_size,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self.url)

    def _cache_key(self, lat: float, lng: float) -> tuple[float, float]:
        return round(lat, 4), round(lng, 4)

    def _request_url(self, lat: float, lng: float) -> str:
        values = {
            "lat": urllib.parse.quote(f"{lat:.7f}", safe=""),
            "lng": urllib.parse.quote(f"{lng:.7f}", safe=""),
            "api_key": urllib.parse.quote(self.api_key, safe=""),
        }
        url = self.url
        for key, value in values.items():
            url = url.replace(f"{{{key}}}", value)
        return url

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.provider == "kakao" and self.api_key:
            headers["Authorization"] = f"KakaoAK {self.api_key}"
        return headers

    def fetch_payload(self, lat: float, lng: float) -> dict:
        request = urllib.request.Request(
            self._request_url(lat, lng),
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ValueError(f"주소 API가 HTTP {exc.code} 오류를 반환했습니다.") from exc
        except URLError as exc:
            raise ValueError("주소 API에 연결할 수 없습니다.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("주소 API 응답을 해석할 수 없습니다.") from exc
        if not isinstance(payload, dict):
            raise ValueError("주소 API 응답 형식이 올바르지 않습니다.")
        return payload

    def parse_address(self, payload: dict) -> str:
        if self.provider == "kakao":
            documents = payload.get("documents") or []
            if documents:
                document = documents[0]
                road = document.get("road_address") or {}
                parcel = document.get("address") or {}
                return str(
                    road.get("address_name") or parcel.get("address_name") or ""
                ).strip()
        if self.provider == "nominatim":
            return str(payload.get("display_name") or "").strip()
        result = payload.get("result") or payload.get("data") or payload
        if isinstance(result, dict):
            return str(
                result.get("address")
                or result.get("address_name")
                or result.get("display_name")
                or ""
            ).strip()
        return ""

    def reverse(self, lat: float, lng: float) -> dict:
        if not self.enabled:
            raise ValueError("역지오코딩 API가 설정되지 않았습니다.")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("유효하지 않은 좌표입니다.")
        key = self._cache_key(lat, lng)
        with self.lock:
            cached = self.cache.get(key)
            if cached:
                self.cache.move_to_end(key)
                return dict(cached)

        address = self.parse_address(self.fetch_payload(lat, lng))
        if not address:
            raise ValueError("해당 좌표의 주소를 찾지 못했습니다.")
        result = {
            "address": address[:300],
            "provider": self.provider,
            "resolvedAt": now(),
        }
        with self.lock:
            self.cache[key] = result
            self.cache.move_to_end(key)
            while len(self.cache) > self.cache_size:
                self.cache.popitem(last=False)
        return dict(result)


class NullReverseGeocoder(ReverseGeocoder):
    def __init__(self) -> None:
        super().__init__()
