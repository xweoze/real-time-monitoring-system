import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from server import MonitoringStore, SQLiteStateRepository, distance_m


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

    def test_danger_detection(self):
        updated = self.store.update_location(
            self.client["id"], {"lat": 37.4979, "lng": 127.0276, "accuracy": 3}
        )
        self.assertEqual(updated["dangerState"], "DANGER")
        self.assertEqual(updated["dangerArea"]["id"], "AREA-01")

    def test_sos_lifecycle(self):
        self.store.update_location(self.client["id"], {"lat": 37.512, "lng": 127.010})
        event = self.store.create_sos(self.client["id"], {"message": "도와주세요"})
        acknowledged = self.store.update_sos(event["id"], "ACKNOWLEDGED", "operator-1")
        resolved = self.store.update_sos(event["id"], "RESOLVED", "operator-1")
        self.assertEqual(acknowledged["status"], "ACKNOWLEDGED")
        self.assertIsNotNone(resolved["resolvedAt"])

    def test_invalid_sos_transition(self):
        self.store.update_location(self.client["id"], {"lat": 37.512, "lng": 127.010})
        event = self.store.create_sos(self.client["id"], {})
        with self.assertRaises(ValueError):
            self.store.update_sos(event["id"], "RESOLVED", "operator-1")

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


if __name__ == "__main__":
    unittest.main()
