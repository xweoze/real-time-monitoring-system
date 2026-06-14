# n8n RTLS Alert Webhook

## Import

1. n8n에서 `workflow-template.json`을 가져옵니다.
2. Webhook 노드의 Production URL을 복사합니다.
3. RTLS `.env`에 URL과 동일한 공유 비밀값을 설정합니다.

```bash
RTLS_N8N_WEBHOOK_URL='https://n8n.example.com/webhook/rtls-alert'
RTLS_N8N_WEBHOOK_SECRET='길고_무작위인_공유_비밀값'
```

4. n8n 자체 호스팅 환경에서는 Code 노드가 HMAC 검증에 `crypto`를 사용할 수
   있도록 `NODE_FUNCTION_ALLOW_BUILTIN=crypto`를 설정합니다.
5. 검증 노드 뒤에 Telegram, SMS, Email, Slack 등 실제 알림 노드를 연결합니다.

## Payload

```json
{
  "version": 1,
  "event": {
    "id": "SOS-ABC123",
    "type": "SOS",
    "title": "사용자 긴급 구조 요청",
    "severity": "CRITICAL",
    "clientId": "C-0001",
    "clientName": "사용자",
    "regionId": "KR-11",
    "location": {
      "lat": 37.5665,
      "lng": 126.978
    },
    "createdAt": "2026-06-14T00:00:00+00:00"
  }
}
```

`X-RTLS-Signature` 헤더는 본문을 공유 비밀값으로 HMAC-SHA256 계산한
`sha256=<hex>` 형식입니다.

## Recommended Routing

- `SOS`: 즉시 문자·전화·메신저, 실패 시 관리자 이메일
- `DANGER_ENTER`: 보호자 또는 담당 지역 관제 알림
- `TIMEOUT`: 1차 메신저, 일정 시간 지속 시 문자
- `LOW_BATTERY`: 사용자·보호자 안내
- `IMMOBILE`: 취약계층 정책에 따라 확인 요청
- `PUBLIC_ALERT`: `WARNING` 또는 `CRITICAL`만 지역별 발송

위치와 사용자 이름은 개인정보입니다. n8n 실행 기록 보존 기간, 접근 권한과
알림 공급자의 개인정보 처리 범위를 운영 전에 확정해야 합니다.
