# 근거 연결형 Decision Radar 구현 보고서

- 완료일: 2026-07-15~16 (Asia/Seoul)
- 구현 범위: final 원문 기반 실시간 회의 의사결정 보조, OpenAI/Gemini 선택, evidence 연결, 사용자 검토
- 최종 판정: **자동 회귀 및 브라우저 검증 PASS** — 실제 유료/외부 API 호출은 SKIP

## 1. 구현 결과

Decision Radar는 Deepgram의 확정 `final` 원문만 받아 기본 10개 문장 또는 최대 20초
단위로 분석한다. 각 요청에는 새 묶음과 함께 직전 최대 16개 final의 rolling context를
제공하고, 새 묶음은 `focus_segment_ids`로 별도 표시한다. 다음 네 종류를 별도의 실시간
카드로 만든다.

- 결정 사항
- 담당자·해야 할 일·기한이 포함된 Action Item
- 아직 해결되지 않은 질문
- 확인이 필요한 사람 이름·용어·번역

모든 생성 항목은 하나 이상의 `evidence_segment_ids`를 가져야 한다. 서버가 rolling
context의 실제 final ID와 다시 대조한다. 2026-07-17부터 한 응답에 실제 ID와 모델이
만든 잘못된 ID가 섞이면 잘못된 참조만 제거하고, 현재 focus의 실제 근거가 하나 이상
남는 항목은 수용한다. 실제 근거가 전혀 없거나 focus 근거가 없는 항목은 폐기하며,
응답 전체에서 안전하게 수용할 항목이 하나도 없으면 기존처럼 `INVALID_EVIDENCE`로
거부한다. 부분 폐기 건수는 diagnostics에 누적한다. UI의 근거 버튼은 해당 원문 카드로
이동한다.

2026-07-16 품질 검토에서 짧은 고정 묶음만 보면 인용된 조언, 조건부 기간 예상,
수사적 질문이 실제 Action 또는 미해결 질문으로 승격될 수 있음을 확인했다. 다음
정밀도 우선 규칙을 OpenAI/Gemini 공통 prompt 계약에 추가했다.

- 명시적으로 확인된 참가자 합의만 결정으로 인정
- 명시적 미래 약속·업무 할당·채택된 다음 단계만 Action으로 인정
- 인용·전언·시청자 요청·예시·일반 조언·의견·제안·가정·조건·가능성·기간 예상 제외
- 실제 후속 확인이 필요한 회의 질문만 미해결 질문으로 인정하고 의미상 중복 금지
- 사람 이름·업무 용어·번역의 실질적 모호함만 `확인 필요`로 인정
- 문장이 중간에서 시작하거나 끝나면 약한 추론 대신 다음 묶음을 기다림
- 같은 업무의 수행과 결과 공유를 별도 Action으로 쪼개지 않고 하나로 병합
- 근거·선호·미채택 제안의 보류를 별도 결정으로 만들지 않음
- 위험·개선 의견을 명시적 미해결 선택 없이 질문으로 만들지 않음
- 인명·제품·업무 용어 철자 모호함은 미해결 질문이 아니라 `확인 필요`로 분류
- 근거에 이름이 없으면 1인칭 발화만으로 화자나 담당자를 추정하지 않음

## 2. Provider와 안전 경계

UI에서 `사용 안 함`, `OpenAI API`, `Gemini API`를 선택할 수 있다. Provider 목록 조회와 페이지 새로고침만으로는 외부 요청을 보내지 않으며, 사용자가 Provider를 적용한 뒤 final 묶음이 준비됐을 때만 분석을 요청한다.

- OpenAI: Responses API 구조화 출력, 비용 안전 기본 모델 `gpt-5.4-mini`
- Gemini: 공식 `google-genai` SDK 구조화 출력, 별도 Radar 모델 또는 기존 분석/번역 모델 fallback
- API 키: 서버 환경에서만 읽고 UI, diagnostics, WebSocket에 값 또는 일부 값을 노출하지 않음
- 입력: final 원문, 언어, 현재 rolling context에서 실제 매칭된 Context Engine 사람
  이름·용어 최대 10개. 활성 프로필 전체 목록은 반복 전송하지 않음
