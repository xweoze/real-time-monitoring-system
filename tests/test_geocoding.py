import unittest

from geocoding import ReverseGeocoder


class StubGeocoder(ReverseGeocoder):
    def __init__(self, provider, payload):
        super().__init__(
            provider=provider,
            url="https://example.test?lat={lat}&lng={lng}&key={api_key}",
            api_key="secret",
            cache_size=2,
        )
        self.payload = payload
        self.fetch_count = 0

    def fetch_payload(self, lat, lng):
        self.fetch_count += 1
        return self.payload


class ReverseGeocoderTest(unittest.TestCase):
    def test_kakao_response_and_cache(self):
        geocoder = StubGeocoder(
            "kakao",
            {
                "documents": [
                    {
                        "road_address": {
                            "address_name": "서울특별시 중구 세종대로 110"
                        },
                        "address": {"address_name": "서울특별시 중구 태평로1가"},
                    }
                ]
            },
        )

        first = geocoder.reverse(37.5665, 126.9780)
        second = geocoder.reverse(37.56651, 126.97801)

        self.assertEqual(first["address"], "서울특별시 중구 세종대로 110")
        self.assertEqual(second["address"], first["address"])
        self.assertEqual(geocoder.fetch_count, 1)

    def test_kakao_falls_back_to_parcel_address(self):
        geocoder = StubGeocoder(
            "kakao",
            {
                "documents": [
                    {
                        "road_address": None,
                        "address": {"address_name": "제주특별자치도 제주시"},
                    }
                ]
            },
        )

        self.assertEqual(
            geocoder.reverse(33.4996, 126.5312)["address"],
            "제주특별자치도 제주시",
        )

    def test_nominatim_response(self):
        geocoder = StubGeocoder(
            "nominatim",
            {"display_name": "Sejong-daero, Jung-gu, Seoul, South Korea"},
        )

        self.assertIn("Seoul", geocoder.reverse(37.5665, 126.9780)["address"])

    def test_disabled_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            ReverseGeocoder().reverse(37.5665, 126.9780)


if __name__ == "__main__":
    unittest.main()
