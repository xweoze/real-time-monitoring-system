

# Real Time Location System

## Conceptualization Document

---

### Disaster Vulnerable Population Real-Time Monitoring System

(재난 상황 취약계층 실시간 위치 및 상태 모니터링 시스템)

---

## [ Revision history ]

</div>

<table align="center">
<tr>
<th>Revision date</th>
<th>Version #</th>
<th>Description</th>
<th>Author</th>
</tr>

<tr align="center">
<td>2026-03-27</td>
<td>0.01</td>
<td>First Documentation</td>
<td>김지훈</td>
</tr>

<tr align="center">
<td>2026-03-28</td>
<td>0.02</td>
<td>Use case 추가 및 수정</td>
<td>김지훈</td>
</tr>
</table>


<div align="center">

<div align="center">

## = Contents =

</div>

---

### 📌 Sections

1. Business Purpose  
2. System Context Diagram  
3. Use Case List  
4. Concept of Operation  
5. Problem Statement  
6. Glossary  
7. References  

---

## 1. Business purpose

### 1.1 Project background

<div align="center">
  <img width="1536" height="1024" alt="dfdf" src="https://github.com/user-attachments/assets/e776a374-044e-45df-91ea-9f457db673fc" />
</div>

<div align="center">
  <sub>(그림 1) 재난 상황 속 취약계층 구조 장면</sub>
</div>

---
전쟁, 자연재해, 대형 사고와 같은 재난 상황에서는  
노인, 여성, 아동과 같은 취약계층이 신속한 구조를 받지 못하는 문제가 발생한다.

특히 최근 우크라이나-러시아 전쟁, 중동 지역의 긴장(이란-미국 관계 등)과 같은 국제 정세를 통해  
실제 전쟁 상황에서 민간인과 취약계층이 겪는 위험과 구조의 어려움이 더욱 부각되고 있다.

우리나라는 현재 전쟁 상태는 아니지만, 분단 국가로서 항상 잠재적인 위기 상황에 대비해야 하는 환경에 놓여 있다.  
따라서 이러한 상황을 보며, 재난 및 전시 상황에서도 보다 빠르게 대응할 수 있는 시스템이 필요하다고 생각하게 되었다.

이러한 문제를 해결하기 위해  
취약계층의 위치와 상태를 실시간으로 수집하고,  
중앙에서 이를 모니터링할 수 있는 시스템을 만들어 관리하면 좋겠다는 생각을 하였다.

---

### 📡 System Idea

<div align="center">
  <img width="1536" height="1024" alt="dfsf" src="https://github.com/user-attachments/assets/a49a2889-b134-45c9-b24c-76c8387dec1a" />
</div>

<div align="center">
  <sub>(그림 3) 재난 상황 취약계층 실시간 모니터링 시스템 구조</sub>
</div>

---

이 시스템은 사용자의 위치와 상태를 서버로 전송하고,  
관제자가 이를 실시간으로 확인함으로써  
위험 상황 발생 시 빠르게 대응할 수 있도록 한다.

---

### ✔ 핵심 기능

- 사용자는 시스템에 접속하여 자신의 위치를 전송한다  
- 위험 지역에 진입하면 자동으로 위험 상태가 감지된다  
- 긴급 상황 발생 시 SOS 요청을 전송할 수 있다  
- 관제자는 모든 사용자의 위치와 상태를 실시간으로 확인한다  
- 특정 사용자의 이동 경로를 분석하여 위험도를 판단할 수 있다  

---

### 1.2 Target Market

- 재난 취약 지역 거주자  
- 노인 및 1인 가구  
- 여성 및 아동  
- 공공 안전 기관 및 구조 조직  

---

### 1.3 Goals

- 취약계층의 위치 및 상태 실시간 모니터링  
- 위험 상황 자동 감지 시스템 구축  
- 구조 요청(SOS) 기능 제공  
- 클라이언트 / 서버 / 관제 시스템 구현  
- 재난 대응 속도 향상

---
## 2. System context diagram

<div align="center">
  <img width="1536" height="1024" alt="diagram" src="https://github.com/user-attachments/assets/387e6a5c-e9ad-4584-b6d2-5c81c24e660f" />
</div>

- Connect : 접속  
- Connect Notice : 접속 알림  
- Move : 이동  
- Is Danger : 위험 감지  
- Send Message : 메시지 송신  
- Reception Message : 메시지 수신  
- Send SOS : SOS 요청  
- Reception SOS : SOS 요청 확인  
- Exit : 접속 종료  
- Exit Notice : 접속 종료 알림  
- Monitoring Clients : 사용자 위치 및 상태 모니터링  
- Client Route : 사용자 이동 경로 확인  
- Danger Client : 위험 지역 체류 시 알림  
- Warning to Client : 위험 위치 알림  
- Help Client : 구조 지원 요청  
- Get Location & State : 사용자 위치 및 상태 확인

<br><br>
## 3. Use case list

