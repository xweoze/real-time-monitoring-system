import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from notifications import WebhookNotifier


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class WebhookNotifierTest(unittest.TestCase):
    def test_disabled_notifier_does_not_queue(self):
        notifier = WebhookNotifier()
        self.assertFalse(notifier.enabled)
        self.assertFalse(notifier.enqueue({"type": "SOS"}))

    def test_only_alert_events_are_queued(self):
        notifier = WebhookNotifier("https://example.test/webhook")
        self.assertFalse(notifier.enqueue({"type": "CONNECT"}))
        self.assertTrue(notifier.enqueue({"type": "SOS", "id": "SOS-1"}))
        self.assertEqual(notifier.events.qsize(), 1)

    def test_delivery_adds_hmac_signature(self):
        notifier = WebhookNotifier(
            "https://example.test/webhook", secret="shared-secret"
        )
        event = {"type": "SOS", "id": "SOS-1", "title": "긴급 요청"}
        captured = {}

        def fake_urlopen(webhook_request, timeout):
            captured["body"] = webhook_request.data
            captured["signature"] = webhook_request.headers["X-rtls-signature"]
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("notifications.request.urlopen", side_effect=fake_urlopen):
            notifier._deliver(event)

        expected = hmac.new(
            b"shared-secret", captured["body"], hashlib.sha256
        ).hexdigest()
        payload = json.loads(captured["body"].decode("utf-8"))
        self.assertEqual(captured["signature"], f"sha256={expected}")
        self.assertEqual(payload["event"]["id"], "SOS-1")
        self.assertEqual(captured["timeout"], 5.0)


if __name__ == "__main__":
    unittest.main()
