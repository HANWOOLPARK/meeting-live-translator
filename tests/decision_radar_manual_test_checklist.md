# 근거 연결형 Decision Radar 수동 테스트 체크리스트

자동 mock 테스트 결과를 수동 PASS로 대체하지 않는다. 실제로 수행한 항목만 `MANUAL PASS` 또는 `MANUAL FAIL`로 기록하고, 실제 음성·API 키·유료 호출이 필요한 미수행 항목은 `SKIP`으로 남긴다.

테스트 환경: Windows 11, Python 3.11, localhost 웹 UI  
실행일: 2026-07-15

| # | 항목 | 상태 | 확인 메모 |
|---:|---|---|---|
| 1 | 넓은 화면에서 원문·번역·Radar 3열 배치 | MANUAL PASS | 1440px에서 세 카드의 시작 위치와 높이 정렬 확인 |
| 2 | 태블릿 크기 반응형 배치 | MANUAL PASS | 1024px에서 Radar가 두 자막 카드 아래 전체 폭으로 배치됨 |
| 3 | 좁은 화면 수평 overflow 없음 | MANUAL PASS | 760px에서 단일 열 및 수평 overflow 없음 |
| 4 | 한국어/영어 UI 전환 | MANUAL PASS | 영어 전환 후 Provider·빈 상태·비활성 상태 문구 확인 |
| 5 | Provider 목록에 사용 안 함/OpenAI/Gemini 표시 | MANUAL PASS | 브라우저에서 세 옵션 확인 |
| 6 | Gemini 선택 시 외부 전송 안내 표시 | MANUAL PASS | 적용 전 안내가 나타나고 적용 버튼이 활성화됨 |
| 7 | 페이지 새로고침 후 오류 없음 | MANUAL PASS | HTTP 응답 오류와 브라우저 console 오류 0건 |
| 8 | partial은 Radar 분석에 전달되지 않음 | AUTOMATED PASS | `test_duplicate_final_and_partial_are_ignored` |
| 9 | final만 10개 또는 최대 20초 단위로 분석 | AUTOMATED PASS | manager batching 및 capture hook 테스트 |
| 10 | Context Engine의 매칭된 사람 이름·용어만 전달 | AUTOMATED PASS | 미사용 프로필 항목 제외와 공급자 요청 payload 검사 |
| 11 | OpenAI 구조화 출력과 evidence 검증 | AUTOMATED PASS | 정상 출력 수용, 혼합 응답의 잘못된 ID만 제거, 근거 없는 항목 거부 |
| 12 | Gemini 구조화 출력과 evidence 검증 | AUTOMATED PASS | OpenAI와 동일한 공통 부분 수용·차단 경계 적용 |
| 13 | 모든 항목에 실제 final 근거 ID 존재 | AUTOMATED PASS | 실제 focus 근거가 남는 항목만 수용하고 전부 무효면 전체 응답 거부 |
| 14 | 동일 final 중복 분석 방지 | AUTOMATED PASS | 같은 `segment_id` 재입력 무시 |
| 15 | 승인·수정·삭제 및 삭제 항목 재등장 방지 | AUTOMATED PASS | 상태 저장, tombstone, WebSocket 이벤트 확인 |
| 16 | Radar 실패 시 final 원문 저장·표시 유지 | AUTOMATED PASS | observer 예외를 주입해 저장과 broadcast 지속 확인 |
| 17 | queue 초과 시 원문 전사 유지 | AUTOMATED PASS | Radar만 drop하고 capture 경로에는 예외 전파하지 않음 |
| 18 | 별도 파일 저장 및 서버 재시작 복원 | AUTOMATED PASS | 임시 `decision_radar.json` atomic 저장·복원 확인 |
| 19 | 기존 세션 JSONL 변경 없음 | AUTOMATED PASS | 작업 전후 179개 파일 집계 SHA-256 동일 |
| 20 | API 키·로컬 경로가 diagnostics/WS/API에 없음 | AUTOMATED PASS | 공개 응답 직렬화 검사 |
| 21 | 실제 OpenAI Radar 분석 | SKIP | 키·요금이 발생하는 외부 호출은 명시적 승인 없이 실행하지 않음 |
| 22 | 실제 Gemini Radar 분석 | SKIP | 키·quota를 사용하는 외부 호출은 명시적 승인 없이 실행하지 않음 |
| 23 | 실제 일본어 회의 중 결정·Action·질문 추출 품질 | MANUAL FAIL (개선 전) | 로컬 샘플 대조에서 인용·조건 표현을 Action으로 승격한 오탐을 확인했으며 개선 후 재실행 필요 |
| 24 | 실제 영어 회의 중 결정·Action·질문 추출 품질 | SKIP | 비민감 실제 회의 또는 공개 샘플로 사용자 수동 확인 필요 |
| 25 | 근거 버튼으로 현재 자막 카드 이동 | SKIP | 실제 캡처 중 항목 생성 후 사용자 수동 확인 필요 |
| 26 | 직전 16개 final rolling context와 새 focus 구분 | AUTOMATED PASS | 연속 4개 묶음에서 context 상한·순서·focus ID 검사 |
| 27 | 뒤 문맥으로 미검토 오탐·중복 철회 | AUTOMATED PASS | 제안 Action은 제거하고 승인 항목은 보존하는 manager 검사 |
| 28 | 인용·일반 조언·조건·수사적 질문 의미 규칙 | AUTOMATED PASS | 공통 prompt 계약과 실제 오탐 지점의 context 신호 포함 여부 검사 |
| 29 | 존재하지 않거나 보호된 항목 철회 차단 | AUTOMATED PASS | Provider 경계에서 미등록 ID 거부, manager에서 승인·수정 항목 보호 |

## 수동 실사용 권장 순서

1. `.env`에 사용할 Provider의 키와 Radar 모델을 지정하고 `start_all.bat`을 실행한다.
2. UI에서 **Decision Radar → 분석 Provider**를 선택하고 외부 전송 안내를 확인한 뒤 적용한다.
3. 공개·비민감 일본어 또는 영어 음성을 재생한다.
4. partial은 원문 카드에서만 바뀌고, final이 쌓인 뒤 Radar 항목이 생성되는지 확인한다.
5. 각 근거 버튼이 실제 원문으로 이동하는지, 승인·수정·삭제가 새로고침 뒤에도 유지되는지 확인한다.
6. API 네트워크를 끊거나 quota 오류를 유도했을 때 원문·번역이 계속 표시되는지 확인한다.

## 안전 확인

- API 키와 실제 회사 회의 내용은 테스트 보고서·스크린샷·저장소에 남기지 않는다.
- OpenAI/Gemini 선택 시 final 원문 묶음과 그 문맥에서 실제 매칭된 제한된 Context Engine 용어·사람 이름이 외부 API로 전송될 수 있다.
- 미수행 실제 API 테스트와 실제 회의 테스트는 PASS로 기록하지 않는다.
