"""Public disaster-data providers and response normalization."""

import json
import hashlib
import os
import re
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from regions import REGIONS


KST = timezone(timedelta(hours=9))

REGION_ALIASES = {
    "서울": "KR-11",
    "부산": "KR-26",
    "대구": "KR-27",
    "인천": "KR-28",
    "광주": "KR-29",
    "대전": "KR-30",
    "울산": "KR-31",
    "세종": "KR-36",
    "경기": "KR-41",
    "강원": "KR-42",
    "충북": "KR-43",
    "충청북": "KR-43",
    "충남": "KR-44",
    "충청남": "KR-44",
    "전북": "KR-45",
    "전라북": "KR-45",
    "전남": "KR-46",
    "전라남": "KR-46",
    "경북": "KR-47",
    "경상북": "KR-47",
    "경남": "KR-48",
    "경상남": "KR-48",
    "제주": "KR-50",
}

for region in REGIONS:
    REGION_ALIASES[region["name"]] = region["id"]


def region_ids_from_text(value: str) -> list[str]:
    text = re.sub(r"\s+", "", str(value or ""))
    matches = []
    for alias, region_id in sorted(
        REGION_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if alias in text and region_id not in matches:
            matches.append(region_id)
    return matches


def normalize_datetime(value) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if text.isdigit() and len(text) in {8, 10, 12, 14}:
        formats = {
            8: "%Y%m%d",
            10: "%Y%m%d%H",
            12: "%Y%m%d%H%M",
            14: "%Y%m%d%H%M%S",
        }
        return datetime.strptime(text, formats[len(text)]).replace(
            tzinfo=KST
        ).isoformat(timespec="seconds")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt).replace(
                tzinfo=KST
            ).isoformat(timespec="seconds")
        except ValueError:
            continue
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat(timespec="seconds")


def _first(item: dict, *keys, default=""):
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return default


def _flatten_items(value) -> list[dict]:
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_flatten_items(item))
        return result
    if isinstance(value, dict):
        if any(
            key.lower()
            in {
                "msg",
                "msg_cn",
                "message",
                "title",
                "wrn",
                "warn_stress",
                "location_name",
                "rcptn_rgn_nm",
            }
            for key in value
        ):
            return [value]
        result = []
        for child in value.values():
            result.extend(_flatten_items(child))
        return result
    return []


def _parse_payload(body: bytes, content_type: str):
    text = body.decode("utf-8-sig")
    if "json" in content_type or text.lstrip().startswith(("{", "[")):
        return json.loads(text)
    root = ET.fromstring(text)
    return [
        {child.tag.split("}")[-1]: child.text or "" for child in item}
        for item in root.iter()
        if item.tag.split("}")[-1].lower() == "item"
    ]


def _severity(value: str) -> str:
    text = str(value or "").upper()
    if any(word in text for word in ("심각", "위급", "CRITICAL", "경보")):
        return "CRITICAL"
    if any(word in text for word in ("주의", "WARNING", "WARN")):
        return "WARNING"
    if any(word in text for word in ("예비", "ADVISORY")):
        return "ADVISORY"
    return "INFO"


