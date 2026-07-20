# Phase 2 수동 테스트 체크리스트

- 실행일: 2026-07-11 (Asia/Seoul)
- 대상: `meeting-live-translator` Phase 2
- 원칙: 실제 수행하지 않은 항목은 자동 테스트가 있더라도 `MANUAL PASS`로 표시하지 않는다.
- 환경: Windows 11, Python 3.11.9, CPU `int8`, OpenAI API 키 없음, 로컬 번역 모델 없음

## 결과 요약

| # | 수동 테스트 | 상태 | 실제 결과 또는 SKIP 사유 |
|---:|---|---|---|
| 1 | 일본어 시스템 음성 → 한국어 번역 | SKIP | 원문 일본어 final은 확인했지만 실제 번역 Provider가 준비되지 않아 한국어 번역은 실행하지 않음. |
| 2 | 영어 시스템 음성 → 한국어 번역 | SKIP | 실제 번역 Provider가 준비되지 않음. |
| 3 | 일본어와 영어가 번갈아 나오는 음성 | SKIP | 실제 번역 Provider가 준비되지 않음. |
| 4 | 일본어 문장 안에 영어 IT 용어가 포함된 음성 | SKIP | 실제 번역 Provider가 준비되지 않음. 용어 보존 프롬프트와 로컬 placeholder는 자동 테스트로만 검증함. |
| 5 | 번역 중 다음 음성 전사가 계속되는지 확인 | SKIP | 실제 Provider 동시 실행은 하지 않음. fake Provider 20건 비동기 benchmark와 통합 테스트는 PASS. |
| 6 | API 키 없이 원문 전사 | MANUAL PASS | `.env`와 키가 없는 상태에서 서버·WebSocket·시스템 loopback 캡처를 시작/중지함. 오류 없이 final 2건이 JSONL에 저장되고 원문 기능이 유지됨. |
| 7 | 잘못된 API 키 사용 | SKIP | 테스트용 잘못된 키를 외부 API에 전송하지 않음. 인증 실패 분류는 mock 자동 테스트로 검증함. |
| 8 | 네트워크 차단 중 원문 전사 | SKIP | 시스템 네트워크 설정을 변경하지 않음. 네트워크 실패 격리와 원문 이벤트 유지는 자동 테스트로 검증함. |
| 9 | OpenAI API timeout 중 원문 전사 | SKIP | 외부 호출을 실행하지 않음. timeout·제한 재시도는 자동 테스트로 검증함. |
| 10 | 번역 Provider 실행 중 변경 | SKIP | 사용 가능한 실제 번역 Provider가 없어 실행 중 전환은 수행하지 않음. 전환 시 pending/active 취소와 provider close는 자동 테스트로 검증함. |
| 11 | 번역 OFF로 변경 | MANUAL PASS | UI에서 `사용 안 함`을 선택한 상태로 캡처 시작·중지. 원문 final은 동작하고 번역 외부 전송은 없었음. |
| 12 | 긴 문장 번역 | SKIP | 실제 번역 Provider가 준비되지 않음. |
| 13 | 짧은 문장 번역 | SKIP | 실제 번역 Provider가 준비되지 않음. |
| 14 | 숫자, 날짜, 시간 보존 | SKIP | 실제 출력 품질 검증은 하지 않음. OpenAI 지시문 구성은 자동 테스트 PASS. |
| 15 | MK119 등 용어 보존 | SKIP | 실제 출력 품질 검증은 하지 않음. 공통 용어집·OpenAI 지시문·로컬 placeholder 복원은 자동 테스트 PASS. |
| 16 | 로컬 모델 설치 상태 표시 | MANUAL PASS | UI에서 로컬 모델을 선택해 `미설치/사용 불가` 사유와 비활성 적용 버튼을 확인. 서버와 원문 기능은 계속 정상. |
| 17 | 실제 로컬 번역 | SKIP | `LOCAL_TRANSLATION_MODEL`과 선택 tokenizer 의존성이 설치되지 않음. 앱은 자동 다운로드하지 않음. |
| 18 | 실제 OpenAI 번역 | SKIP | `OPENAI_API_KEY`, `RUN_OPENAI_LIVE_TEST=1`, 명시적 `OPENAI_TRANSLATION_MODEL`이 모두 없음. 유료 호출 0건. |
| 19 | 20개 이상 발화 연속 처리 | SKIP | 실제 음성+Provider 수동 실행은 하지 않음. 비과금 fake Provider benchmark 20건은 전부 완료됨. |
| 20 | 번역 결과의 segment 매칭 | SKIP | 실제 번역 결과를 수동 화면에서 만들지 않음. 역순 완료·지연 이벤트 매칭 자동 테스트는 PASS. |

## 추가 실제 UI·런타임 확인

| 항목 | 상태 | 결과 |
|---|---|---|
| OpenAI 키 미설정 표시 | MANUAL PASS | `설정되지 않음`, 외부 전송 경고, 비활성 적용/테스트 버튼 확인. 키 입력 필드는 0개. |
| 실제 캡처 시작/중지 | MANUAL PASS | `중지됨 → 수신 중 → 중지됨`; 시작/중지 버튼 상태가 정상 전환되고 오류 메시지 없음. |
| WebSocket | MANUAL PASS | 연결됨 상태와 snapshot 수신 확인. |
| 390×844 반응형 | MANUAL PASS | 가로 overflow 없음, 번역 선택기와 시작 버튼 존재, API 키 입력 필드 없음. |
| 브라우저 콘솔 | MANUAL PASS | 캡처 시작/중지 및 Provider 선택 확인 후 오류 로그 0건. |

## 실행 근거

```text
GET http://127.0.0.1:8765/api/health
브라우저: http://127.0.0.1:8765/
캡처: 시스템 음성 / 기본 Realtek Speaker WASAPI Loopback / small
자동 회귀: .venv\Scripts\python.exe -m pytest -q
비과금 부하: .venv\Scripts\python.exe scripts\benchmark_phase2_translation.py
```

- 실제 OpenAI 호출: SKIP — 키·실행 플래그·명시적 모델 없음.
- 실제 로컬 모델 호출: SKIP — 모델 경로·실행 플래그 없음.
- 오류 요약: 브라우저 모바일 full-page 이미지가 자동화 캡처에서 일부 잘려 보였지만, 390×844 DOM 측정은 `scrollWidth <= clientWidth`, 주요 컨트롤 존재, 콘솔 오류 0건이었다. 기능 판정은 DOM과 일반 viewport 이미지 기준으로 수행했다.