### 3.1. System Connect
| Actor | Client |
|------|--------|
| Description | 사용자가 시스템에 접속하면 고유 ID를 부여받는다. |


### 3.2. Send Location & State
| Actor | Client |
|------|--------|
| Description | 사용자가 자신의 위치와 상태 정보를 시스템으로 전송한다. |


### 3.3. Danger Detection
| Actor | System |
|------|--------|
| Description | 시스템이 사용자의 위치를 기반으로 위험 지역 진입 여부를 판단한다. |


### 3.4. Danger Alert to Client
| Actor | System |
|------|--------|
| Description | 사용자가 위험 지역에 진입하면 경고 메시지를 전달한다. |


### 3.5. Send SOS
| Actor | Client |
|------|--------|
| Description | 사용자가 긴급 상황에서 구조 요청(SOS)을 전송한다. |


### 3.6. Monitoring Clients
| Actor | Monitoring |
|------|------------|
| Description | 관제자가 사용자들의 위치와 상태를 실시간으로 확인한다. |


### 3.7. Rescue Support
| Actor | Monitoring |
|------|------------|
| Description | 관제자가 위험 상황을 확인하고 구조를 지원한다. |


### 3.8. System Exit
| Actor | Client |
|------|--------|
| Description | 사용자가 시스템 접속을 종료한다. |

<br><br>
<br><br>

## 4. Concept of operation

### 4.1. System Connect
| Purpose | 사용자가 시스템에 접속 |
|--------|----------------------|
| Approach | 사용자가 프로그램에 접속하면 서버로부터 고유 ID를 부여받고 시스템과 연결된다. |
| Dynamics | 사용자가 시스템에 처음 접속하는 경우 |
| Goals | 사용자가 시스템을 사용할 수 있도록 연결 상태를 유지한다. |

---

### 4.2. Send Location & State
| Purpose | 사용자의 위치 및 상태 정보 전송 |
|--------|------------------------------|
| Approach | 사용자는 자신의 위치(x,y좌표)와 상태 정보를 시스템으로 전송한다. |
| Dynamics | 사용자가 이동하거나 상태 변화가 발생한 경우 |
| Goals | 시스템이 사용자 정보를 실시간으로 수집할 수 있게 한다. |


### 4.3. Danger Detection
| Purpose | 위험 지역 진입 여부 감지 |
|--------|------------------------|
| Approach | 시스템은 사용자의 위치를 기반으로 위험 지역 여부를 판단한다. |
| Dynamics | 사용자가 특정 지역으로 이동한 경우 |
| Goals | 위험 상황을 빠르게 감지한다. |


### 4.4. Danger Alert
| Purpose | 사용자에게 위험 상황 경고 |
|--------|--------------------------|
| Approach | 사용자가 위험 지역에 진입하면 시스템이 경고 메시지를 전송한다. |
| Dynamics | 사용자가 위험 지역에 진입한 경우 |
| Goals | 사용자가 위험을 인지하고 대응할 수 있도록 한다. |


### 4.5. Send SOS
| Purpose | 긴급 상황 시 구조 요청 |
|--------|----------------------|
| Approach | 사용자가 SOS 버튼을 통해 구조 요청을 보내면 시스템이 이를 관제자에게 전달한다. |
| Dynamics | 사용자가 위험 상태에 놓인 경우 |
| Goals | 빠르게 구조 요청이 전달되도록 한다. |


### 4.6. Monitoring Clients
| Purpose | 사용자 위치 및 상태 모니터링 |
|--------|----------------------------|
| Approach | 관제자는 시스템을 통해 사용자들의 위치와 상태 정보를 실시간으로 확인한다. |
| Dynamics | 여러 사용자가 동시에 시스템을 사용하는 경우 |
| Goals | 위험 상황을 신속하게 파악할 수 있도록 한다. |


### 4.7. Rescue Support
| Purpose | 구조 지원 수행 |
|--------|--------------|
| Approach | 관제자가 위험 상황을 확인하고 구조 인력에게 정보를 전달한다. |
| Dynamics | SOS 요청 또는 위험 상황 발생 시 |
| Goals | 구조 대응 시간을 최소화한다. |


### 4.8. System Exit
| Purpose | 시스템 접속 종료 |
|--------|----------------|
| Approach | 사용자가 시스템 종료 시 서버와의 연결이 해제된다. |
| Dynamics | 사용자가 시스템을 종료하는 경우 |
| Goals | 시스템 자원을 효율적으로 관리한다. |


# 5. Problem statement

## 5.1. Overview
Real Time Location System은 클라이언트의 위치와 상태를 실시간으로 모니터링하는 것을 주 목적으로 한다. 또한 SOS 요청, 클라이언트 구조 요청 등을 실시간으로 시스템에 접속한 사용자에게 전달하여 위험 상황에 대응할 수 있도록 한다.

이 시스템은 다음과 같은 목표를 달성해야 한다.

- 정확한 데이터 처리  
- 실시간 데이터 처리  
- 안정적인 통신 유지  

