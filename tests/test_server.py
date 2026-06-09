import unittest

from server import MonitoringStore, distance_m


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

    def test_invalid_coordinate(self):
        with self.assertRaises(ValueError):
            self.store.update_location(self.client["id"], {"lat": 100, "lng": 127})

    def test_distance(self):
        self.assertLess(distance_m(37.4979, 127.0276, 37.4979, 127.0276), 0.01)


if __name__ == "__main__":
    unittest.main()