- 실패 격리: 인증·429·quota·timeout·잘못된 구조화 응답이 원문 전사, 번역, 세션 저장을 중단하지 않음

2026-07-16 Gemini 실사용 오류 조사에서 Radar가 엄격한 Pydantic 모델을 구형
`response_schema`로 전달해 `additionalProperties: false`가 포함된 요청이 400 계열로
거절될 수 있는 호환성 경계를 확인했다. Gemini 회의 분석과 Radar만 공식
`response_json_schema=<Payload>.model_json_schema()` 방식으로 통일했다. OpenAI의
Responses API `text_format` 경로는 변경하지 않았다. Gemini `INVALID_ARGUMENT`은
`INVALID_RESPONSE`, 무료 사용 불가 지역 등의 `FAILED_PRECONDITION`은
`PROVIDER_UNAVAILABLE`, 429 `RESOURCE_EXHAUSTED`는 `RATE_LIMITED`로 안전하게 분리한다.

2026-07-17 실제 장문 시험에서 번역 166회와 Radar 44회가 함께 발생하고 큰 Radar 모델의 반복 입력 비용이 집중되는 것을 확인했다. 반복 개발 시험의 기본값은 `gpt-5.4-mini`로 바꾸고, 최종 품질 시험에서만 `.env`를 통해 더 큰 모델을 명시적으로 선택하도록 했다. 모델 접근 가능 여부는 계정 권한과 시점에 따라 달라질 수 있다.

## 3. 상태와 데이터 보존

Radar 상태는 `data/decision_radar.json`에 atomic write로 별도 저장한다. 기존 `data/sessions/**/events.jsonl`과 legacy JSONL에는 Radar 이벤트를 append하거나 기존 줄을 수정하지 않는다.

사용자는 제안된 항목을 승인·수정·삭제할 수 있다. 삭제한 항목은 tombstone으로 기억해
같은 내용이 다음 분석에서 바로 다시 나타나는 것을 막는다. 모델은 새 rolling context가
기존 항목을 오탐·의미상 중복·해결된 질문으로 입증하면 `retract_item_ids`를 반환할 수
있다. 서버는 현재 상태에 실제로 존재하는 **미승인·미수정 제안**만 철회하며 사용자가
승인하거나 수정한 항목은 모델 응답과 무관하게 보존한다. WebSocket에는 상태 변경
알림만 보내고, 브라우저는 REST에서 최신 전체 상태를 다시 읽어 오래된 결과가 다른
세션이나 항목에 붙지 않도록 한다.

## 4. 지연과 장애 정책

- capture의 final 저장·broadcast가 먼저 끝난 다음 Radar queue에 비차단 제출한다.
- queue와 동시성은 제한돼 있으며 기본 분석 동시성은 1이다.
- queue가 가득 차면 Radar 분석만 drop하고 원문 경로에는 예외를 전파하지 않는다.
- timeout과 재시도 횟수는 제한돼 무한 재시도하지 않는다.
- 새 분석이 실패하면 이전 성공 항목을 유지하고 안전한 상태 코드만 표시한다.
- partial은 Radar로 전달하지 않아 문장이 바뀔 때마다 비용과 중복 항목이 생기는 것을 막는다.

## 5. 주요 변경 파일

- 신규 backend: `backend/app/decision_radar/`의 models, schemas, prompts, providers, manager
- 연결: `backend/app/config/settings.py`, `backend/app/services.py`, `backend/app/capture/controller.py`, `backend/app/api/schemas.py`, `backend/app/main.py`
- UI: `frontend/static/index.html`, `frontend/static/style.css`, `frontend/static/app.js`, `frontend/static/i18n.js`
- 설정·문서: `.env.example`, `README_KO.md`, `tests/decision_radar_manual_test_checklist.md`
- 자동 테스트: `tests/test_decision_radar.py`

