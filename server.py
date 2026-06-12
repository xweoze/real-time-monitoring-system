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
from public_data import PublicDataSynchronizer
from regions import REGIONS, REGION_BY_ID


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HOST = os.environ.get("RTLS_HOST", "0.0.0.0")
PORT = 8080
DATA_DIR = ROOT / "data"
DATABASE_PATH = Path(os.environ.get("RTLS_DATABASE", DATA_DIR / "rtls.db"))
CLIENT_TIMEOUT_SECONDS = 45
PERSIST_DEBOUNCE_SECONDS = 3.0


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
    ) -> None:
        self.lock = threading.RLock()
        self.repository = repository
        self.client_timeout_seconds = client_timeout_seconds
        self.persist_debounce_seconds = persist_debounce_seconds
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
        self.sequence = int(state.get("sequence", 0))
        for client in self.clients.values():
            client["connectionStatus"] = "OFFLINE"
            client.setdefault("regionId", "KR-11")
            client.setdefault("userId", None)
            client.setdefault("birthDate", None)
            client.setdefault("gender", "UNDISCLOSED")
        self._rebuild_indexes()

    def _state_payload(self) -> dict:
        return {
            "clients": self.clients,
            "routes": self.routes,
            "sosEvents": self.sos_events,
            "publicAlerts": self.public_alerts,
            "timeline": self.timeline,
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
        return event

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
            previous = client["dangerState"]
            danger_area = None
            for area in self.danger_areas:
                if distance_m(lat, lng, area["lat"], area["lng"]) <= area["radius"]:
                    if danger_area is None or area["severity"] > danger_area["severity"]:
                        danger_area = area

            point = {
                "lat": lat,
                "lng": lng,
                "accuracy": accuracy,
                "capturedAt": str(payload.get("capturedAt") or now()),
            }
            client.update(
                {
                    "location": point,
                    "state": str(payload.get("state") or "NORMAL")[:20],
                    "dangerState": "DANGER" if danger_area else "SAFE",
                    "dangerArea": dict(danger_area) if danger_area else None,
                    "connectionStatus": "ONLINE",
                    "updatedAt": now(),
                    "lastSeenAt": now(),
                }
            )
            self.routes[client_id].append(point)
            self.routes[client_id] = self.routes[client_id][-500:]

            if previous != client["dangerState"]:
                if danger_area:
                    event = self._log(
                        "DANGER",
                        f"{danger_area['name']} 진입 감지",
                        client_id,
                        "CRITICAL" if danger_area["severity"] >= 5 else "WARNING",
                    )
                else:
                    event = self._log("SAFE", "안전 구역으로 이동", client_id)
            else:
                event = None
            self._publish("state", {"event": event, "clientId": client_id})
            self._persist(force=event is not None)
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
                "resolvedAt": None,
                "operator": None,
            }
            self.sos_events[event_id] = event
            log = self._log("SOS", f"{client['name']} 긴급 구조 요청", client_id, "CRITICAL")
            self._publish("state", {"event": log, "sosId": event_id})
            self._persist(force=True)
            return dict(event)

    def update_sos(self, event_id: str, status: str, operator: str) -> dict:
        if status not in {"ACKNOWLEDGED", "RESOLVED", "CANCELLED"}:
            raise ValueError("지원하지 않는 SOS 상태입니다.")
        with self.lock:
            event = self.sos_events.get(event_id)
            if not event:
                raise KeyError("SOS 이벤트를 찾을 수 없습니다.")
            allowed = {
                "OPEN": {"ACKNOWLEDGED", "CANCELLED"},
                "ACKNOWLEDGED": {"RESOLVED", "CANCELLED"},
                "RESOLVED": set(),
                "CANCELLED": set(),
            }
            if status not in allowed.get(event["status"], set()):
                raise ValueError(f"{event['status']} 상태에서 {status}(으)로 변경할 수 없습니다.")
            event["status"] = status
            event["operator"] = operator[:30] or "관제 요원"
            if status == "ACKNOWLEDGED":
                event["acknowledgedAt"] = now()
                title = f"{event['id']} 구조 접수"
            elif status == "RESOLVED":
                event["resolvedAt"] = now()
                title = f"{event['id']} 구조 완료"
            else:
                title = f"{event['id']} 요청 취소"
            log = self._log("RESCUE", title, event["clientId"])
            self._publish("state", {"event": log, "sosId": event_id})
            self._persist(force=True)
            return dict(event)

    def heartbeat(self, client_id: str) -> dict:
        with self.lock:
            client = self._require_client(client_id)
            was_offline = client["connectionStatus"] == "OFFLINE"
            client["connectionStatus"] = "ONLINE"
            client["lastSeenAt"] = now()
            if was_offline:
                event = self._log("RECONNECT", f"{client['name']} 연결 복구", client_id)
                self._publish("state", {"event": event, "clientId": client_id})
                self._persist(force=True)
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
                "serverTime": now(),
            }

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
            if event["status"] not in {"OPEN", "ACKNOWLEDGED"}:
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


REPOSITORY = SQLiteStateRepository(DATABASE_PATH)
STORE = MonitoringStore(REPOSITORY)
AUTH = AuthRepository(DATABASE_PATH)
STORE.prune_orphan_clients(AUTH.member_ids())
PUBLIC_DATA_SYNC = PublicDataSynchronizer.from_environment(
    STORE.upsert_public_alerts, STORE.set_public_alert_status
)


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
            if path == "/api/auth/me":
                return self._json({"user": self._user()})
            if path == "/api/operators":
                self._user({"NATIONAL_ADMIN"})
                return self._json({"operators": AUTH.list_operators()})
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
                return self._json(state)
            if path == "/api/events":
                token = query.get("token", [""])[0]
                user = self._user(
                    {"NATIONAL_ADMIN", "REGIONAL_OPERATOR"}, token=token
                )
                return self._events(user)
            match = re.fullmatch(r"/api/clients/([^/]+)/route", path)
            if match:
                user = self._user()
                client_id = match.group(1)
                self._authorize_client(user, client_id)
                return self._json({"route": STORE.route(client_id)})
            self._error(HTTPStatus.NOT_FOUND, "페이지를 찾을 수 없습니다.")
        except AuthenticationError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except AuthorizationError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc).strip("'"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/auth/signup":
                user = AUTH.create_user(
                    payload.get("username", ""),
                    payload.get("password", ""),
                    payload.get("displayName", ""),
                    payload.get("regionId", ""),
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
            if path == "/api/operators":
                self._user({"NATIONAL_ADMIN"})
                operator = AUTH.create_user(
                    payload.get("username", ""),
                    payload.get("password", ""),
                    payload.get("displayName", ""),
                    payload.get("regionId", ""),
                    role="REGIONAL_OPERATOR",
                )
                return self._json({"operator": operator}, HTTPStatus.CREATED)
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
                    return self._json({"client": STORE.heartbeat(client_id)})
                return self._json({"client": STORE.disconnect(client_id)})
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
            match = re.fullmatch(r"/api/members/([^/]+)", path)
            if not match:
                return self._error(HTTPStatus.NOT_FOUND, "API를 찾을 수 없습니다.")
            user = self._user({"NATIONAL_ADMIN", "REGIONAL_OPERATOR"})
            member = AUTH.get_user(match.group(1))
            self._authorize_member(user, member)
            deleted = AUTH.delete_member(match.group(1))
            STORE.remove_client_for_user(deleted["id"])
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
        STORE.flush()
        server.server_close()


if __name__ == "__main__":
    run()
