#!/usr/bin/env python3
"""Real-time vulnerable population monitoring system MVP."""

from __future__ import annotations

import json
import math
import mimetypes
import queue
import re
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HOST = "127.0.0.1"
PORT = 8080


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


class MonitoringStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.clients: dict[str, dict] = {}
        self.routes: dict[str, list[dict]] = {}
        self.sos_events: dict[str, dict] = {}
        self.timeline: list[dict] = []
        self.subscribers: list[queue.Queue] = []
        self.sequence = 0
        self.danger_areas = [
            {
                "id": "AREA-01",
                "name": "강남역 침수 위험 구역",
                "lat": 37.4979,
                "lng": 127.0276,
                "radius": 320,
                "severity": 5,
            },
            {
                "id": "AREA-02",
                "name": "한강 범람 주의 구역",
                "lat": 37.5208,
                "lng": 126.9931,
                "radius": 420,
                "severity": 4,
            },
        ]

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
                "connectionStatus": "ONLINE",
                "state": "NORMAL",
                "dangerState": "SAFE",
                "dangerArea": None,
                "location": None,
                "connectedAt": now(),
                "updatedAt": now(),
            }
            self.clients[client_id] = client
            self.routes[client_id] = []
            event = self._log("CONNECT", f"{client['name']} 접속", client_id)
            self._publish("state", {"event": event})
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
            return dict(event)

    def update_sos(self, event_id: str, status: str, operator: str) -> dict:
        if status not in {"ACKNOWLEDGED", "RESOLVED", "CANCELLED"}:
            raise ValueError("지원하지 않는 SOS 상태입니다.")
        with self.lock:
            event = self.sos_events.get(event_id)
            if not event:
                raise KeyError("SOS 이벤트를 찾을 수 없습니다.")
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
            return dict(event)

    def disconnect(self, client_id: str) -> dict:
        with self.lock:
            client = self._require_client(client_id)
            client["connectionStatus"] = "OFFLINE"
            client["updatedAt"] = now()
            event = self._log("DISCONNECT", f"{client['name']} 접속 종료", client_id)
            self._publish("state", {"event": event, "clientId": client_id})
            return dict(client)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "clients": list(self.clients.values()),
                "dangerAreas": self.danger_areas,
                "sosEvents": sorted(
                    self.sos_events.values(), key=lambda item: item["createdAt"], reverse=True
                ),
                "timeline": self.timeline,
                "serverTime": now(),
            }

    def route(self, client_id: str) -> list[dict]:
        with self.lock:
            self._require_client(client_id)
            return list(self.routes.get(client_id, []))

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


STORE = MonitoringStore()


class Handler(BaseHTTPRequestHandler):
    server_version = "RTLS/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            return self._redirect("/monitor")
        if path == "/monitor":
            return self._static("monitor.html")
        if path == "/app":
            return self._static("app.html")
        if path.startswith("/static/"):
            return self._static(path.removeprefix("/static/"))
        if path == "/api/state":
            return self._json(STORE.snapshot())
        if path == "/api/events":
            return self._events()
        match = re.fullmatch(r"/api/clients/([^/]+)/route", path)
        if match:
            return self._json({"route": STORE.route(match.group(1))})
        self._error(HTTPStatus.NOT_FOUND, "페이지를 찾을 수 없습니다.")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/clients":
                return self._json({"client": STORE.register(payload)}, HTTPStatus.CREATED)
            match = re.fullmatch(r"/api/clients/([^/]+)/(location|sos|disconnect)", path)
            if match:
                client_id, action = match.groups()
                if action == "location":
                    return self._json({"client": STORE.update_location(client_id, payload)})
                if action == "sos":
                    return self._json({"sos": STORE.create_sos(client_id, payload)}, HTTPStatus.CREATED)
                return self._json({"client": STORE.disconnect(client_id)})
            match = re.fullmatch(r"/api/sos/([^/]+)", path)
            if match:
                event = STORE.update_sos(
                    match.group(1), str(payload.get("status", "")), str(payload.get("operator", ""))
                )
                return self._json({"sos": event})
            self._error(HTTPStatus.NOT_FOUND, "API를 찾을 수 없습니다.")
        except (ValueError, TypeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc).strip("'"))

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("요청 데이터가 너무 큽니다.")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

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

    def _events(self) -> None:
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
    print(f"RTLS server running: http://{host}:{port}")
    print(f"Monitoring dashboard: http://{host}:{port}/monitor")
    print(f"Client app:          http://{host}:{port}/app")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
