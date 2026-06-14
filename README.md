# Real Time Location System

재난 상황에서 취약계층의 위치와 상태를 확인하고, 위험 지역 진입과 SOS 요청에 대응하는 웹 기반 MVP입니다.

## 실행 방법

별도 패키지 설치 없이 Python 3만 있으면 실행할 수 있습니다.

```bash
cd /Users/kimjihun/opensrouce/real-time-monitoring-system
python3 server.py
```

- 관제 대시보드: <http://127.0.0.1:8080/monitor>
- 회원 정보 관리: <http://127.0.0.1:8080/members>
- 사용자 안전 앱: <http://127.0.0.1:8080/app>

같은 Wi-Fi에 연결된 핸드폰에서는 서버 실행 시 터미널에 표시되는
`Client app (phone)` 주소로 접속합니다. `127.0.0.1`은 핸드폰 자신을
가리키므로 핸드폰에서 사용할 수 없습니다.

관제 대시보드의 초기 전국 관리자 계정은 `national_admin` / `admin1234`입니다.
전국 관리자는 왼쪽 위 메뉴의 `지역 관리자 관리`에서 지역별 관제 관리자 계정을
만들 수 있습니다.

사용자 앱에서 회원가입할 때 거주·관리 지역을 선택하고 위치 공유에 동의한 뒤 연결하면 관제 화면에 반영됩니다. SOS 버튼을 3초간 누르면 담당 지역과 전국 관제 대시보드에 긴급 요청이 생성됩니다.

회원가입 시 생년월일과 성별은 선택적으로 저장할 수 있습니다. 관제 대시보드에는
현재 날짜 기준 만 나이와 성별을 표시하고, 권한이 있는 관리자는 `정보 수정 관리`
페이지에서 생년월일을 포함한 회원 정보를 조회·수정·삭제할 수 있습니다.

- `서비스 연결 종료`: 위치 공유와 heartbeat만 종료
- `로그아웃`: 서버 세션을 폐기하고 계정에서 로그아웃

## 구현 기능

- SQLite 기반 회원가입·로그인·로그아웃과 12시간 서버 세션
- 선택형 생년월일·성별 프로필과 만 나이 자동 계산
- PBKDF2 비밀번호 해싱과 Bearer 토큰 인증
- 전국 관리자·지역 관리자·일반 사용자·보호자 역할별 접근 제어
- 사용자 동의 기반 보호자 계정 연결·해제와 최신 안전 상태 제한 조회
- 대한민국 17개 시·도 전국 통합 현황과 지역별 관제 필터
- Leaflet과 통계청 SGIS 시·도 경계 기반 실제 좌표 지도
- 지역 관리자 계정 생성 및 담당 지역 데이터 격리
- 관리자 회원 조회·수정·삭제와 관제 프로필 동기화
- 회원 삭제 시 세션, 단말, 경로와 SOS 관련 데이터 정리
- 서버 시작 시 실제 회원 계정과 연결되지 않은 과거 단말 자동 정리
- 사용자 등록과 접속·종료 상태 관리
- 수동 및 선택형 자동 위치 전송
- heartbeat 기반 비정상 연결 오프라인 처리
- Haversine 공식 기반 원형 위험 구역 판정
- 원형·다각형 위험구역 생성·삭제와 지도 표시
- 위험구역별 진입·이탈 이벤트 기록
- 15분 장시간 무동작, 위치 신호 끊김과 지원 기기의 배터리 부족 경고
- 이동 거리·정차 시간·좌표 격자 기반 자주 방문한 장소 통계
- 지역별 기본 대피소·응급의료기관·소방서 거리 정렬과 길 안내 링크
- 호우·지진·화재·폭염·한파 행동 요령
- 사용자 그룹 생성·배정·지도 필터와 그룹 색상 표시
- 활성 알림의 심각도·종류·시간·지역 필터
- 관리자 위험구역·그룹·회원·SOS 작업 감사 로그
- HMAC 서명과 비동기 큐를 사용하는 n8n 외부 알림 Webhook
- 공식 재난 행동요령 문서 기반 출처 표시 검색
- Playwright 데스크톱·모바일 화면 및 시각 회귀검사
- 사용자 앱 위험 경고
- 3초 길게 누르는 SOS 요청
- 관제 화면의 사용자·위험·SOS 현황 표시
- 관제자 요청 시 위·경도를 도로명 또는 지번 주소로 변환
- 좌표 기반 주소 캐시와 위치 변경 중 잘못된 주소 저장 방지
- 지역 선택에 따른 공공 재난 알림 필터링과 실시간 갱신
- SOS 신규·접수/배정·출동·완료 단계 처리
- SOS 담당자·처리 메모·단계별 변경 이력 저장
- SOS 상태 전이 순서 검증
- 사용자별 최근 500개 이동 경로 표시
- SSE 기반 실시간 갱신 알림
- 최근 100개 이벤트 타임라인
- 금일 이벤트 카드의 유형·내용·발생 시각 상세 조회
- SQLite 기반 서버 재시작 데이터 복구

