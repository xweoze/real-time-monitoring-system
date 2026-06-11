"""South Korean regional metadata used by clients and control centers."""

REGIONS = [
    {"id": "KR-11", "name": "서울특별시", "lat": 37.5665, "lng": 126.9780},
    {"id": "KR-26", "name": "부산광역시", "lat": 35.1796, "lng": 129.0756},
    {"id": "KR-27", "name": "대구광역시", "lat": 35.8714, "lng": 128.6014},
    {"id": "KR-28", "name": "인천광역시", "lat": 37.4563, "lng": 126.7052},
    {"id": "KR-29", "name": "광주광역시", "lat": 35.1595, "lng": 126.8526},
    {"id": "KR-30", "name": "대전광역시", "lat": 36.3504, "lng": 127.3845},
    {"id": "KR-31", "name": "울산광역시", "lat": 35.5384, "lng": 129.3114},
    {"id": "KR-36", "name": "세종특별자치시", "lat": 36.4800, "lng": 127.2890},
    {"id": "KR-41", "name": "경기도", "lat": 37.4138, "lng": 127.5183},
    {"id": "KR-42", "name": "강원특별자치도", "lat": 37.8228, "lng": 128.1555},
    {"id": "KR-43", "name": "충청북도", "lat": 36.8000, "lng": 127.7000},
    {"id": "KR-44", "name": "충청남도", "lat": 36.5184, "lng": 126.8000},
    {"id": "KR-45", "name": "전북특별자치도", "lat": 35.7175, "lng": 127.1530},
    {"id": "KR-46", "name": "전라남도", "lat": 34.8161, "lng": 126.4629},
    {"id": "KR-47", "name": "경상북도", "lat": 36.4919, "lng": 128.8889},
    {"id": "KR-48", "name": "경상남도", "lat": 35.4606, "lng": 128.2132},
    {"id": "KR-50", "name": "제주특별자치도", "lat": 33.4996, "lng": 126.5312},
]

REGION_BY_ID = {region["id"]: region for region in REGIONS}