후속 제품 통합에서 Provider 설정은 메인 카드에 유지하고 실제 결과만 표시하는
`/decision-radar` 분리 창을 추가했다. 이 창은 네 결과 그룹, 상태·세션·queue, 항목
승인·수정·삭제, 근거 이동만 제공한다. 일반 브라우저 pop-up과 Electron 네이티브 투명
항상 위 overlay를 모두 지원하며 상세 검증은 `docs/desktop_overlay_report.md`에 기록했다.

## 6. 검증 결과

```text
.venv\Scripts\python.exe -m pytest -q
285 passed, 3 skipped in 11.40s

node --check frontend/static/app.js
PASS

node --check frontend/static/i18n.js
PASS
```

3개 SKIP은 명시적 환경과 사용 승인이 필요한 기존 OpenAI 분석, OpenAI 번역, 로컬 번역 실사용 테스트다. Decision Radar의 실제 OpenAI/Gemini 호출도 API 키·quota·비용을 사용하므로 이번 자동 검증에서는 실행하지 않았다.

의미 판별·rolling context·철회·Gemini JSON Schema 관련 Radar 모의 묶음은 다음과
같이 별도 확인했다.

```text
.venv\Scripts\python.exe -m pytest -q tests\test_decision_radar.py
15 passed
```

실제 저장 세션의 내용은 출력하거나 문서에 기록하지 않고, 최신 시험의 166개 final을
오프라인으로 다시 묶었다. 이전 5개/10초/20 context 설정은 48회로 재현됐고 새
10개/20초/16 context 설정은 26회로 계산되어 호출 수 45.8%, 전체 요청 입력 문자 수
68.4% 감소를 확인했다. 이는 실제 기록된 과거 성공 batch 44회와도 가까운 추정이다.
`google-genai`의
`GenerateContentConfig`로 새 `retract_item_ids` 필수 JSON Schema를 네트워크 없이
구성하는 검사도 PASS였다. 실제 Gemini 생성 요청은 실행하지 않았다.

설치된 Microsoft Edge와 Playwright로 localhost UI를 확인했다.

- 1440px: 원문·번역·Radar 3열 정렬
- 1024px: 자막 2열 아래 Radar 전체 폭
- 760px: 단일 열, 수평 overflow 없음
- 영어 UI와 Provider 세 옵션 표시
- Gemini 선택 시 외부 전송 안내와 적용 버튼 활성화
- 새로고침 후 HTTP/console 오류 0건

최초 구현 당시 기존 세션 179개 파일을 정렬된 상대 경로와 개별 SHA-256으로 집계한
값은 작업 전후 모두 다음과 같았다.

```text
FD0D03ED08680FD5D1F4C138627997DE65C6EE2FC1265A9E7BAC368812948AB9
```

이후 사용자 테스트로 세션 산출물이 늘어난 상태에서 수행한 2026-07-16 의미 판별 개선은
작업 전후 모두 201개 파일, 다음 집계 SHA-256으로 동일했다.

```text
5001E02E416E6FB903A5C8914BF11AABA360F177228E3CC6351EA4111FC892D4
```

## 7. 남은 실제 검증

- 실제 OpenAI 및 Gemini 계정에서 모델 접근 가능 여부, latency, quota, 추출 품질
- 개선된 prompt/context로 비민감 일본어·영어 회의를 다시 분석한 결정/Action/질문
  precision·recall과 오탐 전후 비교
- 장시간 회의에서 queue 밀림과 500개 DOM 자막 보존 한계를 넘긴 과거 근거 이동 UX
- 화자 분리 정보가 없는 입력에서 담당자는 원문에 명시된 경우에만 신뢰할 수 있음

이 항목들은 미검증이며 PASS로 주장하지 않는다. 실행 절차는 `tests/decision_radar_manual_test_checklist.md`에 기록했다.
