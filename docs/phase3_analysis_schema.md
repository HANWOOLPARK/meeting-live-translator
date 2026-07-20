# Phase 3 회의 분석 스키마

## 범위와 원칙

Phase 3 분석은 저장된 `final_transcript` segment만 입력으로 사용한다. partial transcript, 오디오, 환경변수, API 키, 내부 경로는 분석 입력이나 결과에 포함하지 않는다. 기본 공급자는 `none`이고 자동 분석은 기본적으로 꺼져 있다. 페이지 조회와 세션 목록 조회는 외부 요청을 발생시키지 않는다.

설치된 OpenAI Python SDK 2.45.0과 공식 Structured Outputs 문서를 확인한 결과, 비동기 Responses API의 `responses.parse(..., text_format=PydanticModel)`를 사용할 수 있다. OpenAI 공급자는 이 구조화 출력 경로를 사용하며 SDK의 자동 재시도는 끄고 애플리케이션의 제한된 재시도 정책만 적용한다.

## 결과 구조

저장 파일은 세션 폴더의 `analysis.json`이며 UTF-8 JSON, `schema_version: 1`을 사용한다. `SESSION_SAVE_ANALYSIS=false`인 세션은 결과를 디스크에 저장하지 않는다.

```json
{
  "schema_version": 1,
  "session_id": "2026-07-11_14-30-15_ab12cd",
  "provider": "rule_based",
  "model": null,
  "status": "completed",
  "generated_at": "2026-07-11T15:26:30+09:00",
  "revision": 1,
  "meeting_purpose": {
    "text": "미정",
    "evidence_segment_ids": []
  },
  "key_discussions": [],
  "decisions": [],
  "action_items": [
    {
      "task": "System Test 일정표를 확인한다.",
      "assignee": "미정",
      "due_date": "미정",
      "evidence_segment_ids": ["seg-014"]
    }
  ],
  "open_questions": [],
  "next_meeting_checks": [],
  "warnings": []
}
```

`meeting_purpose`는 `{text, evidence_segment_ids}` 객체다. `key_discussions`, `decisions`, `open_questions`, `next_meeting_checks`는 같은 형태의 객체 배열이다. `action_items`는 `{task, assignee, due_date, evidence_segment_ids}` 배열이다. `warnings`에는 검증·병합 과정에서 확인된 안전한 경고 코드 또는 설명만 넣고 원문 전체나 공급자 원시 오류를 넣지 않는다.

`generated_at`과 세션의 모든 시간은 timezone을 포함한 ISO 8601 문자열이다. `revision`은 성공 결과를 교체할 때 증가한다. 재분석 중에는 이전 성공 파일을 보존하고, 새 분석이 성공한 뒤에만 atomic replace한다.

## 상태 모델

분석 상태는 다음 값만 사용한다.

```text
not_started -> pending -> running -> completed
                              |----> failed
                              |----> cancelled
```

재시도는 `failed` 또는 `cancelled`에서 `pending`으로 돌아간다. 이전 성공 결과가 있는 재분석은 새 실행 상태와 기존 결과를 별도로 유지한다. 실패·취소 시 기존 성공 결과를 삭제하거나 Markdown 내보내기에서 제거하지 않는다.

## evidence 규칙

- 모든 `evidence_segment_ids`는 분석 입력 세션에 실제로 존재하는 final segment ID여야 한다.
- 존재하지 않는 ID가 하나라도 있으면 해당 ID만 제거하지 않고 chunk 또는 최종 응답 전체를 검증 실패로 처리한다.
- evidence 없는 결정, Action Item, 질문, 논의 항목은 만들지 않는다.
- 회의 목적이 명확하지 않으면 `미정`과 빈 evidence를 허용한다.
- 번역은 참고 자료일 뿐이며 원문과 충돌하면 원문을 우선한다.
- 원문 전체를 결과에 반복하지 않고, UI는 evidence ID를 원문 카드 위치로 연결한다.

## 담당자와 기한 정책

