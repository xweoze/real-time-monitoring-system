# Real Time Location System

재난 상황에서 취약계층의 위치와 상태를 확인하고, 위험 지역 진입과 SOS 요청에 대응하는 웹 기반 MVP입니다.

## 실행 방법

별도 패키지 설치 없이 Python 3만 있으면 실행할 수 있습니다.

```bash
cd /Users/kimjihun/opensrouce/real-time-monitoring-system
python3 server.py
```

- 관제 대시보드: <http://127.0.0.1:8080/monitor>
- 사용자 안전 앱: <http://127.0.0.1:8080/app>

같은 Wi-Fi에 연결된 핸드폰에서는 서버 실행 시 터미널에 표시되는
`Client app (phone)` 주소로 접속합니다. `127.0.0.1`은 핸드폰 자신을
가리키므로 핸드폰에서 사용할 수 없습니다.

관제 대시보드의 초기 전국 관리자 계정은 `national_admin` / `admin1234`입니다. 로그인 후 지역별 관제 관리자 계정을 만들 수 있습니다.

사용자 앱에서 회원가입할 때 거주·관리 지역을 선택하고 위치 공유에 동의한 뒤 연결하면 관제 화면에 반영됩니다. SOS 버튼을 3초간 누르면 담당 지역과 전국 관제 대시보드에 긴급 요청이 생성됩니다.

회원가입 시 생년월일과 성별은 선택적으로 저장할 수 있습니다. 관제센터에는 정확한
생년월일 대신 현재 날짜 기준 만 나이와 성별만 표시됩니다.

- `서비스 연결 종료`: 위치 공유와 heartbeat만 종료
- `로그아웃`: 서버 세션을 폐기하고 계정에서 로그아웃

## 구현 기능

- SQLite 기반 회원가입·로그인·로그아웃과 12시간 서버 세션
- 선택형 생년월일·성별 프로필과 만 나이 자동 계산
- PBKDF2 비밀번호 해싱과 Bearer 토큰 인증
- 전국 관리자·지역 관리자·일반 사용자 역할별 접근 제어
- 대한민국 17개 시·도 전국 통합 현황과 지역별 관제 필터
- 지역 관리자 계정 생성 및 담당 지역 데이터 격리
- 사용자 등록과 접속·종료 상태 관리
- 수동 및 선택형 자동 위치 전송
- heartbeat 기반 비정상 연결 오프라인 처리
- Haversine 공식 기반 원형 위험 구역 판정
- 사용자 앱 위험 경고
- 3초 길게 누르는 SOS 요청
- 관제 화면의 사용자·위험·SOS 현황 표시
- 지역 선택에 따른 공공 재난 알림 필터링과 실시간 갱신
- SOS 구조 접수 및 완료 처리
- SOS 상태 전이 순서 검증
- 사용자별 최근 500개 이동 경로 표시
- SSE 기반 실시간 갱신 알림
- 최근 100개 이벤트 타임라인
- SQLite 기반 서버 재시작 데이터 복구

## 프로젝트 구조

```text
server.py                 HTTP API, 권한 검사와 모니터링 저장소
auth.py                   SQLite 계정, 비밀번호 해싱과 세션
regions.py                대한민국 17개 시·도 기준 정보
static/app.html           사용자 안전 앱
static/monitor.html       관제 대시보드
static/*.js               API 호출과 화면 동작
static/*.css              사용자 앱과 관제 화면 스타일
tests/test_server.py      핵심 도메인 로직 테스트
tests/test_auth.py        회원가입·로그인·로그아웃 테스트
Conceptualization_*.md    개념화 문서
Analysis_*.md             분석 문서
Design_*.md               설계 문서
```

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

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
- 실제 지도 서비스가 아닌 대한민국 개요 기반 좌표 화면을 사용합니다.
- 공공 재난 알림 공급자는 구현되어 있으나 실제 호출에는 기관별 활용 승인, 정확한 호출 URL과 API 키가 필요합니다.
- 초기 전국 관리자 비밀번호는 로컬 시연용이므로 배포 전에 반드시 변경해야 합니다.
- HTTPS, MFA, 세션 쿠키, 상세 감사 로그와 백업은 아직 없습니다.
- 실제 119·구조기관에 SOS를 자동 전달하지 않습니다.
- 동시 접속 및 응답 시간 목표는 아직 부하 테스트로 검증되지 않았습니다.

실제 배포 전에는 사용자 동의와 위치정보 처리 정책, HTTPS, HttpOnly 세션 쿠키, 관리자 MFA, 데이터 보존 기간, 장애 복구, 실제 지도 연동 및 구조기관 협력 절차가 필요합니다.
생년월일과 성별은 민감한 개인정보가 될 수 있으므로 수집 목적, 보존 기간, 열람 권한과 삭제 절차도 별도로 고지해야 합니다.

## 문서

- [Conceptualization Document](Conceptualization_22212023_김지훈.md)
- [Analysis Document](Analysis_22212023_김지훈.md)
- [Design Document](Design_22212023_김지훈.md)
