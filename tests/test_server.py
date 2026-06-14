import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from server import MonitoringStore, SQLiteStateRepository, distance_m, point_in_polygon


class CountingRepository:
    def __init__(self):
        self.save_count = 0
        self.state = None

    def load(self):
        return self.state

    def save(self, state):
        self.save_count += 1
        self.state = state


class MonitoringStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = MonitoringStore()
        self.client = self.store.register({"name": "테스트 사용자"})

    def test_register_and_safe_location(self):
        updated = self.store.update_location(
            self.client["id"], {"lat": 37.512, "lng": 127.010, "accuracy": 5}
        )
        self.assertEqual(updated["dangerState"], "SAFE")
        self.assertEqual(len(self.store.route(self.client["id"])), 1)

    def test_location_address_is_stored(self):
        self.store.update_location(
            self.client["id"], {"lat": 37.5665, "lng": 126.9780}
        )

        updated = self.store.set_location_address(
            self.client["id"],
            {
                "address": "서울특별시 중구 세종대로 110",
                "provider": "kakao",
                "resolvedAt": "2026-06-13T09:00:00+00:00",
            },
        )

        self.assertEqual(
            updated["location"]["address"], "서울특별시 중구 세종대로 110"
        )
        self.assertEqual(updated["location"]["addressProvider"], "kakao")

    def test_stale_address_result_is_rejected(self):
        self.store.update_location(
            self.client["id"], {"lat": 37.5665, "lng": 126.9780}
        )
        self.store.update_location(
            self.client["id"], {"lat": 37.5700, "lng": 126.9800}
        )

        with self.assertRaises(ValueError):
            self.store.set_location_address(
                self.client["id"],
                {"address": "이전 위치", "provider": "test"},
                37.5665,
                126.9780,
            )

    def test_client_profile_is_stored_and_can_be_synced(self):
        client = self.store.register(
            {
                "name": "보호 대상",
                "userId": "U-PROFILE",
                "regionId": "KR-11",
                "birthDate": "2017-03-01",
                "gender": "FEMALE",
            }
        )

        synced = self.store.sync_client_profile(
            client["id"],
            {
                "displayName": "보호 대상 수정",
                "regionId": "KR-26",
                "birthDate": "2017-03-01",
                "gender": "FEMALE",
            },
        )

        self.assertEqual(synced["birthDate"], "2017-03-01")
        self.assertEqual(synced["gender"], "FEMALE")
        self.assertIn(client["id"], self.store.clients_by_region["KR-26"])
        self.assertNotIn(client["id"], self.store.clients_by_region["KR-11"])

    def test_member_client_can_be_removed_with_related_data(self):
        client = self.store.register(
            {"name": "삭제 회원", "userId": "U-DELETE", "regionId": "KR-11"}
        )
        self.store.update_location(
            client["id"], {"lat": 37.512, "lng": 127.010}
        )
        self.store.create_sos(client["id"], {"message": "삭제 전 SOS"})

        removed = self.store.remove_client_for_user("U-DELETE")

        self.assertEqual(removed["id"], client["id"])
        self.assertIsNone(self.store.client_for_user("U-DELETE"))
        self.assertNotIn(client["id"], self.store.routes)
        self.assertFalse(
            any(
                event.get("clientId") == client["id"]
                for event in self.store.sos_events.values()
            )
        )

    def test_orphan_clients_are_pruned(self):
        valid = self.store.register(
            {"name": "정상 회원", "userId": "U-VALID", "regionId": "KR-11"}
        )
        legacy = self.store.register(
            {"name": "과거 단말", "regionId": "KR-11"}
        )
        deleted = self.store.register(
            {"name": "삭제 회원", "userId": "U-DELETED", "regionId": "KR-26"}
        )

        removed = self.store.prune_orphan_clients({"U-VALID"})

        self.assertEqual(
            set(removed), {self.client["id"], legacy["id"], deleted["id"]}
        )
        self.assertEqual(
            [client["id"] for client in self.store.snapshot()["clients"]],
            [valid["id"]],
        )

    def test_danger_detection(self):
        updated = self.store.update_location(
            self.client["id"], {"lat": 37.4979, "lng": 127.0276, "accuracy": 3}
        )
        self.assertEqual(updated["dangerState"], "SAFE")
        self.assertIsNone(updated["dangerArea"])

    def test_sos_lifecycle(self):
        self.store.update_location(self.client["id"], {"lat": 37.512, "lng": 127.010})
        event = self.store.create_sos(self.client["id"], {"message": "도와주세요"})
        acknowledged = self.store.update_sos(
            event["id"], "ACKNOWLEDGED", "operator-1", "신고자 위치 확인"
        )
        dispatched = self.store.update_sos(
            event["id"], "DISPATCHED", "operator-1", "현장 담당자 출동"
        )
        seoul = next(
            region
            for region in self.store.snapshot()["regions"]
            if region["id"] == "KR-11"
        )
        resolved = self.store.update_sos(
            event["id"], "RESOLVED", "operator-1", "보호자 인계 완료"
        )
        self.assertEqual(acknowledged["status"], "ACKNOWLEDGED")
        self.assertIsNotNone(dispatched["dispatchedAt"])
        self.assertEqual(seoul["sos"], 1)
        self.assertIsNotNone(resolved["resolvedAt"])
        self.assertEqual(resolved["note"], "보호자 인계 완료")
        self.assertEqual(len(resolved["history"]), 3)
        self.assertEqual(resolved["history"][0]["operator"], "operator-1")

    def test_invalid_sos_transition(self):
        self.store.update_location(self.client["id"], {"lat": 37.512, "lng": 127.010})
        event = self.store.create_sos(self.client["id"], {})
        with self.assertRaises(ValueError):
            self.store.update_sos(event["id"], "RESOLVED", "operator-1")

    def test_sos_note_is_limited(self):
        self.store.update_location(self.client["id"], {"lat": 37.512, "lng": 127.010})
        event = self.store.create_sos(self.client["id"], {})
        updated = self.store.update_sos(
            event["id"], "ACKNOWLEDGED", "operator-1", "가" * 700
        )
        self.assertEqual(len(updated["note"]), 500)

    def test_legacy_sos_is_migrated_on_restore(self):
        repository = CountingRepository()
        repository.state = {
            "clients": {},
            "routes": {},
            "sosEvents": {
                "SOS-OLD": {
                    "id": "SOS-OLD",
                    "clientId": "C-OLD",
                    "clientName": "기존 사용자",
                    "status": "ACKNOWLEDGED",
                    "createdAt": "2026-06-01T00:00:00+00:00",
                    "acknowledgedAt": "2026-06-01T00:01:00+00:00",
                    "resolvedAt": None,
                    "operator": "기존 담당자",
                }
            },
        }

        restored = MonitoringStore(repository)
        event = restored.sos_events["SOS-OLD"]

        self.assertEqual(event["assignedAt"], event["acknowledgedAt"])
        self.assertIsNone(event["dispatchedAt"])
        self.assertEqual(event["history"], [])
        self.assertEqual(event["note"], "")

    def test_heartbeat_restores_offline_client(self):
        self.store.disconnect(self.client["id"])
        restored = self.store.heartbeat(self.client["id"])
        self.assertEqual(restored["connectionStatus"], "ONLINE")

    def test_stale_client_becomes_offline(self):
        self.store.clients[self.client["id"]]["lastSeenAt"] = (
            datetime.now(timezone.utc) - timedelta(seconds=60)
        ).isoformat()
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["clients"][0]["connectionStatus"], "OFFLINE")

    def test_sqlite_persistence(self):
        with TemporaryDirectory() as directory:
            repository = SQLiteStateRepository(Path(directory) / "state.db")
            store = MonitoringStore(repository)
            client = store.register({"name": "저장 사용자"})
            store.update_location(client["id"], {"lat": 37.512, "lng": 127.010})
            store.flush()

            restored = MonitoringStore(repository)
            self.assertEqual(restored.clients[client["id"]]["name"], "저장 사용자")
            self.assertEqual(restored.clients[client["id"]]["connectionStatus"], "OFFLINE")
            self.assertEqual(len(restored.route(client["id"])), 1)

    def test_invalid_coordinate(self):
        with self.assertRaises(ValueError):
            self.store.update_location(self.client["id"], {"lat": 100, "lng": 127})

    def test_distance(self):
        self.assertLess(distance_m(37.4979, 127.0276, 37.4979, 127.0276), 0.01)

    def test_snapshot_can_be_filtered_by_region(self):
        seoul = self.store.register({"name": "서울", "regionId": "KR-11"})
        busan = self.store.register({"name": "부산", "regionId": "KR-26"})

        snapshot = self.store.snapshot("KR-11")

        self.assertEqual(
            [client["id"] for client in snapshot["clients"]], [self.client["id"], seoul["id"]]
        )
        self.assertNotIn(
            busan["id"], [client["id"] for client in snapshot["clients"]]
        )
        self.assertEqual(len(snapshot["regions"]), 17)

    def test_location_persistence_is_debounced(self):
        repository = CountingRepository()
        store = MonitoringStore(repository, persist_debounce_seconds=60)
        client = store.register(
            {"name": "연속 위치 사용자", "userId": "U-1", "regionId": "KR-26"}
        )

        for offset in range(30):
            store.update_location(
                client["id"],
                {"lat": 35.2 + offset / 100_000, "lng": 129.0},
            )

        self.assertEqual(repository.save_count, 1)
        self.assertEqual(store.client_for_user("U-1")["id"], client["id"])
        store.flush()
        self.assertEqual(repository.save_count, 2)

    def test_public_alerts_are_upserted_and_filtered_by_region(self):
        alerts = self.store.upsert_public_alerts(
            [
                {
                    "sourceId": "seoul-001",
                    "source": "공공데이터 테스트",
                    "regionId": "KR-11",
                    "type": "HEAVY_RAIN",
                    "severity": "WARNING",
                    "title": "서울 호우주의보",
                    "message": "저지대 접근에 주의하세요.",
                    "issuedAt": "2026-06-12T01:00:00+00:00",
                },
                {
                    "sourceId": "busan-001",
                    "source": "공공데이터 테스트",
                    "regionId": "KR-26",
                    "severity": "ADVISORY",
                    "title": "부산 강풍 예비특보",
                    "issuedAt": "2026-06-12T02:00:00+00:00",
                },
            ]
        )

        self.assertEqual(len(alerts), 2)
        self.assertEqual(
            [alert["title"] for alert in self.store.snapshot("KR-11")["publicAlerts"]],
            ["서울 호우주의보"],
        )
        seoul = next(
            region
            for region in self.store.snapshot()["regions"]
            if region["id"] == "KR-11"
        )
        self.assertEqual(seoul["publicAlerts"], 1)
        self.assertEqual(seoul["publicSeverity"], "WARNING")

    def test_expired_public_alert_is_hidden(self):
        self.store.upsert_public_alerts(
            [
                {
                    "sourceId": "expired-001",
                    "regionId": "KR-11",
                    "severity": "INFO",
                    "title": "만료 알림",
                    "issuedAt": "2020-01-01T00:00:00+00:00",
                    "expiresAt": "2020-01-02T00:00:00+00:00",
                }
            ]
        )

        self.assertEqual(self.store.snapshot("KR-11")["publicAlerts"], [])

    def test_polygon_danger_area_entry_and_exit_are_logged(self):
        area = self.store.create_danger_area(
            {
                "name": "다각형 테스트 구역",
                "regionId": "KR-11",
                "shape": "POLYGON",
                "severity": 5,
                "points": [
                    {"lat": 37.50, "lng": 127.00},
                    {"lat": 37.50, "lng": 127.02},
                    {"lat": 37.52, "lng": 127.02},
                    {"lat": 37.52, "lng": 127.00},
                ],
            }
        )

        inside = self.store.update_location(
            self.client["id"], {"lat": 37.51, "lng": 127.01}
        )
        outside = self.store.update_location(
            self.client["id"], {"lat": 37.54, "lng": 127.04}
        )

        self.assertTrue(
            point_in_polygon(37.51, 127.01, area["points"])
        )
        self.assertEqual(inside["dangerArea"]["id"], area["id"])
        self.assertEqual(outside["dangerState"], "SAFE")
        self.assertEqual(
            [event["type"] for event in self.store.timeline[:2]],
            ["DANGER_EXIT", "DANGER_ENTER"],
        )

    def test_circle_danger_area_can_be_deleted(self):
        area = self.store.create_danger_area(
            {
                "name": "원형 테스트 구역",
                "regionId": "KR-11",
                "shape": "CIRCLE",
                "severity": 3,
                "lat": 37.51,
                "lng": 127.01,
                "radius": 200,
            }
        )
        self.store.update_location(
            self.client["id"], {"lat": 37.51, "lng": 127.01}
        )

        deleted = self.store.delete_danger_area(area["id"])

        self.assertEqual(deleted["id"], area["id"])
        self.assertEqual(self.store.client(self.client["id"])["dangerState"], "SAFE")

    def test_heartbeat_detects_low_battery_and_immobility_once(self):
        self.store.update_location(
            self.client["id"], {"lat": 37.51, "lng": 127.01}
        )
        client = self.store.clients[self.client["id"]]
        client["movement"]["lastMovedAt"] = (
            datetime.now(timezone.utc) - timedelta(minutes=16)
        ).isoformat()

        updated = self.store.heartbeat(
            self.client["id"],
            {"batteryLevel": 12, "batteryCharging": False},
        )
        first_count = len(
            [
                event
                for event in self.store.timeline
                if event["type"] in {"LOW_BATTERY", "IMMOBILE"}
            ]
        )
        self.store.heartbeat(
            self.client["id"],
            {"batteryLevel": 12, "batteryCharging": False},
        )

        self.assertTrue(updated["warnings"]["lowBattery"])
        self.assertTrue(updated["warnings"]["immobile"])
        self.assertEqual(first_count, 2)
        self.assertEqual(
            len(
                [
                    event
                    for event in self.store.timeline
                    if event["type"] in {"LOW_BATTERY", "IMMOBILE"}
                ]
            ),
            2,
        )

    def test_route_analytics_and_nearby_facilities(self):
        base = datetime(2026, 6, 14, tzinfo=timezone.utc)
        points = [
            (37.5665, 126.9780, base),
            (37.5665, 126.9780, base + timedelta(minutes=10)),
            (37.5700, 126.9820, base + timedelta(minutes=20)),
        ]
        for lat, lng, captured_at in points:
            self.store.update_location(
                self.client["id"],
                {"lat": lat, "lng": lng, "capturedAt": captured_at.isoformat()},
            )

        analytics = self.store.client_analytics(self.client["id"])
        facilities = self.store.nearby_facilities(self.client["id"])

        self.assertGreater(analytics["distanceMeters"], 0)
        self.assertEqual(analytics["stationarySeconds"], 600)
        self.assertTrue(analytics["frequentPlaces"])
        self.assertEqual(len(facilities), 3)
        self.assertEqual(
            [item["distanceMeters"] for item in facilities],
            sorted(item["distanceMeters"] for item in facilities),
        )

    def test_group_membership_and_audit_region_filter(self):
        group = self.store.create_group(
            {"name": "집중 관리", "regionId": "KR-11", "color": "#123456"}
        )
        busan = self.store.register({"name": "부산 사용자", "regionId": "KR-26"})
        with self.assertRaises(ValueError):
            self.store.set_group_members(group["id"], [busan["id"]])
        updated = self.store.set_group_members(group["id"], [self.client["id"]])
        actor = {
            "id": "ADMIN-1",
            "displayName": "전국 관리자",
            "role": "NATIONAL_ADMIN",
            "regionId": None,
        }
        self.store.audit(
            actor, "GROUP_MEMBERS_UPDATE", group["id"], group["name"], "KR-11"
        )
        self.store.audit(actor, "OTHER_REGION", "target", "", "KR-26")

        seoul = self.store.snapshot("KR-11")
        deleted = self.store.delete_group(group["id"])

        self.assertEqual(updated["memberIds"], [self.client["id"]])
        self.assertEqual(
            [entry["action"] for entry in seoul["auditLogs"]],
            ["GROUP_MEMBERS_UPDATE"],
        )
        self.assertEqual(deleted["id"], group["id"])
        self.assertEqual(self.store.client(self.client["id"])["groupIds"], [])

    def test_new_monitoring_state_is_persisted(self):
        with TemporaryDirectory() as directory:
            repository = SQLiteStateRepository(Path(directory) / "expanded.db")
            store = MonitoringStore(repository)
            area = store.create_danger_area(
                {
                    "name": "저장 다각형",
                    "regionId": "KR-26",
                    "shape": "POLYGON",
                    "severity": 4,
                    "points": [
                        {"lat": 35.1, "lng": 129.0},
                        {"lat": 35.2, "lng": 129.0},
                        {"lat": 35.2, "lng": 129.1},
                    ],
                }
            )
            group = store.create_group(
                {"name": "저장 그룹", "regionId": "KR-26"}
            )
            store.audit(
                {
                    "id": "A-1",
                    "displayName": "관리자",
                    "role": "NATIONAL_ADMIN",
                    "regionId": None,
                },
                "CREATE",
                area["id"],
                "",
                "KR-26",
            )

            restored = MonitoringStore(repository)

            self.assertEqual(restored.danger_areas[0]["id"], area["id"])
            self.assertIn(group["id"], restored.groups)
            self.assertEqual(restored.audit_logs[0]["regionId"], "KR-26")


if __name__ == "__main__":
    unittest.main()