## 프로젝트 구조

```text
server.py                 HTTP API, 권한 검사와 모니터링 저장소
auth.py                   SQLite 계정, 비밀번호 해싱과 세션
public_data.py            공공데이터 응답 변환과 주기 동기화
geocoding.py              Kakao·Nominatim 역지오코딩과 좌표 캐시
notifications.py          서명된 비동기 n8n Webhook 발송
disaster_rag.py           공식 재난문서 검색과 출처 구성
disaster_docs/            로컬 재난 행동요령 지식 문서
regions.py                대한민국 17개 시·도 기준 정보
static/app.html           사용자 안전 앱
static/monitor.html       관제 대시보드
static/members.html       관리자 회원 정보 관리 화면
static/data/              대한민국 시·도 경계와 데이터 라이선스
static/vendor/            Leaflet과 TopoJSON 클라이언트
static/*.js               API 호출과 화면 동작
static/*.css              사용자 앱과 관제 화면 스타일
tests/test_server.py      핵심 도메인 로직 테스트
tests/test_auth.py        회원가입·로그인·로그아웃 테스트
tests/test_public_data.py 공공데이터 변환과 지역 매핑 테스트
tests/test_geocoding.py   주소 응답 변환과 좌표 캐시 테스트
tests/test_notifications.py Webhook 선별·서명 테스트
tests/test_disaster_rag.py 재난문서 검색·출처 테스트
e2e/                      Playwright 화면·시각 회귀검사
integrations/n8n/          n8n 가져오기 템플릿과 설정 안내
AGENTS.md                 저장소 작업·검증·보안 규칙
Conceptualization_*.md    개념화 문서
Analysis_*.md             분석 문서
Design_*.md               설계 문서
```

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

현재 Python 자동 테스트는 총 52개이며 인증, 보호자 연결, 위험구역·기기 경고·이동 통계·그룹·감사 로그,
Webhook 선별·서명, 재난문서 검색·출처,
환경설정 로딩, 회원 정보 관리,
고아 단말 정리, 위치·주소·SOS, 지역 필터, 상태 복구와 공공데이터 변환을 검증합니다.

## Playwright 화면 회귀검사

최초 한 번 설치합니다.

```bash
npm install
npx playwright install chromium
```

일반 회귀검사는 다음 명령으로 실행합니다.

```bash
npm run test:e2e
```

의도적으로 디자인을 변경한 경우에만 기준 이미지를 갱신합니다.

```bash
npm run test:e2e:update
```

Playwright는 실제 개발 서버와 충돌하지 않도록 임시 DB와 `8091` 포트를 사용합니다.
기준 이미지 변경은 `e2e/monitor.spec.js-snapshots/`의 이미지 차이를 확인한 뒤 반영합니다.

## n8n 알림 Webhook

`.env`에 다음 값을 설정하면 외부 알림이 활성화됩니다.

