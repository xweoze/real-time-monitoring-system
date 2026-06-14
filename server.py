#!/usr/bin/env python3
"""Real-time vulnerable population monitoring system MVP."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import queue
import re
import socket
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from auth import AuthRepository, AuthenticationError, AuthorizationError
from disaster_rag import DisasterKnowledgeBase
from geocoding import ReverseGeocoder
from notifications import WebhookNotifier
from public_data import PublicDataSynchronizer, load_environment_file
from regions import REGIONS, REGION_BY_ID


ROOT = Path(__file__).resolve().parent
load_environment_file(ROOT / ".env")
STATIC = ROOT / "static"
HOST = os.environ.get("RTLS_HOST", "0.0.0.0")
PORT = int(os.environ.get("RTLS_PORT", "8080"))
DATA_DIR = ROOT / "data"
DATABASE_PATH = Path(os.environ.get("RTLS_DATABASE", DATA_DIR / "rtls.db"))
CLIENT_TIMEOUT_SECONDS = 45
PERSIST_DEBOUNCE_SECONDS = 3.0
IMMOBILITY_SECONDS = 15 * 60
IMMOBILITY_DISTANCE_METERS = 20
LOW_BATTERY_PERCENT = 20


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def point_in_polygon(lat: float, lng: float, points: list[dict]) -> bool:
    inside = False
    previous = points[-1]
    for current in points:
        y1, x1 = float(previous["lat"]), float(previous["lng"])
        y2, x2 = float(current["lat"]), float(current["lng"])
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lng < crossing:
                inside = not inside
        previous = current
    return inside


SAFETY_GUIDES = {
    "HEAVY_RAIN": {
        "title": "호우·침수",
        "steps": ["지하 공간과 하천 주변에서 즉시 이동", "침수 도로는 차량과 도보 모두 진입 금지", "재난문자와 지자체 대피 안내 확인"],
    },
    "EARTHQUAKE": {
        "title": "지진",
        "steps": ["튼튼한 탁자 아래에서 머리 보호", "흔들림이 멈춘 뒤 계단으로 대피", "건물·담장·전신주에서 거리 확보"],
    },
    "FIRE": {
        "title": "화재",
        "steps": ["119 신고 후 낮은 자세로 이동", "엘리베이터 대신 계단 사용", "연기가 많으면 젖은 천으로 코와 입 보호"],
    },
    "HEAT": {
        "title": "폭염",
        "steps": ["낮 시간 야외활동 최소화", "물을 자주 마시고 무더위쉼터 이용", "어지럼증·의식 저하 시 119 신고"],
    },
    "COLD": {
        "title": "한파",
        "steps": ["외출 시 보온 장비 착용", "빙판길과 수도 동파 주의", "취약계층의 난방과 건강 상태 확인"],
    },
}


def regional_facilities(region_id: str) -> list[dict]:
    region = REGION_BY_ID[region_id]
    lat, lng = region["lat"], region["lng"]
    return [
        {"id": f"{region_id}-SHELTER", "type": "SHELTER", "name": f"{region['name']} 대표 대피소", "lat": lat + 0.008, "lng": lng - 0.006, "source": "기본 안전시설 데이터"},
        {"id": f"{region_id}-HOSPITAL", "type": "HOSPITAL", "name": f"{region['name']} 권역 응급의료기관", "lat": lat - 0.006, "lng": lng + 0.007, "source": "기본 안전시설 데이터"},
        {"id": f"{region_id}-FIRE", "type": "FIRE_STATION", "name": f"{region['name']} 대표 소방서", "lat": lat + 0.003, "lng": lng + 0.009, "source": "기본 안전시설 데이터"},
    ]


class SQLiteStateRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def load(self) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM state WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else None

    def save(self, state: dict) -> None:
        payload = json.dumps(state, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO state (id, payload) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )


class MonitoringStore:
    def __init__(
        self,
        repository: Optional[SQLiteStateRepository] = None,
        client_timeout_seconds: int = CLIENT_TIMEOUT_SECONDS,
        persist_debounce_seconds: float = PERSIST_DEBOUNCE_SECONDS,
        notifier: Optional[WebhookNotifier] = None,
    ) -> None:
        self.lock = threading.RLock()
        self.repository = repository
        self.client_timeout_seconds = client_timeout_seconds
        self.persist_debounce_seconds = persist_debounce_seconds
        self.notifier = notifier
        self.clients: dict[str, dict] = {}
        self.clients_by_region: dict[str, set[str]] = {
            region["id"]: set() for region in REGIONS
        }
        self.client_by_user: dict[str, str] = {}
        self.routes: dict[str, list[dict]] = {}
        self.sos_events: dict[str, dict] = {}
        self.public_alerts: dict[str, dict] = {}
        self.public_alert_status = {
            "connected": False,
            "message": "공공데이터 동기화 대기",
        }
        self.timeline: list[dict] = []
        self.audit_logs: list[dict] = []
        self.groups: dict[str, dict] = {}
        self.subscribers: list[queue.Queue] = []
        self.sequence = 0
        self._persist_timer: Optional[threading.Timer] = None
        self._last_persist_at = 0.0
        self._dirty = False
        self.danger_areas = []
        self._restore()

    def _restore(self) -> None:
        if not self.repository:
            return
        state = self.repository.load()
        if not state:
            return
        self.clients = state.get("clients", {})
        self.routes = state.get("routes", {})
        self.sos_events = state.get("sosEvents", {})
        self.public_alerts = state.get("publicAlerts", {})
        self.timeline = state.get("timeline", [])[:100]
        self.audit_logs = state.get("auditLogs", [])[:500]
        self.groups = state.get("groups", {})
        self.danger_areas = state.get("dangerAreas", [])
        self.sequence = int(state.get("sequence", 0))
        for client in self.clients.values():
            client["connectionStatus"] = "OFFLINE"
            client.setdefault("regionId", "KR-11")
            client.setdefault("userId", None)
            client.setdefault("birthDate", None)
            client.setdefault("gender", "UNDISCLOSED")
            client.setdefault("batteryLevel", None)
            client.setdefault("batteryCharging", None)
            client.setdefault("activeDangerAreaIds", [])
            client.setdefault("groupIds", [])
            client.setdefault("movement", {"lastMovedAt": client.get("updatedAt"), "immobile": False})
            client.setdefault("warnings", {"signalLost": False, "lowBattery": False, "immobile": False})
        for event in self.sos_events.values():
            event.setdefault("assignedAt", event.get("acknowledgedAt"))
            event.setdefault("dispatchedAt", None)
            event.setdefault("cancelledAt", None)
            event.setdefault("note", "")
            event.setdefault("history", [])
        self._rebuild_indexes()

    def _state_payload(self) -> dict:
        return {
            "clients": self.clients,
            "routes": self.routes,
            "sosEvents": self.sos_events,
            "publicAlerts": self.public_alerts,
            "timeline": self.timeline,
            "auditLogs": self.audit_logs,
            "groups": self.groups,
            "dangerAreas": self.danger_areas,
            "sequence": self.sequence,
        }

    def _persist(self, force: bool = False) -> None:
        if not self.repository:
            return
        elapsed = time.monotonic() - self._last_persist_at
        if force or elapsed >= self.persist_debounce_seconds:
            if self._persist_timer:
                self._persist_timer.cancel()
                self._persist_timer = None
            self.repository.save(self._state_payload())
            self._last_persist_at = time.monotonic()
            self._dirty = False
            return

        self._dirty = True
        if self._persist_timer:
            return
        delay = max(0.01, self.persist_debounce_seconds - elapsed)
        self._persist_timer = threading.Timer(delay, self.flush)
        self._persist_timer.daemon = True
        self._persist_timer.start()

    def flush(self) -> None:
        with self.lock:
            if self._persist_timer:
                self._persist_timer.cancel()
            self._persist_timer = None
            if self._dirty:
                self._persist(force=True)

    def _rebuild_indexes(self) -> None:
        for client_ids in self.clients_by_region.values():
            client_ids.clear()
        self.client_by_user.clear()
        for client_id, client in self.clients.items():
            region_id = client.get("regionId", "KR-11")
            self.clients_by_region.setdefault(region_id, set()).add(client_id)
            if client.get("userId"):
                self.client_by_user[client["userId"]] = client_id

    def _publish(self, event_type: str, data: dict) -> None:
        message = {"type": event_type, "data": data, "sentAt": now()}
        dead = []
        for subscriber in self.subscribers:
            try:
                subscriber.put_nowait(message)
            except queue.Full:
                dead.append(subscriber)
        for subscriber in dead:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def _log(self, event_type: str, title: str, client_id: str = "", severity: str = "INFO") -> dict:
        event = {
            "id": f"LOG-{uuid.uuid4().hex[:8].upper()}",
            "type": event_type,
            "title": title,
            "clientId": client_id,
            "severity": severity,
            "createdAt": now(),
        }
        self.timeline.insert(0, event)
        self.timeline = self.timeline[:100]
        if self.notifier:
            client = self.clients.get(client_id, {})
            self.notifier.enqueue(
                {
                    **event,
                    "clientName": client.get("name"),
                    "regionId": client.get("regionId"),
                    "location": client.get("location"),
                }
            )
        return event

    def audit(
        self,
        actor: dict,
        action: str,
        target: str,
        detail: str = "",
        region_id: Optional[str] = None,
    ) -> dict:
        with self.lock:
            entry = {
                "id": f"AUD-{uuid.uuid4().hex[:8].upper()}",
                "actorId": actor["id"],
                "actorName": actor["displayName"],
                "role": actor["role"],
                "action": str(action)[:60],
                "target": str(target)[:100],
                "detail": str(detail)[:500],
                "regionId": region_id or actor.get("regionId"),
                "createdAt": now(),
            }
            self.audit_logs.insert(0, entry)
            self.audit_logs = self.audit_logs[:500]
            self._persist(force=True)
            return dict(entry)

    def register(self, payload: dict) -> dict:
        with self.lock:
            self.sequence += 1
            client_id = f"C-{self.sequence:04d}"
            client = {
                "id": client_id,
                "name": str(payload.get("name") or f"사용자 {self.sequence}")[:30],
                "deviceId": str(payload.get("deviceId") or uuid.uuid4().hex[:12])[:40],
                "userId": payload.get("userId"),
                "birthDate": payload.get("birthDate"),
                "gender": payload.get("gender", "UNDISCLOSED"),
                "regionId": (
                    payload.get("regionId")
                    if payload.get("regionId") in REGION_BY_ID
                    else "KR-11"
                ),
                "connectionStatus": "ONLINE",
                "state": "NORMAL",
                "dangerState": "SAFE",
                "dangerArea": None,
                "location": None,
                "connectedAt": now(),
                "updatedAt": now(),
                "lastSeenAt": now(),
                "batteryLevel": None,
                "batteryCharging": None,
                "activeDangerAreaIds": [],
                "groupIds": [],
                "movement": {"lastMovedAt": now(), "immobile": False},
                "warnings": {"signalLost": False, "lowBattery": False, "immobile": False},
            }
            self.clients[client_id] = client
            self.clients_by_region[client["regionId"]].add(client_id)
            if client.get("userId"):
                self.client_by_user[client["userId"]] = client_id
            self.routes[client_id] = []
            event = self._log("CONNECT", f"{client['name']} 접속", client_id)
            self._publish("state", {"event": event})
            self._persist(force=True)
            return dict(client)

    def update_location(self, client_id: str, payload: dict) -> dict:
        lat = float(payload.get("lat"))
        lng = float(payload.get("lng"))
        accuracy = max(0.0, float(payload.get("accuracy", 0)))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("유효하지 않은 좌표입니다.")

        with self.lock:
            client = self._require_client(client_id)
            previous_area_ids = set(client.get("activeDangerAreaIds", []))
            active_areas = []
            for area in self.danger_areas:
                if area["shape"] == "POLYGON":
                    matched = point_in_polygon(lat, lng, area["points"])
                else:
                    matched = distance_m(lat, lng, area["lat"], area["lng"]) <= area["radius"]
                if matched:
                    active_areas.append(area)
            danger_area = max(active_areas, key=lambda area: area["severity"], default=None)
            active_area_ids = {area["id"] for area in active_areas}

            point = {
                "lat": lat,
                "lng": lng,
                "accuracy": accuracy,
                "capturedAt": str(payload.get("capturedAt") or now()),
            }
            previous_point = client.get("location")
            movement = client.setdefault(
                "movement", {"lastMovedAt": point["capturedAt"], "immobile": False}
            )
            if (
                not previous_point
                or distance_m(lat, lng, previous_point["lat"], previous_point["lng"])
                >= IMMOBILITY_DISTANCE_METERS
            ):
                movement["lastMovedAt"] = point["capturedAt"]
                movement["immobile"] = False
            else:
                movement["immobile"] = (
                    parse_time(point["capturedAt"]) - parse_time(movement["lastMovedAt"])
                ).total_seconds() >= IMMOBILITY_SECONDS
            battery_level = payload.get("batteryLevel")
            if battery_level is not None:
                battery_level = max(0, min(100, round(float(battery_level))))
                client["batteryLevel"] = battery_level
                client["batteryCharging"] = bool(payload.get("batteryCharging"))
            client.update(
                {
                    "location": point,
                    "state": str(payload.get("state") or "NORMAL")[:20],
                    "dangerState": "DANGER" if danger_area else "SAFE",
                    "dangerArea": dict(danger_area) if danger_area else None,
                    "activeDangerAreaIds": sorted(active_area_ids),
                    "connectionStatus": "ONLINE",
                    "updatedAt": now(),
                    "lastSeenAt": now(),
                }
            )
            self.routes[client_id].append(point)
            self.routes[client_id] = self.routes[client_id][-500:]

            events = []
            area_by_id = {area["id"]: area for area in self.danger_areas}
            for area_id in sorted(active_area_ids - previous_area_ids):
                area = area_by_id[area_id]
                events.append(self._log(
                    "DANGER_ENTER", f"{area['name']} 진입 감지", client_id,
                    "CRITICAL" if area["severity"] >= 5 else "WARNING",
                ))
            for area_id in sorted(previous_area_ids - active_area_ids):
                area = area_by_id.get(area_id, {"name": "위험 구역"})
                events.append(self._log("DANGER_EXIT", f"{area['name']} 이탈 감지", client_id))
            warnings = client.setdefault("warnings", {})
            low_battery = client.get("batteryLevel") is not None and client["batteryLevel"] <= LOW_BATTERY_PERCENT and not client.get("batteryCharging")
            if low_battery and not warnings.get("lowBattery"):
                events.append(self._log("LOW_BATTERY", f"{client['name']} 배터리 부족", client_id, "WARNING"))
            if movement["immobile"] and not warnings.get("immobile"):
                events.append(self._log("IMMOBILE", f"{client['name']} 장시간 움직임 없음", client_id, "WARNING"))
            warnings.update({"lowBattery": low_battery, "immobile": movement["immobile"], "signalLost": False})
            event = events[0] if events else None
            self._publish("state", {"event": event, "clientId": client_id})
            self._persist(force=bool(events))
            return dict(client)

    def set_location_address(
        self,
        client_id: str,
        result: dict,
        expected_lat: Optional[float] = None,
        expected_lng: Optional[float] = None,
    ) -> dict:
        with self.lock:
            client = self._require_client(client_id)
            location = client.get("location")
            if not location:
                raise ValueError("위치를 먼저 전송해 주세요.")
            if (
                expected_lat is not None
                and expected_lng is not None
                and (
                    location["lat"] != expected_lat
                    or location["lng"] != expected_lng
                )
            ):
                raise ValueError(
                    "주소 조회 중 위치가 변경되었습니다. 다시 확인해 주세요."
                )
            location["address"] = str(result.get("address") or "")[:300]
            location["addressProvider"] = str(result.get("provider") or "")[:30]
            location["addressResolvedAt"] = result.get("resolvedAt") or now()
            client["updatedAt"] = now()
            self._publish("state", {"clientId": client_id, "addressUpdated": True})
            self._persist(force=True)
            return dict(client)

    def create_sos(self, client_id: str, payload: dict) -> dict:
        with self.lock:
            client = self._require_client(client_id)
            location = client.get("location")
            if not location:
                raise ValueError("위치를 먼저 전송해 주세요.")
            event_id = f"SOS-{uuid.uuid4().hex[:6].upper()}"
            event = {
                "id": event_id,
                "clientId": client_id,
                "clientName": client["name"],
                "status": "OPEN",
                "message": str(payload.get("message") or "긴급 구조 요청")[:200],
                "location": location,
                "createdAt": now(),
                "acknowledgedAt": None,
                "assignedAt": None,
                "dispatchedAt": None,
                "resolvedAt": None,
                "cancelledAt": None,
                "operator": None,
                "note": "",
                "history": [],
            }
            self.sos_events[event_id] = event
            log = self._log("SOS", f"{client['name']} 긴급 구조 요청", client_id, "CRITICAL")
            self._publish("state", {"event": log, "sosId": event_id})
            self._persist(force=True)
            return dict(event)

    def update_sos(
        self, event_id: str, status: str, operator: str, note: str = ""
    ) -> dict:
        if status not in {"ACKNOWLEDGED", "DISPATCHED", "RESOLVED", "CANCELLED"}:
            raise ValueError("지원하지 않는 SOS 상태입니다.")
        with self.lock:
            event = self.sos_events.get(event_id)
            if not event:
                raise KeyError("SOS 이벤트를 찾을 수 없습니다.")
            allowed = {
                "OPEN": {"ACKNOWLEDGED", "CANCELLED"},
                "ACKNOWLEDGED": {"DISPATCHED", "CANCELLED"},
                "DISPATCHED": {"RESOLVED", "CANCELLED"},
                "RESOLVED": set(),
                "CANCELLED": set(),
            }
            if status not in allowed.get(event["status"], set()):
                raise ValueError(f"{event['status']} 상태에서 {status}(으)로 변경할 수 없습니다.")
            changed_at = now()
            operator_name = operator[:30] or "관제 요원"
            note_text = str(note or "").strip()[:500]
            event["status"] = status
            event["operator"] = operator_name
            event["note"] = note_text
            event.setdefault("history", []).append(
                {
                    "status": status,
                    "operator": operator_name,
                    "note": note_text,
                    "createdAt": changed_at,
                }
            )
            if status == "ACKNOWLEDGED":
                event["acknowledgedAt"] = changed_at
                event["assignedAt"] = changed_at
                title = f"{event['id']} 구조 접수·담당자 배정"
            elif status == "DISPATCHED":
                event["dispatchedAt"] = changed_at
                title = f"{event['id']} 구조 출동"
            elif status == "RESOLVED":
                event["resolvedAt"] = changed_at
                title = f"{event['id']} 구조 완료"
            else:
                event["cancelledAt"] = changed_at
                title = f"{event['id']} 요청 취소"
            log = self._log("RESCUE", title, event["clientId"])
            self._publish("state", {"event": log, "sosId": event_id})
            self._persist(force=True)
            return dict(event)

    def heartbeat(self, client_id: str, payload: Optional[dict] = None) -> dict:
        with self.lock:
            client = self._require_client(client_id)
            payload = payload or {}
            was_offline = client["connectionStatus"] == "OFFLINE"
            client["connectionStatus"] = "ONLINE"
            client["lastSeenAt"] = now()
            client.setdefault("warnings", {})["signalLost"] = False
            if payload.get("batteryLevel") is not None:
                client["batteryLevel"] = max(
                    0, min(100, round(float(payload["batteryLevel"])))
                )
                client["batteryCharging"] = bool(payload.get("batteryCharging"))
            warnings = client.setdefault("warnings", {})
            low_battery = client.get("batteryLevel") is not None and client["batteryLevel"] <= LOW_BATTERY_PERCENT and not client.get("batteryCharging")
            movement = client.setdefault(
                "movement", {"lastMovedAt": client.get("updatedAt") or now(), "immobile": False}
            )
            if client.get("location"):
                movement["immobile"] = (
                    datetime.now(timezone.utc) - parse_time(movement["lastMovedAt"])
                ).total_seconds() >= IMMOBILITY_SECONDS
            generated = []
            if low_battery and not warnings.get("lowBattery"):
                generated.append(self._log("LOW_BATTERY", f"{client['name']} 배터리 부족", client_id, "WARNING"))
            if movement["immobile"] and not warnings.get("immobile"):
                generated.append(self._log("IMMOBILE", f"{client['name']} 장시간 움직임 없음", client_id, "WARNING"))
            warnings.update({"signalLost": False, "lowBattery": low_battery, "immobile": movement["immobile"]})
            if was_offline:
                event = self._log("RECONNECT", f"{client['name']} 연결 복구", client_id)
                self._publish("state", {"event": event, "clientId": client_id})
                self._persist(force=True)
            elif generated:
                self._publish("state", {"event": generated[0], "clientId": client_id})
                self._persist(force=True)
            else:
                self._persist()
            return dict(client)

    def disconnect(self, client_id: str) -> dict:
        with self.lock:
            client = self._require_client(client_id)
            client["connectionStatus"] = "OFFLINE"
            client["updatedAt"] = now()
            client["lastSeenAt"] = now()
            event = self._log("DISCONNECT", f"{client['name']} 접속 종료", client_id)
            self._publish("state", {"event": event, "clientId": client_id})
            self._persist(force=True)
            return dict(client)

    def snapshot(self, region_id: Optional[str] = None) -> dict:
        with self.lock:
            self._expire_stale_clients()
            public_alerts = self.active_public_alerts(region_id)
            danger_areas = self.danger_areas
            sos_events = list(self.sos_events.values())
            timeline = self.timeline
            if region_id:
                client_ids = self.clients_by_region.get(region_id, set())
                clients = [self.clients[client_id] for client_id in sorted(client_ids)]
                danger_areas = [
                    item for item in danger_areas if item.get("regionId") == region_id
                ]
                sos_events = [
                    item for item in sos_events if item.get("clientId") in client_ids
                ]
                timeline = [
                    item
                    for item in timeline
                    if not item.get("clientId") or item.get("clientId") in client_ids
                ]
            else:
                clients = list(self.clients.values())
            return {
                "clients": clients,
                "dangerAreas": danger_areas,
                "sosEvents": sorted(
                    sos_events, key=lambda item: item["createdAt"], reverse=True
                ),
                "timeline": timeline,
                "regions": self._region_summaries(),
                "publicAlerts": public_alerts,
                "publicAlertStatus": dict(self.public_alert_status),
                "notificationStatus": (
                    self.notifier.status()
                    if self.notifier
                    else {"enabled": False, "delivered": 0, "dropped": 0, "lastError": ""}
                ),
                "groups": [
                    group
                    for group in self.groups.values()
                    if not region_id or group.get("regionId") in {None, region_id}
                ],
                "auditLogs": [
                    entry
                    for entry in self.audit_logs
                    if not region_id or entry.get("regionId") == region_id
                ][:200],
                "serverTime": now(),
            }

    def create_danger_area(self, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        region_id = str(payload.get("regionId") or "")
        shape = str(payload.get("shape") or "CIRCLE").upper()
        severity = int(payload.get("severity", 3))
        if not name or len(name) > 80:
            raise ValueError("위험구역 이름은 1~80자로 입력해 주세요.")
        if region_id not in REGION_BY_ID:
            raise ValueError("유효한 지역을 선택해 주세요.")
        if shape not in {"CIRCLE", "POLYGON"}:
            raise ValueError("위험구역 형태가 유효하지 않습니다.")
        if not 1 <= severity <= 5:
            raise ValueError("위험도는 1~5 사이여야 합니다.")
        area = {
            "id": f"AREA-{uuid.uuid4().hex[:8].upper()}",
            "name": name,
            "regionId": region_id,
            "shape": shape,
            "severity": severity,
            "createdAt": now(),
        }
        if shape == "CIRCLE":
            lat = float(payload.get("lat"))
            lng = float(payload.get("lng"))
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError("원형 위험구역 좌표가 유효하지 않습니다.")
            area.update(
                {
                    "lat": lat,
                    "lng": lng,
                    "radius": max(10, min(100_000, float(payload.get("radius", 100)))),
                }
            )
        else:
            raw_points = payload.get("points")
            if not isinstance(raw_points, list) or not 3 <= len(raw_points) <= 200:
                raise ValueError("다각형은 3~200개의 꼭짓점이 필요합니다.")
            points = []
            for point in raw_points:
                lat, lng = float(point["lat"]), float(point["lng"])
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    raise ValueError("다각형 좌표가 유효하지 않습니다.")
                points.append({"lat": lat, "lng": lng})
            area["points"] = points
        with self.lock:
            self.danger_areas.append(area)
            self._publish("state", {"dangerAreaId": area["id"]})
            self._persist(force=True)
        return dict(area)

    def delete_danger_area(self, area_id: str) -> dict:
        with self.lock:
            area = next(
                (item for item in self.danger_areas if item["id"] == area_id), None
            )
            if not area:
                raise KeyError("위험구역을 찾을 수 없습니다.")
            self.danger_areas = [
                item for item in self.danger_areas if item["id"] != area_id
            ]
            for client in self.clients.values():
                active = set(client.get("activeDangerAreaIds", []))
                if area_id in active:
                    active.remove(area_id)
                    client["activeDangerAreaIds"] = sorted(active)
                    if (client.get("dangerArea") or {}).get("id") == area_id:
                        client["dangerArea"] = None
                        client["dangerState"] = "DANGER" if active else "SAFE"
            self._publish("state", {"dangerAreaId": area_id, "deleted": True})
            self._persist(force=True)
            return dict(area)

    def create_group(self, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        region_id = payload.get("regionId") or None
        if not name or len(name) > 40:
            raise ValueError("그룹 이름은 1~40자로 입력해 주세요.")
        if region_id and region_id not in REGION_BY_ID:
            raise ValueError("유효한 그룹 지역을 선택해 주세요.")
        group = {
            "id": f"GRP-{uuid.uuid4().hex[:8].upper()}",
            "name": name,
            "regionId": region_id,
            "color": str(payload.get("color") or "#1677e8")[:20],
            "memberIds": [],
            "createdAt": now(),
        }
        with self.lock:
            self.groups[group["id"]] = group
            self._publish("state", {"groupId": group["id"]})
            self._persist(force=True)
        return dict(group)

    def set_group_members(self, group_id: str, member_ids: list[str]) -> dict:
        if not isinstance(member_ids, list):
            raise ValueError("memberIds는 배열이어야 합니다.")
        with self.lock:
            group = self.groups.get(group_id)
            if not group:
                raise KeyError("그룹을 찾을 수 없습니다.")
            if group.get("regionId") and any(
                self.clients.get(client_id, {}).get("regionId") != group["regionId"]
                for client_id in member_ids
                if client_id in self.clients
            ):
                raise ValueError("지역 그룹에는 같은 지역 사용자만 배정할 수 있습니다.")
            valid_ids = {
                client_id for client_id in member_ids if client_id in self.clients
            }
            group["memberIds"] = sorted(valid_ids)
            for client in self.clients.values():
                groups = set(client.get("groupIds", []))
                if client["id"] in valid_ids:
                    groups.add(group_id)
                else:
                    groups.discard(group_id)
                client["groupIds"] = sorted(groups)
            self._publish("state", {"groupId": group_id})
            self._persist(force=True)
            return dict(group)

    def delete_group(self, group_id: str) -> dict:
        with self.lock:
            group = self.groups.pop(group_id, None)
            if not group:
                raise KeyError("그룹을 찾을 수 없습니다.")
            for client in self.clients.values():
                client["groupIds"] = [
                    item for item in client.get("groupIds", []) if item != group_id
                ]
            self._publish("state", {"groupId": group_id, "deleted": True})
            self._persist(force=True)
            return dict(group)

    def client_analytics(self, client_id: str) -> dict:
        with self.lock:
            self._require_client(client_id)
            points = list(self.routes.get(client_id, []))
        distance = sum(
            distance_m(
                previous["lat"], previous["lng"], current["lat"], current["lng"]
            )
            for previous, current in zip(points, points[1:])
        )
        stationary_seconds = 0.0
        visits: dict[tuple[float, float], dict] = {}
        for previous, current in zip(points, points[1:]):
            elapsed = max(
                0,
                (parse_time(current["capturedAt"]) - parse_time(previous["capturedAt"])).total_seconds(),
            )
            if distance_m(previous["lat"], previous["lng"], current["lat"], current["lng"]) <= 30:
                stationary_seconds += elapsed
            key = (round(current["lat"], 3), round(current["lng"], 3))
            visit = visits.setdefault(
                key,
                {"lat": key[0], "lng": key[1], "visits": 0, "lastVisitedAt": current["capturedAt"]},
            )
            visit["visits"] += 1
            visit["lastVisitedAt"] = current["capturedAt"]
        return {
            "distanceMeters": round(distance, 1),
            "stationarySeconds": round(stationary_seconds),
            "frequentPlaces": sorted(
                visits.values(), key=lambda item: item["visits"], reverse=True
            )[:5],
            "pointCount": len(points),
        }

    def nearby_facilities(self, client_id: str) -> list[dict]:
        client = self.client(client_id)
        location = client.get("location")
        if not location:
            raise ValueError("위치를 먼저 전송해 주세요.")
        facilities = regional_facilities(client["regionId"])
        return sorted(
            [
                {
                    **facility,
                    "distanceMeters": round(
                        distance_m(
                            location["lat"],
                            location["lng"],
                            facility["lat"],
                            facility["lng"],
                        )
                    ),
                }
                for facility in facilities
            ],
            key=lambda item: item["distanceMeters"],
        )

    def active_public_alerts(self, region_id: Optional[str] = None) -> list[dict]:
        current = datetime.now(timezone.utc)
        alerts = []
        for alert in self.public_alerts.values():
            if region_id and alert["regionId"] != region_id:
                continue
            expires_at = alert.get("expiresAt")
            if expires_at and parse_time(expires_at) <= current:
                continue
            alerts.append(dict(alert))
        return sorted(alerts, key=lambda item: item["issuedAt"], reverse=True)

    def upsert_public_alerts(self, alerts: list[dict]) -> list[dict]:
        if not isinstance(alerts, list):
            raise ValueError("alerts는 배열이어야 합니다.")
        normalized = []
        with self.lock:
            for item in alerts[:500]:
                if not isinstance(item, dict):
                    raise ValueError("각 공공 알림은 JSON 객체여야 합니다.")
                region_id = str(item.get("regionId") or "")
                if region_id not in REGION_BY_ID:
                    raise ValueError("공공 알림의 regionId가 유효하지 않습니다.")
                issued_at = str(item.get("issuedAt") or now())
                parse_time(issued_at)
                expires_at = item.get("expiresAt")
                if expires_at:
                    parse_time(str(expires_at))
                severity = str(item.get("severity") or "INFO").upper()
                if severity not in {"INFO", "ADVISORY", "WARNING", "CRITICAL"}:
                    raise ValueError("공공 알림의 severity가 유효하지 않습니다.")
                source = str(item.get("source") or "공공데이터")[:60]
                source_id = str(item.get("sourceId") or item.get("id") or "")
                if not source_id:
                    raise ValueError("공공 알림의 sourceId가 필요합니다.")
                alert_id = f"{source}:{source_id}"
                alert = {
                    "id": alert_id,
                    "sourceId": source_id,
                    "source": source,
                    "regionId": region_id,
                    "type": str(item.get("type") or "DISASTER")[:40],
                    "severity": severity,
                    "title": str(item.get("title") or "재난 안전 알림")[:120],
                    "message": str(item.get("message") or "")[:1000],
                    "issuedAt": issued_at,
                    "expiresAt": str(expires_at) if expires_at else None,
                    "sourceUrl": str(item.get("sourceUrl") or "")[:500],
                    "syncedAt": now(),
                }
                self.public_alerts[alert_id] = alert
                normalized.append(dict(alert))
                if (
                    self.notifier
                    and severity in {"WARNING", "CRITICAL"}
                ):
                    self.notifier.enqueue(
                        {
                            "id": alert_id,
                            "type": "PUBLIC_ALERT",
                            "title": alert["title"],
                            "severity": severity,
                            "regionId": region_id,
                            "message": alert["message"],
                            "source": source,
                            "createdAt": issued_at,
                        }
                    )
            if normalized:
                self.public_alert_status = {
                    "connected": True,
                    "message": f"공공데이터 {len(normalized)}건 동기화",
                }
            self._publish("public-alerts", {"count": len(normalized)})
            self._persist(force=True)
        return normalized

    def set_public_alert_status(self, status: dict) -> None:
        with self.lock:
            self.public_alert_status = {
                "connected": bool(status.get("connected")),
                "message": str(status.get("message") or "공공데이터 상태 미확인")[:300],
            }
            self._publish("public-alert-status", dict(self.public_alert_status))

    def _region_summaries(self) -> list[dict]:
        stats = {
            region["id"]: {
                "total": 0,
                "online": 0,
                "danger": 0,
                "sos": 0,
                "publicAlerts": 0,
                "publicSeverity": "INFO",
            }
            for region in REGIONS
        }
        for client in self.clients.values():
            region_stats = stats.get(client.get("regionId"))
            if not region_stats:
                continue
            region_stats["total"] += 1
            region_stats["online"] += client["connectionStatus"] == "ONLINE"
            region_stats["danger"] += client["dangerState"] == "DANGER"
        for event in self.sos_events.values():
            if event["status"] not in {"OPEN", "ACKNOWLEDGED", "DISPATCHED"}:
                continue
            client = self.clients.get(event["clientId"])
            if client and client.get("regionId") in stats:
                stats[client["regionId"]]["sos"] += 1
        severity_rank = {"INFO": 0, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 3}
        for alert in self.active_public_alerts():
            region_stats = stats[alert["regionId"]]
            region_stats["publicAlerts"] += 1
            if severity_rank[alert["severity"]] > severity_rank[region_stats["publicSeverity"]]:
                region_stats["publicSeverity"] = alert["severity"]
        return [{**region, **stats[region["id"]]} for region in REGIONS]

    def _expire_stale_clients(self) -> None:
        deadline = datetime.now(timezone.utc) - timedelta(seconds=self.client_timeout_seconds)
        changed = False
        for client in self.clients.values():
            last_seen = client.get("lastSeenAt") or client.get("updatedAt")
            if (
                client["connectionStatus"] == "ONLINE"
                and last_seen
                and parse_time(last_seen) < deadline
            ):
                client["connectionStatus"] = "OFFLINE"
                client.setdefault("warnings", {})["signalLost"] = True
                event = self._log("TIMEOUT", f"{client['name']} 응답 시간 초과", client["id"], "WARNING")
                self._publish("state", {"event": event, "clientId": client["id"]})
                changed = True
        if changed:
            self._persist(force=True)

    def route(self, client_id: str) -> list[dict]:
        with self.lock:
            self._require_client(client_id)
            return list(self.routes.get(client_id, []))

    def client(self, client_id: str) -> dict:
        with self.lock:
            return dict(self._require_client(client_id))

    def client_for_user(self, user_id: str) -> Optional[dict]:
        with self.lock:
            client_id = self.client_by_user.get(user_id)
            return dict(self.clients[client_id]) if client_id else None

    def sync_client_profile(self, client_id: str, user: dict) -> dict:
        with self.lock:
            client = self._require_client(client_id)
            client.update(
                {
                    "name": user["displayName"],
                    "regionId": user["regionId"],
                    "birthDate": user.get("birthDate"),
                    "gender": user.get("gender", "UNDISCLOSED"),
                }
            )
            self._rebuild_indexes()
            self._publish("state", {"clientId": client_id})
            self._persist(force=True)
            return dict(client)

    def remove_client_for_user(self, user_id: str) -> Optional[dict]:
        with self.lock:
            client_id = self.client_by_user.get(user_id)
            if not client_id:
                return None
            client = self.clients.pop(client_id)
            self.routes.pop(client_id, None)
            self.sos_events = {
                event_id: event
                for event_id, event in self.sos_events.items()
                if event.get("clientId") != client_id
            }
            self.timeline = [
                event
                for event in self.timeline
                if event.get("clientId") != client_id
            ]
            for group in self.groups.values():
                group["memberIds"] = [
                    item for item in group.get("memberIds", []) if item != client_id
                ]
            self._rebuild_indexes()
            event = self._log("MEMBER_DELETE", f"{client['name']} 회원 삭제")
            self._publish("state", {"event": event, "clientId": client_id})
            self._persist(force=True)
            return dict(client)

    def prune_orphan_clients(self, valid_user_ids: set[str]) -> list[str]:
        with self.lock:
            orphan_ids = [
                client_id
                for client_id, client in self.clients.items()
                if not client.get("userId")
                or client.get("userId") not in valid_user_ids
            ]
            if not orphan_ids:
                return []
            orphan_set = set(orphan_ids)
            for client_id in orphan_ids:
                self.clients.pop(client_id, None)
                self.routes.pop(client_id, None)
            for group in self.groups.values():
                group["memberIds"] = [
                    item
                    for item in group.get("memberIds", [])
                    if item not in orphan_set
                ]
            self.sos_events = {
                event_id: event
                for event_id, event in self.sos_events.items()
                if event.get("clientId") not in orphan_set
            }
            self.timeline = [
                event
                for event in self.timeline
                if event.get("clientId") not in orphan_set
            ]
            self._rebuild_indexes()
            self._persist(force=True)
            return orphan_ids

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=20)
        with self.lock:
            self.subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def _require_client(self, client_id: str) -> dict:
        client = self.clients.get(client_id)
        if not client:
            raise KeyError("사용자를 찾을 수 없습니다.")
        return client


NOTIFIER = WebhookNotifier.from_environment()
REPOSITORY = SQLiteStateRepository(DATABASE_PATH)
STORE = MonitoringStore(REPOSITORY, notifier=NOTIFIER)
AUTH = AuthRepository(DATABASE_PATH)
STORE.prune_orphan_clients(AUTH.member_ids())
PUBLIC_DATA_SYNC = PublicDataSynchronizer.from_environment(
    STORE.upsert_public_alerts, STORE.set_public_alert_status
)
GEOCODER = ReverseGeocoder.from_environment()
KNOWLEDGE_BASE = DisasterKnowledgeBase(ROOT / "disaster_docs")


class Handler(BaseHTTPRequestHandler):
    server_version = "RTLS/1.0"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/":
                return self._redirect("/monitor")
            if path == "/monitor":
                return self._static("monitor.html")
            if path == "/members":
                return self._static("members.html")
            if path == "/app":
                return self._static("app.html")
            if path.startswith("/static/"):
                return self._static(path.removeprefix("/static/"))
            if path == "/api/regions":
                return self._json({"regions": REGIONS})
            if path == "/api/safety-guides":
                self._user()
                return self._json({"guides": SAFETY_GUIDES})
            if path == "/api/disaster-knowledge":
                self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                return self._json(
                    {
                        "documents": len(KNOWLEDGE_BASE.documents),
                        "sources": sorted(
                            {
                                document["source"]
                                for document in KNOWLEDGE_BASE.documents
                                if document["source"]
                            }
                        ),
                    }
                )
            if path == "/api/auth/me":
                return self._json({"user": self._user()})
            if path == "/api/operators":
                self._user({"NATIONAL_ADMIN"})
                return self._json({"operators": AUTH.list_operators()})
            if path == "/api/guardians":
                user = self._user({"USER"})
                return self._json(
                    {"guardians": AUTH.guardians_for_user(user["id"])}
                )
            if path == "/api/guardian/wards":
                user = self._user({"GUARDIAN"})
                active_sos_by_client = {
                    event.get("clientId"): event
                    for event in STORE.sos_events.values()
                    if event.get("status")
                    in {"OPEN", "ACKNOWLEDGED", "DISPATCHED"}
                }
                wards = []
                for ward in AUTH.wards_for_guardian(user["id"]):
                    client = STORE.client_for_user(ward["id"])
                    wards.append(
                        {
                            "user": ward,
                            "client": client,
                            "openSos": active_sos_by_client.get(
                                (client or {}).get("id")
                            ),
                        }
                    )
                return self._json({"wards": wards})
            if path == "/api/members":
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                region_id = query.get("region", [None])[0]
                region_id = self._authorized_region(user, region_id)
                members = AUTH.list_members(region_id)
                clients = {
                    client["userId"]: client
                    for client in STORE.snapshot(region_id)["clients"]
                    if client.get("userId")
                }
                return self._json(
                    {
                        "members": [
                            {
                                **member,
                                "connectionStatus": clients.get(
                                    member["id"], {}
                                ).get("connectionStatus", "OFFLINE"),
                                "clientId": clients.get(member["id"], {}).get("id"),
                            }
                            for member in members
                        ]
                    }
                )
            if path == "/api/state":
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                region_id = query.get("region", [None])[0]
                region_id = self._authorized_region(user, region_id)
                state = STORE.snapshot(region_id)
                if user["role"] == "REGIONAL_OPERATOR":
                    state["regions"] = [
                        region
                        for region in state["regions"]
                        if region["id"] == user["regionId"]
                    ]
                    state["groups"] = [
                        group
                        for group in state["groups"]
                        if group.get("regionId") == user["regionId"]
                    ]
                return self._json(state)
            if path == "/api/events":
                token = query.get("token", [""])[0]
                user = self._user(
                    {"NATIONAL_ADMIN", "REGIONAL_OPERATOR"}, token=token
                )
                return self._events(user)
            match = re.fullmatch(r"/api/clients/([^/]+)/route", path)
            if match:
                user = self._user(
                    {"USER", "NATIONAL_ADMIN", "REGIONAL_OPERATOR"}
                )
                client_id = match.group(1)
                self._authorize_client(user, client_id)
                return self._json({"route": STORE.route(client_id)})
            match = re.fullmatch(r"/api/clients/([^/]+)/(analytics|facilities)", path)
            if match:
                user = self._user(
                    {"NATIONAL_ADMIN", "REGIONAL_OPERATOR"}
                )
                client_id, resource = match.groups()
                self._authorize_client(user, client_id)
                if resource == "analytics":
                    return self._json({"analytics": STORE.client_analytics(client_id)})
                return self._json({"facilities": STORE.nearby_facilities(client_id)})
            self._error(HTTPStatus.NOT_FOUND, "페이지를 찾을 수 없습니다.")
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except AuthorizationError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, TypeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc).strip("'"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/auth/signup":
                requested_role = str(payload.get("role") or "USER").upper()
                if requested_role not in {"USER", "GUARDIAN"}:
                    raise ValueError("일반 사용자 또는 보호자 계정만 가입할 수 있습니다.")
                user = AUTH.create_user(
                    payload.get("username", ""),
                    payload.get("password", ""),
                    payload.get("displayName", ""),
                    payload.get("regionId", ""),
                    role=requested_role,
                    birth_date=payload.get("birthDate"),
                    gender=payload.get("gender", "UNDISCLOSED"),
                )
                session = AUTH.login(
                    payload.get("username", ""), payload.get("password", "")
                )
                return self._json(
                    {"user": user, **session}, HTTPStatus.CREATED
                )
            if path == "/api/auth/login":
                return self._json(
                    AUTH.login(
                        payload.get("username", ""), payload.get("password", "")
                    )
                )
            if path == "/api/auth/logout":
                AUTH.logout(self._token())
                return self._json({"ok": True})
            if path == "/api/disaster-knowledge/search":
                self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                query = str(payload.get("query") or "").strip()
                if len(query) < 2:
                    raise ValueError("검색어를 2자 이상 입력해 주세요.")
                return self._json(KNOWLEDGE_BASE.answer(query, payload.get("limit", 3)))
            if path == "/api/operators":
                self._user({"NATIONAL_ADMIN"})
                operator = AUTH.create_user(
                    payload.get("username", ""),
                    payload.get("password", ""),
                    payload.get("displayName", ""),
                    payload.get("regionId", ""),
                    role="REGIONAL_OPERATOR",
                )
                STORE.audit(
                    self._user({"NATIONAL_ADMIN"}),
                    "OPERATOR_CREATE",
                    operator["id"],
                    operator["displayName"],
                    operator["regionId"],
                )
                return self._json({"operator": operator}, HTTPStatus.CREATED)
            if path == "/api/danger-areas":
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                requested_region = str(payload.get("regionId") or "")
                if (
                    user["role"] == "REGIONAL_OPERATOR"
                    and requested_region != user["regionId"]
                ):
                    raise AuthorizationError("담당 지역에만 위험구역을 생성할 수 있습니다.")
                area = STORE.create_danger_area(payload)
                STORE.audit(
                    user, "DANGER_AREA_CREATE", area["id"], area["name"], area["regionId"]
                )
                return self._json({"dangerArea": area}, HTTPStatus.CREATED)
            if path == "/api/groups":
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                if user["role"] == "REGIONAL_OPERATOR":
                    payload["regionId"] = user["regionId"]
                group = STORE.create_group(payload)
                STORE.audit(
                    user, "GROUP_CREATE", group["id"], group["name"], group.get("regionId")
                )
                return self._json({"group": group}, HTTPStatus.CREATED)
            match = re.fullmatch(r"/api/groups/([^/]+)/members", path)
            if match:
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                group = STORE.groups.get(match.group(1))
                if not group:
                    raise KeyError("그룹을 찾을 수 없습니다.")
                if (
                    user["role"] == "REGIONAL_OPERATOR"
                    and group.get("regionId") != user["regionId"]
                ):
                    raise AuthorizationError("담당 지역 그룹만 관리할 수 있습니다.")
                for client_id in payload.get("memberIds", []):
                    self._authorize_client(user, client_id)
                group = STORE.set_group_members(
                    match.group(1), payload.get("memberIds", [])
                )
                STORE.audit(
                    user, "GROUP_MEMBERS_UPDATE", group["id"], group["name"], group.get("regionId")
                )
                return self._json({"group": group})
            if path == "/api/guardians/link":
                user = self._user({"USER"})
                guardian = AUTH.link_guardian(
                    user["id"], payload.get("guardianUsername", "")
                )
                return self._json({"guardian": guardian}, HTTPStatus.CREATED)
            match = re.fullmatch(r"/api/members/([^/]+)", path)
            if match:
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                member = AUTH.get_user(match.group(1))
                self._authorize_member(user, member)
                requested_region = str(payload.get("regionId") or "")
                if (
                    user["role"] == "REGIONAL_OPERATOR"
                    and requested_region != user["regionId"]
                ):
                    raise AuthorizationError(
                        "회원을 담당 지역 밖으로 이동할 수 없습니다."
                    )
                member = AUTH.update_member(
                    match.group(1),
                    payload.get("displayName", ""),
                    requested_region,
                    payload.get("birthDate"),
                    payload.get("gender", "UNDISCLOSED"),
                )
                client = STORE.client_for_user(member["id"])
                if client:
                    STORE.sync_client_profile(client["id"], member)
                STORE.audit(
                    user, "MEMBER_UPDATE", member["id"], member["displayName"], member["regionId"]
                )
                return self._json({"member": member})
            if path == "/api/public-alerts":
                self._user({"NATIONAL_ADMIN"})
                alerts = STORE.upsert_public_alerts(payload.get("alerts", []))
                return self._json(
                    {"alerts": alerts, "count": len(alerts)},
                    HTTPStatus.CREATED,
                )
            if path == "/api/public-alerts/sync":
                self._user({"NATIONAL_ADMIN"})
                count = PUBLIC_DATA_SYNC.sync_once()
                return self._json(
                    {
                        "count": count,
                        "status": dict(STORE.public_alert_status),
                    }
                )
            if path == "/api/clients":
                user = self._user({"USER"})
                existing = STORE.client_for_user(user["id"])
                if existing:
                    STORE.sync_client_profile(existing["id"], user)
                    client = STORE.heartbeat(existing["id"])
                    return self._json({"client": client})
                payload.update(
                    {
                        "name": user["displayName"],
                        "userId": user["id"],
                        "regionId": user["regionId"],
                        "birthDate": user.get("birthDate"),
                        "gender": user.get("gender", "UNDISCLOSED"),
                    }
                )
                return self._json(
                    {"client": STORE.register(payload)}, HTTPStatus.CREATED
                )
            match = re.fullmatch(r"/api/clients/([^/]+)/(location|sos|heartbeat|disconnect)", path)
            if match:
                client_id, action = match.groups()
                user = self._user({"USER"})
                self._authorize_client(user, client_id)
                if action == "location":
                    return self._json({"client": STORE.update_location(client_id, payload)})
                if action == "sos":
                    return self._json({"sos": STORE.create_sos(client_id, payload)}, HTTPStatus.CREATED)
                if action == "heartbeat":
                    return self._json({"client": STORE.heartbeat(client_id, payload)})
                return self._json({"client": STORE.disconnect(client_id)})
            match = re.fullmatch(r"/api/clients/([^/]+)/address", path)
            if match:
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                client_id = match.group(1)
                self._authorize_client(user, client_id)
                client = STORE.client(client_id)
                location = client.get("location")
                if not location:
                    raise ValueError("위치를 먼저 전송해 주세요.")
                lat, lng = location["lat"], location["lng"]
                result = GEOCODER.reverse(lat, lng)
                return self._json(
                    {
                        "client": STORE.set_location_address(
                            client_id, result, lat, lng
                        )
                    }
                )
            match = re.fullmatch(r"/api/sos/([^/]+)", path)
            if match:
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                event = STORE.sos_events.get(match.group(1))
                if not event:
                    raise KeyError("SOS 이벤트를 찾을 수 없습니다.")
                self._authorize_client(user, event["clientId"])
                event = STORE.update_sos(
                    match.group(1),
                    str(payload.get("status", "")),
                    user["displayName"],
                    str(payload.get("note", "")),
                )
                STORE.audit(
                    user,
                    "SOS_STATUS_UPDATE",
                    event["id"],
                    event["status"],
                    STORE.client(event["clientId"]).get("regionId"),
                )
                return self._json({"sos": event})
            self._error(HTTPStatus.NOT_FOUND, "API를 찾을 수 없습니다.")
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except AuthorizationError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, TypeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc).strip("'"))

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            match = re.fullmatch(r"/api/guardians/([^/]+)", path)
            if match:
                user = self._user({"USER"})
                AUTH.unlink_guardian(user["id"], match.group(1))
                return self._json({"ok": True})
            match = re.fullmatch(r"/api/danger-areas/([^/]+)", path)
            if match:
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                area = next(
                    (
                        item
                        for item in STORE.danger_areas
                        if item["id"] == match.group(1)
                    ),
                    None,
                )
                if not area:
                    raise KeyError("위험구역을 찾을 수 없습니다.")
                if (
                    user["role"] == "REGIONAL_OPERATOR"
                    and area.get("regionId") != user["regionId"]
                ):
                    raise AuthorizationError("담당 지역 위험구역만 삭제할 수 있습니다.")
                deleted = STORE.delete_danger_area(match.group(1))
                STORE.audit(
                    user, "DANGER_AREA_DELETE", deleted["id"], deleted["name"], deleted["regionId"]
                )
                return self._json({"deleted": deleted})
            match = re.fullmatch(r"/api/groups/([^/]+)", path)
            if match:
                user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
                group = STORE.groups.get(match.group(1))
                if not group:
                    raise KeyError("그룹을 찾을 수 없습니다.")
                if (
                    user["role"] == "REGIONAL_OPERATOR"
                    and group.get("regionId") != user["regionId"]
                ):
                    raise AuthorizationError("담당 지역 그룹만 삭제할 수 있습니다.")
                deleted = STORE.delete_group(match.group(1))
                STORE.audit(
                    user, "GROUP_DELETE", deleted["id"], deleted["name"], deleted.get("regionId")
                )
                return self._json({"deleted": deleted})
            match = re.fullmatch(r"/api/members/([^/]+)", path)
            if not match:
                return self._error(HTTPStatus.NOT_FOUND, "API를 찾을 수 없습니다.")
            user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
            member = AUTH.get_user(match.group(1))
            self._authorize_member(user, member)
            deleted = AUTH.delete_member(match.group(1))
            STORE.remove_client_for_user(deleted["id"])
            STORE.audit(
                user, "MEMBER_DELETE", deleted["id"], deleted["displayName"], deleted["regionId"]
            )
            self._json({"deleted": deleted})
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except AuthorizationError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc).strip("'"))

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("요청 데이터가 너무 큽니다.")
        if not length:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON 객체 형식의 요청이 필요합니다.")
        return payload

    def _token(self) -> str:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header.removeprefix("Bearer ").strip()
        return ""

    def _user(self, roles: Optional[set[str]] = None, token: str = "") -> dict:
        user = AUTH.authenticate(token or self._token())
        if roles and user["role"] not in roles:
            raise AuthorizationError("이 기능을 사용할 권한이 없습니다.")
        return user

    def _authorized_region(
        self, user: dict, requested_region: Optional[str]
    ) -> Optional[str]:
        if user["role"] == "REGIONAL_OPERATOR":
            return user["regionId"]
        if requested_region and requested_region not in REGION_BY_ID:
            raise ValueError("유효하지 않은 지역입니다.")
        return requested_region

    def _authorize_client(self, user: dict, client_id: str) -> None:
        client = STORE.client(client_id)
        if user["role"] == "USER" and client.get("userId") != user["id"]:
            raise AuthorizationError("다른 사용자의 단말에는 접근할 수 없습니다.")
        if (
            user["role"] == "REGIONAL_OPERATOR"
            and client.get("regionId") != user["regionId"]
        ):
            raise AuthorizationError("담당 지역 밖의 단말에는 접근할 수 없습니다.")

    def _authorize_member(self, user: dict, member: Optional[dict]) -> None:
        if not member or member["role"] != "USER":
            raise KeyError("회원을 찾을 수 없습니다.")
        if (
            user["role"] == "REGIONAL_OPERATOR"
            and member.get("regionId") != user["regionId"]
        ):
            raise AuthorizationError("담당 지역 밖의 회원은 관리할 수 없습니다.")

    def _json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _redirect(self, target: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", target)
        self.end_headers()

    def _static(self, relative: str) -> None:
        target = (STATIC / relative).resolve()
        if STATIC not in target.parents or not target.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "파일을 찾을 수 없습니다.")
        body = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _events(self, user: dict) -> None:
        subscriber = STORE.subscribe()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b"event: connected\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    message = subscriber.get(timeout=15)
                    data = json.dumps(message, ensure_ascii=False)
                    packet = f"event: update\ndata: {data}\n\n".encode("utf-8")
                except queue.Empty:
                    packet = b": heartbeat\n\n"
                self.wfile.write(packet)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            STORE.unsubscribe(subscriber)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def run(host: str = HOST, port: int = PORT) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    NOTIFIER.start()
    PUBLIC_DATA_SYNC.start()
    if not PUBLIC_DATA_SYNC.enabled_providers():
        STORE.set_public_alert_status(
            {
                "connected": False,
                "message": "공공데이터 API URL 또는 키 미설정",
            }
        )
    local_host = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            local_host = probe.getsockname()[0]
    except OSError:
        pass
    print(f"RTLS server running on {host}:{port}")
    print(f"Monitoring dashboard: http://127.0.0.1:{port}/monitor")
    print(f"Client app (Mac):     http://127.0.0.1:{port}/app")
    if host in {"0.0.0.0", ""}:
        print(f"Client app (phone):   http://{local_host}:{port}/app")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        PUBLIC_DATA_SYNC.stop()
        NOTIFIER.stop()
        STORE.flush()
        server.server_close()


if __name__ == "__main__":
    run()
