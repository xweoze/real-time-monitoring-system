import unittest

from public_data import (
    DisasterMessageProvider,
    PublicDataSynchronizer,
    WeatherWarningProvider,
    normalize_datetime,
    region_ids_from_text,
)


class StubDisasterProvider(DisasterMessageProvider):
    def fetch_items(self):
        return [
            {
                "SN": "101",
                "MSG_CN": "서울특별시와 인천광역시 저지대 침수에 주의하세요.",
                "RCPTN_RGN_NM": "서울특별시, 인천광역시",
                "CRT_DT": "20260612123000",
                "DST_SE_NM": "호우",
                "EMRG_STEP_NM": "주의",
            }
        ]


class StubWeatherProvider(WeatherWarningProvider):
    def fetch_items(self):
        return [
            {
                "TM_FC": "202606121300",
                "TITLE": "부산광역시 강풍경보",
                "T6": "부산 해안가 접근에 주의하세요.",
                "REG_NAME": "부산광역시",
            }
        ]


class PublicDataProviderTest(unittest.TestCase):
    def test_region_mapping(self):
        self.assertEqual(
            region_ids_from_text("서울특별시, 인천광역시"),
            ["KR-11", "KR-28"],
        )

    def test_disaster_message_normalization(self):
        provider = StubDisasterProvider("행정안전부", "https://example.test", "key")
        alerts = provider.fetch()

        self.assertEqual([alert["regionId"] for alert in alerts], ["KR-11", "KR-28"])
        self.assertEqual(alerts[0]["severity"], "WARNING")
        self.assertEqual(alerts[0]["type"], "DISASTER_MESSAGE")

    def test_weather_warning_normalization(self):
        provider = StubWeatherProvider("기상청", "https://example.test", "key")
        alerts = provider.fetch()

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["regionId"], "KR-26")
        self.assertEqual(alerts[0]["severity"], "CRITICAL")
        self.assertEqual(alerts[0]["type"], "WEATHER_WARNING")

    def test_kma_text_warning_response_is_parsed(self):
        text = """
#START7777
# REG_UP REG_UP_KO REG_ID REG_KO TM_FC TM_EF WRN LVL CMD ED_TM
11 서울특별시 L1010100 서울동북권 202606121300 202606121500 호우 경보 1 0
#END7777
"""
        items = WeatherWarningProvider.parse_text_items(text)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["REG_UP_KO"], "서울특별시")
        self.assertEqual(items[0]["REG_KO"], "서울동북권")
        self.assertEqual(items[0]["WRN"], "호우")
        self.assertEqual(items[0]["LVL"], "경보")

    def test_datetime_normalization(self):
        self.assertEqual(
            normalize_datetime("20260612123000"),
            "2026-06-12T12:30:00+09:00",
        )

    def test_synchronizer_reports_missing_configuration(self):
        statuses = []
        synchronizer = PublicDataSynchronizer(
            lambda alerts: alerts,
            statuses.append,
            providers=[],
        )

        self.assertEqual(synchronizer.sync_once(), 0)
        self.assertFalse(statuses[-1]["connected"])


if __name__ == "__main__":
    unittest.main()