---

## 5.2. Problem definition
Real Time Location System에서 클라이언트와 옵저버가 서버를 통해 통신하는 과정에서 발생할 수 있는 주요 문제점과 해결 방안은 다음과 같다.

---

### 5.2.1. Problem#1 Protocol 설계

클라이언트와 서버, 옵저버 간의 정확한 데이터 통신을 위해서는 통신 규약(Protocol)을 정의하는 것이 필수적이다.

Real Time Location System에서는 빠르고 정확한 통신을 위해 다음과 같은 방식으로 프로토콜을 설계한다.

- 데이터의 시작과 끝을 구분하기 위해 STX(Start of Text)와 ETX(End of Text)를 사용한다.  
- 데이터 구조는 Command와 Data 영역으로 구분한다.  
- Command에는 메시지 종류(Connect, Move, SOS 등)를 정의한다.  
- Data에는 실제 전송할 위치, 상태, 메시지 정보가 포함된다.  

이를 통해 잘못된 데이터 처리 및 통신 오류를 방지하고 안정적인 데이터 교환이 가능하다.

---

### 5.2.2. Problem#2 실시간 통신 처리

사용자와 서버는 지속적으로 데이터를 주고받기 때문에 실시간 처리 구조가 필요하다.

이를 해결하기 위해 멀티스레드 기반 구조를 적용한다.

- 클라이언트는 서버로부터 데이터를 수신하는 전용 스레드를 사용한다.  
- 옵저버 또한 클라이언트 상태를 수신하기 위한 스레드를 사용한다.  
- 서버는 각 클라이언트 및 옵저버별로 독립적인 처리 스레드를 생성한다.  

이 구조를 통해 동시에 여러 사용자가 접속하더라도 지연 없이 실시간 통신이 가능하다.

---

### 5.2.3. Problem#3 클라이언트 관리

다수의 클라이언트가 접속하는 환경에서는 효율적인 사용자 관리가 필요하다.

- 서버는 접속한 클라이언트를 리스트 형태로 관리한다.  
- 새로운 클라이언트가 접속하면 리스트에 추가한다.  
- 클라이언트가 종료하면 리스트에서 제거한다.  
- 옵저버는 해당 리스트를 기반으로 클라이언트를 모니터링한다.  

이를 통해 클라이언트 상태를 체계적으로 관리할 수 있다.

---

### 5.2.4. Problem#4 위험 상황 감지

클라이언트가 위험 지역에 진입하거나 특정 조건을 만족할 경우 위험 상황을 감지해야 한다.

- 클라이언트의 위치 데이터를 지속적으로 분석한다.  
- 위험 지역에 일정 시간 이상 머무를 경우 위험 상태로 판단한다.  
- 위험 상태 발생 시 클라이언트와 옵저버에게 알림을 전송한다.  

이를 통해 사고 예방 및 빠른 대응이 가능하다.

---

### 5.2.5. Problem#5 SOS 요청 처리

클라이언트가 긴급 상황에서 도움을 요청할 수 있어야 한다.

- 클라이언트는 SOS 신호를 서버로 전송한다.  
- 서버는 해당 정보를 모든 사용자 및 옵저버에게 전달한다.  
- SOS 요청에는 위치 및 상태 정보가 포함된다.  

이를 통해 긴급 상황에서 빠른 구조 요청이 가능하다.

---

### 5.2.6. Problem#6 위치 및 상태 동기화

클라이언트의 위치와 상태 정보는 항상 최신 상태로 유지되어야 한다.

- 클라이언트는 일정 주기로 위치 데이터를 서버에 전송한다.  
- 서버는 해당 정보를 옵저버에게 실시간으로 전달한다.  
- 데이터 지연 및 손실을 최소화하는 구조를 유지한다.  

이를 통해 정확한 모니터링이 가능하다.

# 6. Glossary

| Term | Description |
|------|-------------|
| Real Time Location System | 클라이언트들의 위치 및 상태를 실시간으로 모니터링하고 서로 통신할 수 있게 해주는 시스템 |
| 클라이언트 | 가상 환경에서 움직이고 활동하는 사용자 |
| 옵저버 | 클라이언트들을 실시간으로 모니터링 하는 사용자 |
| 모니터링 | 클라이언트들의 위치 및 상태를 지속적으로 감시, 관찰하는 행위 |
| 쓰레드 | 프로그램 내에서 실행되는 흐름의 단위 |
| 프로토콜 | Real Time Location System에서 사용되는 데이터의 규칙 체계 |
| 이동 | 클라이언트가 키보드를 통해 움직이는 행위 |
| 위험감지 | 클라이언트가 위험 지역에 진입했는지에 대한 감지 |
| 상태 | 클라이언트 위험감지 장치의 상태 |
| 채팅 | 클라이언트끼리 서버를 통해 문자 기반으로 통신하는 행위 |

# 7. References

- 본 보고서의 모든 그림은 직접 제작함 (Created by author)

