"""Asynchronous signed webhook notifications for external automation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import threading
from typing import Optional
from urllib import request


NOTIFIABLE_TYPES = {
    "SOS",
    "DANGER_ENTER",
    "TIMEOUT",
    "LOW_BATTERY",
    "IMMOBILE",
    "PUBLIC_ALERT",
}


class WebhookNotifier:
    def __init__(
        self,
        url: str = "",
        secret: str = "",
        timeout: float = 5.0,
        queue_size: int = 100,
    ) -> None:
        self.url = str(url or "").strip()
        self.secret = str(secret or "")
        self.timeout = max(1.0, float(timeout))
        self.events: queue.Queue = queue.Queue(maxsize=max(1, queue_size))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_error = ""
        self.delivered = 0
        self.dropped = 0

    @classmethod
    def from_environment(cls) -> "WebhookNotifier":
        return cls(
            os.environ.get("RTLS_N8N_WEBHOOK_URL", ""),
            os.environ.get("RTLS_N8N_WEBHOOK_SECRET", ""),
            float(os.environ.get("RTLS_N8N_WEBHOOK_TIMEOUT", "5")),
        )

    @property
    def enabled(self) -> bool:
        return self.url.startswith(("http://", "https://"))

    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self._thread = threading.Thread(
            target=self._run, name="rtls-webhook", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.timeout + 1)
        self._thread = None

    def enqueue(self, event: dict) -> bool:
        if not self.enabled or event.get("type") not in NOTIFIABLE_TYPES:
            return False
        try:
            self.events.put_nowait(dict(event))
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "delivered": self.delivered,
            "dropped": self.dropped,
            "lastError": self.last_error,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.events.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._deliver(event)
                self.delivered += 1
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)[:300]
            finally:
                self.events.task_done()

    def _deliver(self, event: dict) -> None:
        body = json.dumps(
            {"version": 1, "event": event},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "RTLS-Monitoring/1.0",
        }
        if self.secret:
            signature = hmac.new(
                self.secret.encode("utf-8"), body, hashlib.sha256
            ).hexdigest()
            headers["X-RTLS-Signature"] = f"sha256={signature}"
        webhook_request = request.Request(
            self.url, data=body, headers=headers, method="POST"
        )
        with request.urlopen(webhook_request, timeout=self.timeout) as response:
            if response.status >= 300:
                raise RuntimeError(f"Webhook HTTP {response.status}")