```bash
RTLS_N8N_WEBHOOK_URL='https://n8n.example.com/webhook/rtls-alert'
RTLS_N8N_WEBHOOK_SECRET='길고_무작위인_공유_비밀값'
```

SOS, 위험구역 진입, 위치 신호 끊김, 배터리 부족, 장시간 무동작과 심각 공공알림만
비동기 큐로 전송합니다. 서버의 위치·SOS API는 n8n 응답을 기다리지 않습니다.
가져오기용 워크플로와 서명 검증 방법은 `integrations/n8n/README.md`에 있습니다.

Webhook에는 이름·지역·최신 위치가 포함될 수 있으므로 n8n 실행 기록의 보존 기간과
문자·메신저 공급자의 개인정보 처리 범위를 실제 사용 전에 확정해야 합니다.

## 재난문서 검색

관제 메뉴의 `재난문서 검색`에서 호우, 침수, 지진, 화재, 폭염과 한파 행동요령을
검색할 수 있습니다. 현재 구현은 생성형 모델이 새 문장을 만드는 방식이 아니라,
`disaster_docs/`의 공식기관 기반 문단을 관련도 순으로 찾아 출처 링크와 함께
표시합니다. 따라서 OpenAI API 키 없이 작동합니다.

운영 시에는 문서 담당자, 원문 URL, 검토일을 관리하고 기관 원문이 변경되면 로컬
문서와 검색 테스트를 함께 갱신해야 합니다.

## 보호자 연결

1. 보호자는 사용자 앱의 회원가입 화면에서 `보호자` 계정을 만듭니다.
2. 보호 대상 사용자가 로그인한 뒤 보호자 아이디를 입력해 연결합니다.
3. 보호자는 로그인 후 연결된 사용자의 최신 접속 상태, 안전 상태, 위치와 진행 중인
   SOS만 확인할 수 있습니다.
4. 보호 대상 사용자는 언제든 보호자 연결을 해제할 수 있습니다.

보호자는 위치 전송, SOS 생성, 전체 이동 경로 조회와 관제 기능을 사용할 수 없습니다.

## 안전 분석 기능 참고

- 무동작은 마지막 20m 이상 이동 후 15분이 지났는지 기준으로 판정합니다.
- 배터리 경고는 브라우저가 Battery Status API를 제공하는 기기에서만 동작합니다.
- 가까운 안전시설은 현재 각 시·도 기준점 주변의 기본 시연 데이터입니다. 실제 운영
  전에는 행정안전부·국립중앙의료원·소방청 등 최신 공공데이터로 교체해야 합니다.
- 자주 방문한 장소는 개인정보 노출을 줄이기 위해 좌표를 소수점 셋째 자리 격자로
  묶어 방문 횟수를 계산합니다.

## 주소 변환 설정

관제 화면에서 사용자를 선택하고 `주소 확인`을 누르면 해당 시점의 위·경도를
서버가 주소 API로 전송합니다. 자동 위치 전송 때마다 호출하지 않으며, 가까운
좌표의 결과는 최대 1,000개까지 메모리에 캐시합니다.

Kakao Local API를 사용하는 경우 `.env`에 다음 값을 설정합니다.

```bash
RTLS_GEOCODER_PROVIDER='kakao'
RTLS_GEOCODER_URL='https://dapi.kakao.com/v2/local/geo/coord2address.json?x={lng}&y={lat}'
RTLS_GEOCODER_API_KEY='Kakao_REST_API_키'
```

설정 후 서버를 재시작해야 합니다. 주소는 최신 위치 데이터와 함께 SQLite에
저장되므로 개인정보 처리 목적과 보존 기간에 주소 정보도 포함해야 합니다.

## 공공 재난 알림 연동

관제 화면은 공공데이터 공급자가 보내는 알림을 `regionId` 기준으로 분리합니다.
전국 관리자 토큰으로 다음 표준 형식의 데이터를 `/api/public-alerts`에 전달하면
해당 지역의 `활성 알림`에 즉시 표시되고 SSE로 갱신됩니다.

