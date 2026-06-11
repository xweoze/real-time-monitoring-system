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

사용자 앱에서 위치 공유에 동의하고 이름을 입력해 연결한 후 위치를 전송하면 관제 화면에 반영됩니다. `위험 이동 체험` 버튼으로 위험 지역 진입을 확인할 수 있으며, SOS 버튼을 3초간 누르면 관제 대시보드에 긴급 요청이 생성됩니다.

## 구현 기능

- 사용자 등록과 접속·종료 상태 관리
- 수동 및 선택형 자동 위치 전송
- heartbeat 기반 비정상 연결 오프라인 처리
- Haversine 공식 기반 원형 위험 구역 판정
- 사용자 앱 위험 경고
- 3초 길게 누르는 SOS 요청
- 관제 화면의 사용자·위험·SOS 현황 표시
- SOS 구조 접수 및 완료 처리
- SOS 상태 전이 순서 검증
- 사용자별 최근 500개 이동 경로 표시
- SSE 기반 실시간 갱신 알림
- 최근 100개 이벤트 타임라인
- SQLite 기반 서버 재시작 데이터 복구

## 프로젝트 구조

```text
server.py                 Python HTTP 서버와 인메모리 저장소
static/app.html           사용자 안전 앱
static/monitor.html       관제 대시보드
static/*.js               API 호출과 화면 동작
static/*.css              사용자 앱과 관제 화면 스타일
tests/test_server.py      핵심 도메인 로직 테스트
Conceptualization_*.md    개념화 문서
Analysis_*.md             분석 문서
Design_*.md               설계 문서
```

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

## 현재 범위와 한계

현재 버전은 로컬 시연용 MVP입니다.

- 서버 재시작 후 데이터는 복구되며 접속 상태는 안전하게 `OFFLINE`으로 시작합니다.
- 실제 지도 서비스가 아닌 시연용 좌표 화면을 사용합니다.
- 운영자 인증과 역할별 접근 제어가 없습니다.
- HTTPS, 운영자 인증, 감사 로그와 백업이 없습니다.
- 실제 119·구조기관에 SOS를 자동 전달하지 않습니다.
- 동시 접속 및 응답 시간 목표는 아직 부하 테스트로 검증되지 않았습니다.

실제 배포 전에는 사용자 동의와 위치정보 처리 정책, 운영자 인증, HTTPS, 영구 저장소, 데이터 보존 기간, 장애 복구, 실제 지도 연동 및 구조기관 협력 절차가 필요합니다.

## 문서

- [Conceptualization Document](Conceptualization_22212023_김지훈.md)
- [Analysis Document](Analysis_22212023_김지훈.md)
- [Design Document](Design_22212023_김지훈.md)