- 사람 이름이나 명시적인 고유 팀명이 원문에 분명히 연결된 경우에만 담당자로 기록한다.
- `we`, `they`, `우리`, `저희`, `담당팀`, 대명사처럼 지시 대상이 불명확하면 `미정`이다.
- 명시적인 날짜·시간·상대 기한 표현만 원문 그대로 기록한다.
- `빠른 시일 내`, `나중에`, `가능한 한 빨리`처럼 모호한 표현은 `미정`이다.
- `다음 주`와 같은 상대 날짜를 임의의 절대 날짜로 변환하지 않는다.
- 회사명, 인명, 날짜, 숫자, 제품명은 추측하거나 보정하지 않는다.

## chunking

입력 segment는 `started_at`, `ended_at`, 원본 이벤트 순서, `segment_id` 순으로 정렬한다. 기본 제한은 chunk당 100 segment 및 24,000문자이며 두 제한 중 먼저 도달하는 지점에서 분할한다.

- segment 경계를 유지하고 segment 내부 문장을 자르지 않는다.
- 단일 segment가 문자 제한보다 길어도 내용을 자르지 않고 단독 chunk로 처리하며 경고를 남긴다.
- 각 chunk에는 segment ID, 시간, 언어, 확정 원문과 저장된 경우 한국어 번역만 전달한다.
- 분석 동시성은 기본 1이며 timeout은 60초, 애플리케이션 재시도는 기본 1회다.

## 병합

Chunk 결과는 원래 chunk 순서대로 병합한다.

- 공백·대소문자·문장부호를 보수적으로 정규화한 키로 동일 결정을 중복 제거한다.
- 같은 방식으로 동일 Action Item을 중복 제거한다. Action Item은 task가 같을 때 합치며 명시성이 더 낮은 담당자·기한으로 추측해 채우지 않는다.
- 중복 항목의 evidence ID는 입력 순서를 유지해 합친다.
- 동일 주제에 대해 긍정/부정 등 서로 충돌하는 결정은 하나로 합치지 않고 모두 보존하며 `conflicting_decisions` 경고를 추가한다.
- `meeting_purpose`는 명확한 evidence가 있는 첫 유효 항목을 사용하고, 없으면 `미정`이다.
- 병합 후 전체 결과에 대해 다시 evidence 검증과 담당자·기한 보수화를 수행한다.

## 검증 실패 정책

다음은 안전한 `INVALID_RESPONSE` 또는 동등한 분석 오류로 처리한다.

- 빈 응답 또는 구조화 결과 없음
- 필수 필드 누락, 허용되지 않은 추가 필드, 잘못된 타입
- 세션 ID 불일치 또는 완료 상태가 아닌 성공 결과
- 존재하지 않는 evidence segment ID
- 원문 없이 생성된 결정·Action Item 등 근거 규칙 위반

원시 SDK 응답, 전체 요청, traceback, API 키는 파일·API·WebSocket·로그에 기록하지 않는다. 검증 실패는 분석 작업만 실패시키며 세션 원문, 번역, 기존 내보내기 및 이전 성공 분석은 유지한다.

## 공급자별 제한

### none

외부 호출과 생성 작업을 하지 않는다. 세션 저장·복원·내보내기는 계속 작동하며 UI에는 분석하지 않음으로 표시한다.

### rule_based

외부 API나 생성형 로컬 모델을 사용하지 않는다. 일본어·영어·한국어의 명시적인 결정 표현, 요청/할 일 표현, 질문만 보수적으로 추출한다. 생성형 요약을 흉내 내지 않으며 회의 목적은 기본 `미정`, 주요 논의는 확실하지 않으면 비워 둔다. 키워드 존재만으로 담당자나 결정을 확정하지 않는다.

### openai

`OPENAI_API_KEY`와 `OPENAI_ANALYSIS_MODEL`이 모두 명시된 경우에만 사용 가능하다. 저장된 확정 원문과 번역이 외부 서버로 전송될 수 있으므로 UI에 회사 보안정책과 참가자 동의 확인 안내를 표시한다. 사용자의 분석 생성 또는 명시적인 자동 실행 설정 없이는 호출하지 않는다. 모델 기능을 추측하지 않고 설치 SDK가 지원하는 Pydantic Structured Outputs를 사용한다.