```json
{
  "alerts": [
    {
      "sourceId": "official-alert-id",
      "source": "기상청",
      "regionId": "KR-11",
      "type": "HEAVY_RAIN",
      "severity": "WARNING",
      "title": "서울 호우주의보",
      "message": "저지대와 하천 주변 접근에 주의하세요.",
      "issuedAt": "2026-06-12T12:00:00+09:00",
      "expiresAt": "2026-06-12T18:00:00+09:00",
      "sourceUrl": "https://example.go.kr/alert"
    }
  ]
}
```

동일한 `source`와 `sourceId`는 갱신 처리되며, `expiresAt`이 지난 알림은 화면에서
자동으로 제외됩니다.

현재 서버에는 행정안전부 긴급재난문자와 기상청 기상특보의 JSON/XML 응답을
표준 알림으로 변환하고, 기관 지역명을 내부 `KR-*` 코드로 매핑하는 공급자 모듈이
포함되어 있습니다. 기본 동기화 주기는 5분입니다.

API 활용 신청이 승인되면 예시 설정을 복사하고 승인 화면에 표시된 실제 호출 URL과
키를 입력합니다. API 키가 포함된 `.env` 파일은 Git에 커밋되지 않습니다.

```bash
cp .env.example .env
# .env의 URL과 키 수정
source .env
python3 server.py
```

기관마다 `serviceKey`, `authKey`처럼 키 매개변수 이름이 다르므로 호출 URL에서
키가 들어갈 위치를 `{service_key}`로 작성합니다.

```bash
export RTLS_DISASTER_API_URL='기관_호출_URL?serviceKey={service_key}&returnType=json'
export RTLS_DISASTER_API_KEY='발급받은_키'
export RTLS_WEATHER_API_URL='기관_호출_URL?authKey={service_key}'
export RTLS_WEATHER_API_KEY='발급받은_키'
export RTLS_PUBLIC_DATA_INTERVAL='300'
```

전국 관리자는 `POST /api/public-alerts/sync`를 호출해 즉시 동기화할 수도 있습니다.

## 현재 범위와 한계

현재 버전은 로컬 시연용 MVP입니다.

- 서버 재시작 후 데이터는 복구되며 접속 상태는 안전하게 `OFFLINE`으로 시작합니다.
- 회원 계정이 삭제됐거나 계정 ID가 없는 과거 단말은 시작 시 자동 제거됩니다.
- 지도는 통계청 SGIS의 2018년 시·도 경계를 사용하며 최신 행정 경계, 도로,
  건물, 주소 검색과 배경 지도 타일은 제공하지 않습니다. 단, 설정된 역지오코딩
  API를 통한 현재 좌표의 주소 확인은 지원합니다.
- 공공 재난 알림 공급자는 구현되어 있으나 실제 호출에는 기관별 활용 승인, 정확한 호출 URL과 API 키가 필요합니다.
- 초기 전국 관리자 비밀번호는 로컬 시연용이므로 배포 전에 반드시 변경해야 합니다.
- HTTPS, MFA, 세션 쿠키, 영구 보존되는 보안 감사 로그와 백업은 아직 없습니다.
- 실제 119·구조기관에 SOS를 자동 전달하지 않습니다.
- 동시 접속 및 응답 시간 목표는 아직 부하 테스트로 검증되지 않았습니다.

실제 배포 전에는 사용자 동의와 위치정보 처리 정책, HTTPS, HttpOnly 세션 쿠키, 관리자 MFA, 데이터 보존 기간, 장애 복구, 최신 행정 경계·도로 지도 연동 및 구조기관 협력 절차가 필요합니다.
생년월일과 성별은 민감한 개인정보가 될 수 있으므로 수집 목적, 보존 기간, 열람 권한과 삭제 절차도 별도로 고지해야 합니다.

## 문서

- [Conceptualization Document](Conceptualization_22212023_김지훈.md)
- [Analysis Document](Analysis_22212023_김지훈.md)
- [Design Document](Design_22212023_김지훈.md)
