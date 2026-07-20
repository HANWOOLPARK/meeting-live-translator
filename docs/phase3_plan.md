# Meeting Live Translator Phase 3 구현 계획

- 작성일: 2026-07-11 (Asia/Seoul)
- 기준: Phase 1·2 완료 프로젝트와 Phase 3 구현 요청
- 구현 순서: Phase 3A 세션·내보내기 → 3A 전체 테스트 통과 → Phase 3B 회의 분석

## 1. 기준선

작업 전 실제 결과:

```text
Git: ENVIRONMENT DIFFERENCE — 저장소가 아님
Python: 3.11.9
pytest: 93 passed, 2 skipped
compileall backend: PASS
JavaScript syntax: PASS
pip check: PASS
audio devices strict: PASS (output 11 / loopback 3 / microphone 8)
server PID: 없음
```

두 SKIP은 Phase 2의 opt-in OpenAI/로컬 번역 실사용 테스트다. 기존 `data/sessions`, JSONL, `.env`, 사용자 용어집, 모델, 보고서를 보존한다.

## 2. Phase 3A 설계

### 저장 경계

- 회의 중에는 final/translation 이벤트를 append-only `events.jsonl`에 기록한다.
- 기존 `data/sessions/<uuid>.jsonl`은 수정·이름 변경하지 않고 legacy 입력으로 읽는다.
- 신규 세션은 검증된 session ID의 독립 디렉터리를 사용한다.
- manifest와 완성본은 같은 디렉터리의 임시 파일에 쓰고 flush/fsync 후 `os.replace`한다.
- 저장 오류는 해당 세션 경고/오류로 격리하며 서버와 실시간 전사를 종료하지 않는다.

### lifecycle

```text
created → running ⇄ paused → stopping → finalizing → completed
                                      ↘ recovered
                                      ↘ error
```

캡처 상태와 세션 상태를 분리한다. stop은 마지막 final 저장을 기다린 뒤 세션을 finalize한다. 동일 세션 finalize는 idempotent하게 완성본을 다시 생성하되 이벤트를 중복 append하지 않는다.

### 조립과 호환

- final row와 translation row를 `segment_id`로 결합한다.
- segment는 `started_at`, `ended_at`, 원본 행 순서, `segment_id` 순으로 정렬한다.
- 번역 이벤트가 여러 개면 최신 성공을 선택한다.
- 성공이 없고 오류 이벤트만 있으면 오류 상태를 유지한다.
- malformed 행은 파일/행 번호를 포함한 경고로 건너뛰고 원본은 보존한다.
- 저장 설정 OFF는 디스크 산출물에만 적용하고 실시간 메모리/UI 흐름은 유지한다.

### 내보내기

- `session.json`: 공개 metadata, segment, 선택적 analysis를 가진 schema version 1.
- `transcript_original.txt`: 저장된 원문과 일관된 로컬 시간.
- `transcript_korean.txt`: 성공 번역만 표시하고 전체/성공/미번역 개수를 헤더에 기록.
- `meeting_report.md`: 분석 전에는 명시적으로 미생성 상태를 표시하고 전체 기록을 포함.
- 다운로드는 검증된 session ID만 받고 안전한 고정 파일명을 사용한다.

## 3. Phase 3A 테스트 게이트

요청된 세션 자동 테스트 1~30, 기존 93개 회귀, compileall, JS 구문, pip, 오디오 검사를 실행한다. 특히 다음을 별도 확인한다.

- legacy UUID JSONL 호환과 원본 hash 불변.
- path traversal, 절대 경로, 제어문자, Windows 예약명, 과도한 길이 거부.
- atomic replace 실패 시 기존 정상 완성본 유지.
- 손상된 세션 하나가 목록 전체를 막지 않음.
- server restart 후 목록/상세 복원.
- 10/100/500/1000 synthetic segment benchmark.

이 게이트가 실패한 상태에서는 Phase 3B 코드를 작성하지 않는다.

## 4. Phase 3B 설계

Phase 3A 통과 후에만 `analysis` 모듈을 추가한다.

- Provider: `none`, `rule_based`, `openai`.
- 기본 Provider와 자동 분석은 `none`/OFF.
- 규칙 기반 Provider는 명시적 Action Item·결정·질문만 보수적으로 추출하고 생성형 요약을 흉내 내지 않는다.
- OpenAI는 Phase 2의 공식 비동기 SDK/인증을 재사용한다.
- 외부 요청은 사용자가 분석 생성/재시도 API를 명시적으로 호출했을 때만 발생한다.
- segment 경계를 유지해 제한된 chunk로 나누고 기본 동시성 1로 순차 분석한다.
- 결과를 병합·중복 제거한 뒤 모든 evidence ID를 실제 segment 집합과 대조한다.
- 담당자/기한/목적이 불명확하면 `미정`, 상대 날짜는 그대로 유지한다.
- 재분석 실패 시 이전 성공 결과를 보존한다.
- 분석 취소와 서버 종료 시 active task를 안전하게 취소한다.

## 5. 보안

- localhost 기본 bind와 기존 `.gitignore` 유지.
- API 키 값, 내부 절대 경로, raw traceback, 환경 전체, OpenAI 요청·응답을 API/WS/파일에 저장하지 않는다.
- final만 분석하고 partial은 분석 입력에 포함하지 않는다.
- OpenAI 분석 선택/실행 전 외부 전송·회사 정책·참가자 동의를 UI에 표시한다.
- 세션 삭제는 자동화하지 않고 사용자가 프로젝트의 해당 세션 디렉터리를 직접 검토·삭제하도록 문서화한다.
- 오디오 저장과 대형 로컬 LLM 설치/다운로드는 구현하지 않는다.

## 6. 검증과 보고

- 실제 OpenAI 분석은 키, `RUN_OPENAI_ANALYSIS_LIVE_TEST=1`, 명시적 모델이 모두 있을 때만 실행한다.
- 조건이 없으면 `SKIP`이며 과금 요청을 만들지 않는다.
- `docs/phase3_session_schema.md`, `docs/phase3_analysis_schema.md`, `tests/phase3_manual_test_checklist.md`, `docs/phase3_report.md`를 작성한다.
- 수동으로 하지 않은 항목은 자동 테스트가 있어도 `MANUAL PASS`로 기록하지 않는다.
- Phase 4 기능은 구현하지 않는다.