def _fallback_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class PublicDataProvider:
    def __init__(self, name: str, url: str, api_key: str) -> None:
        self.name = name
        self.url = url
        self.api_key = api_key

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.api_key)

    def _request_url(self) -> str:
        if "{service_key}" in self.url:
            return self.url.replace(
                "{service_key}", urllib.parse.quote(self.api_key, safe="")
            )
        separator = "&" if "?" in self.url else "?"
        return (
            f"{self.url}{separator}"
            + urllib.parse.urlencode(
                {"serviceKey": self.api_key, "pageNo": 1, "numOfRows": 100, "type": "json"}
            )
        )

    def fetch_items(self) -> list[dict]:
        body, content_type = self.fetch_raw()
        payload = _parse_payload(body, content_type)
        return _flatten_items(payload)

    def fetch_raw(self) -> tuple[bytes, str]:
        request = urllib.request.Request(
            self._request_url(),
            headers={"Accept": "application/json, application/xml;q=0.9"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read(), response.headers.get("Content-Type", "")

    def fetch(self) -> list[dict]:
        raise NotImplementedError


class DisasterMessageProvider(PublicDataProvider):
    def fetch(self) -> list[dict]:
        alerts = []
        for item in self.fetch_items():
            message = str(
                _first(item, "MSG_CN", "msg", "message", "content", "title")
            )
            region_text = str(
                _first(
                    item,
                    "RCPTN_RGN_NM",
                    "location_name",
                    "region",
                    "location",
                )
            )
            source_id = str(
                _first(
                    item,
                    "SN",
                    "md101_sn",
                    "id",
                    "seq",
                    default=_fallback_id(message),
                )
            )
            issued_at = normalize_datetime(
                _first(item, "CRT_DT", "create_date", "created_at", "date")
            )
            category = str(
                _first(item, "DST_SE_NM", "emergency_step", "category", default="재난문자")
            )
            regions = region_ids_from_text(region_text)
            for region_id in regions:
                alerts.append(
                    {
                        "sourceId": f"{source_id}:{region_id}",
                        "source": self.name,
                        "regionId": region_id,
                        "type": "DISASTER_MESSAGE",
                        "severity": _severity(
                            _first(item, "EMRG_STEP_NM", "emergency_step", "severity")
                        ),
                        "title": category or "긴급재난문자",
                        "message": message,
                        "issuedAt": issued_at,
                    }
                )
        return alerts


class WeatherWarningProvider(PublicDataProvider):
    @staticmethod
    def parse_text_items(text: str) -> list[dict]:
        items = []
        columns = [
            "REG_UP",
            "REG_UP_KO",
            "REG_ID",
            "REG_KO",
            "TM_FC",
            "TM_EF",
            "WRN",
            "LVL",
            "CMD",
            "ED_TM",
        ]
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            values = re.split(r"\s+", line)
            if len(values) < len(columns) - 1:
                continue
            values += [""] * (len(columns) - len(values))
            items.append(dict(zip(columns, values[: len(columns)])))
        return items

    def fetch_items(self) -> list[dict]:
        body, content_type = self.fetch_raw()
        text = body.decode("utf-8-sig", errors="replace")
        if "#START" in text or "# REG_UP" in text:
            return self.parse_text_items(text)
        return _flatten_items(_parse_payload(body, content_type))

    def fetch(self) -> list[dict]:
        alerts = []
        for item in self.fetch_items():
            warning_type = str(
                _first(item, "WRN", "warn_stress", "warning", default="기상특보")
            )
            warning_level = str(_first(item, "LVL", "level", "severity"))
            title = str(
                _first(
                    item,
                    "TITLE",
                    default=f"{warning_type} {warning_level}".strip(),
                )
            )
            message = str(
                _first(
                    item,
                    "T6",
                    "content",
                    "message",
                    "remark",
                    default=f"{_first(item, 'REG_KO', 'REG_UP_KO')} {title}".strip(),
                )
            )
            region_text = " ".join(
                str(_first(item, key))
                for key in (
                    "REGION",
                    "REG_NAME",
                    "AREA_NAME",
                    "STN_NAME",
                    "REG_UP_KO",
                    "REG_KO",
                )
            )
            if not region_text.strip():
                region_text = f"{title} {message}"
            source_id = str(
                _first(
                    item,
                    "TM_SEQ",
                    "id",
                    "seq",
                    default=(
                        f"{_first(item, 'TM_FC')}:{_first(item, 'REG_ID')}:"
                        f"{warning_type}"
                    )
                    or _fallback_id(message),
                )
            )
            issued_at = normalize_datetime(
                _first(item, "TM_FC", "issued_at", "created_at", "date")
            )
            for region_id in region_ids_from_text(region_text):
                command = str(_first(item, "CMD", "command")).upper()
                expires_at = None
                if command in {"2", "해제", "CANCEL", "CANCELLED"}:
                    expires_at = issued_at
                alerts.append(
                    {
                        "sourceId": f"{source_id}:{region_id}",
                        "source": self.name,
                        "regionId": region_id,
                        "type": "WEATHER_WARNING",
                        "severity": _severity(f"{title} {warning_level} {message}"),
                        "title": title,
                        "message": message,
                        "issuedAt": issued_at,
                        "expiresAt": expires_at,
                    }
                )
        return alerts


class PublicDataSynchronizer:
    def __init__(
        self,
        upsert: Callable[[list[dict]], list[dict]],
        status_callback: Callable[[dict], None],
        interval_seconds: int = 300,
        providers: Optional[list[PublicDataProvider]] = None,
    ) -> None:
        self.upsert = upsert
        self.status_callback = status_callback
        self.interval_seconds = max(30, interval_seconds)
        self.providers = providers or []
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    @classmethod
    def from_environment(cls, upsert, status_callback):
        providers = [
            DisasterMessageProvider(
                "행정안전부 긴급재난문자",
                os.environ.get("RTLS_DISASTER_API_URL", ""),
                os.environ.get("RTLS_DISASTER_API_KEY", ""),
            ),
            WeatherWarningProvider(
                "기상청 기상특보",
                os.environ.get("RTLS_WEATHER_API_URL", ""),
                os.environ.get("RTLS_WEATHER_API_KEY", ""),
            ),
        ]
        return cls(
            upsert,
            status_callback,
            int(os.environ.get("RTLS_PUBLIC_DATA_INTERVAL", "300")),
            providers,
        )

    def enabled_providers(self) -> list[PublicDataProvider]:
        return [provider for provider in self.providers if provider.enabled]

    def sync_once(self) -> int:
        providers = self.enabled_providers()
        if not providers:
            self.status_callback(
                {"connected": False, "message": "공공데이터 API URL 또는 키 미설정"}
            )
            return 0
        total = 0
        errors = []
        for provider in providers:
            try:
                alerts = provider.fetch()
                self.upsert(alerts)
                total += len(alerts)
            except Exception:
                errors.append(f"{provider.name}: 연결 또는 응답 변환 실패")
        self.status_callback(
            {
                "connected": not errors,
                "message": (
                    f"공공데이터 {total}건 동기화"
                    if not errors
                    else " / ".join(errors)[:300]
                ),
            }
        )
        return total

    def start(self) -> None:
        if self.thread or not self.enabled_providers():
            return
        self.thread = threading.Thread(
            target=self._run, name="public-data-sync", daemon=True
        )
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self.sync_once()
            self.stop_event.wait(self.interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
