# Meeting Live Translator Phase 3 완료 보고서

- 완료일: 2026-07-11 (Asia/Seoul)
- 구현 범위: Phase 3A 세션·복구·내보내기, Phase 3B 명시적 회의 분석
- 최종 판정: **PASS** — Phase 4는 시작하지 않음

## 1. Phase 1·2 기준선 검사

- Git: `ENVIRONMENT DIFFERENCE` — 작업 폴더는 Git 저장소가 아니다.
- 프로젝트 Python: 3.11.9.
- 기존 세션, `.env`, 사용자 용어집, 로컬 모델 폴더, Phase 1·2 문서를 삭제하거나 이름 변경하지 않았다.
- 작업 전 서버 PID 파일과 localhost:8765 listener는 없었다.
- 오디오 장치 읽기 전용 검사: output 11, WASAPI loopback 3, microphone 8, output-loopback pair 3.
- 기존 UUID JSONL 6개의 SHA-256을 작업 전후 비교했으며 모두 동일하다.

## 2. 작업 전 테스트 결과

```text
pytest: 93 passed, 2 skipped
compileall: PASS
JavaScript syntax: PASS
pip check: PASS
audio device strict check: PASS
```

두 SKIP은 명시적 환경변수가 필요한 Phase 2 OpenAI 번역 및 로컬 번역 실사용 테스트였다. Phase 3A 게이트는 `125 passed, 2 skipped`로 통과한 뒤에만 Phase 3B 구현을 시작했다.

## 3. Phase 3A 세션 아키텍처

새 세션은 `data/sessions/<session-id>/` 아래에 append-only `events.jsonl`, `manifest.json`, 완성된 `session.json`, 원문/번역 TXT, Markdown을 둔다. manifest와 파생 파일은 같은 디렉터리의 임시 파일에 쓰고 flush/fsync 후 `os.replace`한다. 운영 앱만 `phase3=True`를 사용하고, 기본 repository 생성자는 Phase 1·2 테스트를 위한 legacy 동작을 유지한다.

캡처·전사 표시와 파일 저장 실패를 분리했다. 저장 실패가 final 원문 브라우저 표시를 억제하지 않으며, 손상된 세션 하나가 전체 세션 목록을 막지 않는다.

## 4. Phase 3B 분석 아키텍처

`backend/app/analysis`에 공급자 인터페이스, strict 모델, 오류 분류, chunking, 병합, evidence 검증, 단일 동시성 manager를 구현했다. 분석은 final segment만 사용하며 partial transcript는 입력하지 않는다.

```text
명시적 submit/retry
→ pending → running
→ segment 경계 chunk
→ chunk별 구조화 분석
→ 보수적 병합·중복 제거
→ 전체 evidence 검증
→ atomic 저장·내보내기 갱신
→ completed | failed | cancelled
```

분석 페이지 조회, 공급자 목록 조회, 세션 목록 조회는 `analyze()`를 호출하지 않는다. 재분석 중 이전 성공 결과를 유지하고 새 성공 결과만 revision 증가 후 교체한다.

## 5. 생성한 파일

- `backend/app/analysis/`: `__init__.py`, `base.py`, `models.py`, `manager.py`, `none_provider.py`, `rule_based_provider.py`, `openai_provider.py`, `prompts.py`, `chunking.py`, `validation.py`, `exceptions.py`, `structured.py`.
- `backend/app/sessions/`: Phase 3 조립·내보내기·복구·manager·예외 모듈.
- `docs/phase3_plan.md`, `docs/phase3_session_schema.md`, `docs/phase3_analysis_schema.md`, `docs/phase3_report.md`.
- `scripts/benchmark_phase3_sessions.py`, `scripts/benchmark_phase3_analysis.py`.
- `tests/phase3_manual_test_checklist.md`.
- Phase 3 세션/API/UI/분석/실사용 opt-in 테스트 파일.

## 6. 수정한 파일

- 설정·API·서비스: `.env.example`, `backend/app/config/settings.py`, `backend/app/api/schemas.py`, `backend/app/services.py`, `backend/app/main.py`.
- lifecycle·저장 연결: `backend/app/capture/controller.py`, `backend/app/sessions/models.py`, `backend/app/sessions/repository.py`, `backend/app/sessions/__init__.py`, `backend/app/websocket/manager.py`.
- UI: `frontend/static/index.html`, `frontend/static/app.js`, `frontend/static/style.css`.
- 문서·운영 안내: `README_KO.md`, `AGENTS.md`.
- 기존 테스트 계약을 보존하면서 Phase 3 assertion을 추가했다.

## 7. 세션 lifecycle

```text
created → running ⇄ paused → stopping → finalizing → completed
                                      ↘ recovered
                                      ↘ error
```

캡처 상태와 세션 상태는 별도다. stop은 마지막 final 처리 후 finalize하고 active session ID를 해제한다. 재-finalize는 이벤트를 append하지 않고 같은 이벤트 원본에서 파생 파일만 다시 만들어 idempotent하다.

## 8. 기존 JSONL 호환 방식

- 루트 `<uuid>.jsonl`을 authoritative legacy 원본으로 읽는다.
- 원본 파일을 수정·이동·재작성하지 않는다.
- 필요할 때 같은 UUID의 파생 세션 폴더만 생성한다.
- 신규 Phase 3 세션은 기존 Phase 2 통합 소비자를 위해 루트 JSONL compatibility mirror도 append한다.
- 최종 SHA-256은 다음과 같이 기준선과 동일하다: `49D9…B07C`, `8FD1…CA76`, `B0B3…C7AA`, `6263…B2D2`, `33D6…DA36`, `E0F2…3ED6`.

## 9. 세션 복구 방식

서버 시작 시 auto-recover가 켜져 있으면 Phase 3 디렉터리의 `created/running/paused/stopping/finalizing` 또는 완성본 누락 세션만 대상으로 한다. events의 malformed 한 줄은 `파일명:행:malformed_json` 안전 경고로 건너뛰고 정상 행을 복구한다. 종료 시각을 알 수 없으면 추측하지 않고 `null`을 유지한다. Legacy JSONL은 startup에서 임의 변환하지 않는다.

## 10. JSON 내보내기

`session.json` schema version 1에 공개 metadata, 시간순 segment, 최신 성공 번역 또는 최종 실패 상태, 선택적 분석, 안전 경고를 저장한다. API 키, Authorization, traceback, 절대 경로는 포함하지 않는다. 다운로드 파일명은 검증된 session ID와 고정 suffix만 사용한다.

## 11. TXT 내보내기

- `transcript_original.txt`: 저장된 확정 원문만 시간순 표시.
- `transcript_korean.txt`: 성공한 한국어 번역만 표시하고 전체/성공/미번역·실패 개수를 기록.
- 저장 OFF인 내용은 파일에 남기지 않고 저장하지 않았다는 상태만 유지한다.

## 12. Markdown 내보내기

회의 기본 정보, 목적, 주요 논의, 결정, Action Items 표, 미해결 질문, 다음 회의 확인, 전체 원문·번역 기록을 포함한다. 분석 전에는 `분석이 아직 생성되지 않았습니다.`라고 명시한다. 분석 성공 시 `analysis.json`을 반영해 Markdown을 atomic하게 다시 만든다.

## 13. 구현한 분석 Provider

- `none`: 분석하지 않음, 외부 호출 없음.
- `rule_based`: 외부 모델 없는 보수적 일본어·영어·한국어 signal 추출.
- `openai`: 공식 비동기 SDK Responses API Structured Outputs, 주입 가능한 mock client.

공급자 switching은 가용성을 확인하며 진행 중 작업을 안전하게 취소한다. OpenAI model 또는 API key가 없으면 앱 시작은 성공하고 해당 공급자만 unavailable이다.

## 14. 규칙 기반 분석 동작

명시적인 `decided/agreed/決定/決まりました/결정했습니다`, Action Item·담당·요청·확인 표현, 질문 표현만 추출한다. 제안과 영어 부정 결정은 결정으로 확정하지 않는다. 불명확한 actor와 vague due는 `미정`, 명시적 `by next week/다음 주까지/来週まで`는 절대 날짜로 변환하지 않고 원문 표현을 보존한다. 회의 목적은 기본 `미정`, 주요 논의는 생성하지 않는다.

브라우저 합성 테스트 결과는 결정 1, Action Item 1(`Alice`, `by next week`), 질문 2, purpose `미정`, evidence 연결 성공이었다. PowerShell pipe로 만든 일본어 fixture 한 줄은 콘솔 인코딩이 손실되어 일본어 실사용 판정에는 사용하지 않았고, 다국어 정확성은 Unicode 자동 테스트로만 PASS 처리했다.

## 15. OpenAI 분석 방식

설치된 `openai 2.45.0`의 `AsyncOpenAI.responses.parse(..., text_format=AnalysisResponsePayload)` 지원을 실제 signature로 확인했다. Pydantic `extra="forbid"` 모델로 `output_parsed`를 검증하고 `store=False`, SDK `max_retries=0`을 사용한다. timeout과 제한된 재시도는 manager 한 계층에서만 담당한다.

참고한 공식 문서: [Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Text generation](https://developers.openai.com/api/docs/guides/text), [Models](https://developers.openai.com/api/docs/models).

## 16. evidence 검증

목적이 `미정`인 경우를 제외한 모든 결과 항목은 하나 이상의 evidence ID가 필요하다. 모든 ID를 실제 입력 final segment 집합과 대조한다. 존재하지 않는 ID, 빈 evidence, session/provider 불일치, 잘못된 schema/version/timezone, 추가 필드가 하나라도 있으면 해당 값만 삭제하지 않고 전체 응답을 실패 처리한다.

중복 항목은 normalized text/task 기준으로 합치고 evidence 순서를 보존한다. 서로 다른 담당자·기한 또는 충돌 가능 결정은 추측해 하나로 만들지 않고 `미정` 또는 warning으로 보존한다.

## 17. UI 변경사항

- 현재 세션 정보·저장 설정, 과거 세션 목록·복원, 전체 원문/번역 복사, 4종 다운로드.
- 분석 공급자 설정, 자동 분석 toggle, 생성·취소·재시도, 상태 badge와 REST polling/WS 동기화.
- 목적·논의·결정·Action Item·질문·다음 확인·경고 영역.
- evidence 버튼 클릭 시 exact `segment_id` 카드 scroll/focus.
- OpenAI 비용·외부 전송·회사 보안정책·회의 참가자 동의 경고.
- Clipboard API가 지연되면 1.5초 후 fallback하고 성공 또는 읽을 수 있는 오류를 표시.
- 원문 저장 OFF + 번역 저장 ON segment도 복원 가능.
- 375px 실제 client width에서 수평 overflow 없음.

## 18. API 변경사항

세션 목록·상세·segment·finalize·recover·4종 download 및 session storage settings를 추가했다. 분석 API는 다음과 같다.

```text
GET/POST /api/analysis/settings
GET      /api/analysis/providers
GET/POST /api/sessions/{session_id}/analysis
POST     /api/sessions/{session_id}/analysis/cancel
POST     /api/sessions/{session_id}/analysis/retry
```

Health의 기존 `phase: 2`는 Phase 2 소비자 호환을 위해 유지하고 `current_phase: 3`, `version: 0.3.0-phase3`를 추가했다.

## 19. WebSocket 변경사항

기존 전사·번역 이벤트를 유지하면서 `session_created/status/finalized/recovered`와 `analysis_pending/status/completed/error/cancelled`를 추가했다. 분석 완료 이벤트에는 session ID, provider, generated time, revision만 넣고 큰 결과 본문은 REST로 조회한다. 초기 snapshot은 공개 분석 설정과 키 존재 여부 boolean만 포함한다.

## 20. 보안 확인사항

- 기본 bind `127.0.0.1`, `.env`와 `data/sessions` Git ignore 유지.
- API key 값은 API, WebSocket, 로그, manifest, analysis, Markdown에 노출되지 않음.
- OpenAI 전체 요청·응답, raw exception, traceback, 내부 절대 경로를 공개 응답에 넣지 않음.
- path traversal, 절대/상대 탈출, 제어문자, 64자 초과, Windows 예약명 차단.
- partial transcript 분석 금지, 오디오 저장 기능 없음.
- OpenAI 선택과 실행은 별도이며 페이지 조회만으로 외부 호출하지 않음.
- 테스트는 합성·비민감 내용만 사용하고 종료 후 합성 session folder/mirror를 삭제했다.

## 21. 자동 테스트 결과

```text
pytest: 187 passed, 3 skipped in 2.17s — PASS
Python compileall backend/scripts: PASS
JavaScript syntax (Node v24.14.0): PASS
pip check: No broken requirements found — PASS
audio device strict check: PASS
```

3 SKIP은 조건이 없는 live OpenAI 분석, live OpenAI 번역, live 로컬 번역이다. 분석 코어 40개 이상은 mock/fake로 공급자 성공·실패, 인증/rate limit/timeout/network, 빈/잘못된 구조, evidence, 보수화, chunk/merge, cancel/retry, 이전 결과, shutdown, submit race를 검증한다.

## 22. 수동 테스트 결과

- `MANUAL PASS` 9개: 브라우저 새로고침 복원, 서버 재시작 복원, 전체 원문 Clipboard, 규칙 기반 분석, 질문 추출, evidence 이동, OpenAI 키 없이 로컬 분석, OpenAI 경고, 모바일 overflow.
- 브라우저 console error: 0.
- 번역 없는 합성 세션에서 전체 번역 복사는 `클립보드 복사 실패: 복사할 번역이 없습니다.`라는 읽을 수 있는 오류를 확인했지만 성공 복사 테스트가 아니므로 체크리스트는 `SKIP`이다.
- 실제 오디오, 실제 번역, 실제 OpenAI, 다운로드 클릭, 30~60분 세션, `stop_all.bat`은 수행하지 않아 `SKIP`이다.

## 23. 세션 크기별 benchmark

각 크기 3회, 비민감 synthetic data, 단위 ms·peak MiB다.

| segments | assemble median | JSON median | Markdown median | finalize median | peak max MiB |
|---:|---:|---:|---:|---:|---:|
| 10 | 1.331 | 3.365 | 2.384 | 18.013 | 0.131 |
| 100 | 7.481 | 11.366 | 6.427 | 48.526 | 0.919 |
| 500 | 35.636 | 43.286 | 27.257 | 184.187 | 4.482 |
| 1000 | 74.501 | 84.836 | 52.886 | 361.761 | 8.933 |

결과 원본은 `work/phase3_session_benchmark.json`이다. 1000개 segment finalize도 이 환경에서 0.4초 미만 median이었다.

## 24. 분석 처리 지연

`scripts/benchmark_phase3_analysis.py --iterations 3`으로 rule-based의 chunk→병합→evidence 검증 전체를 측정했다.

| segments | chunks | median ms | p95 ms | peak max MiB |
|---:|---:|---:|---:|---:|
| 10 | 1 | 0.944 | 1.330 | 0.008 |
| 100 | 1 | 8.677 | 9.450 | 0.046 |
| 500 | 5 | 51.574 | 51.881 | 0.181 |
| 1000 | 10 | 106.722 | 108.235 | 0.273 |

OpenAI 지연은 실제 요청을 실행하지 않아 `SKIP`이다.

## 25. OpenAI 실사용 여부

**SKIP. 실제 OpenAI 요청과 과금은 발생하지 않았다.** 최종 환경은 `OPENAI_API_KEY` 미설정, `RUN_OPENAI_ANALYSIS_LIVE_TEST=1` 미설정, `OPENAI_ANALYSIS_MODEL` 미설정, 프로젝트 `.env` 없음이었다. 세 조건을 모두 명시해야 live test가 실행된다.

## 26. 발견한 버그

구현·리뷰 중 다음을 수정했다.

- legacy derived folder가 있을 때 events와 root JSONL source 선택 오류.
- session WebSocket 이벤트의 `final` 문자열이 일반 final transcript handler로 들어가던 문제.
- 분석 저장 toggle 누락과 translation-only 복원 누락.
- final 저장 실패가 브라우저 final 표시를 억제할 수 있던 문제.
- Clipboard API promise가 권한 환경에서 오래 pending될 수 있던 문제.
- 분석 saved `generated_at` 손실, 동시 submit race, 늦은 wait, immediate cancel/shutdown 상태.
- 질문의 Action Item 오탐, 영어 부정 결정 오탐, 중복 Action metadata 충돌, purpose evidence 병합.
- OpenAI 구조 검증 오류와 unknown evidence의 안전한 오류 분류.

## 27. 알려진 제한사항

- 규칙 기반 분석은 생성형 요약이 아니며 purpose와 주요 논의를 적극 생성하지 않는다.
- UI에서 바꾼 분석 공급자·자동 분석 설정은 현재 서버 프로세스 동안만 유지되고 재시작 시 `.env` 설정으로 돌아간다.
- 실제 OpenAI 모델별 품질·비용·지연은 검증하지 않았다.
- 실제 일본어/영어 오디오, 장시간 회의, 번역 성공이 섞인 브라우저 세션은 수동 미검증이다.
- 앱은 과거 세션을 임의 삭제하지 않으며 별도 세션 삭제 UI는 없다.
- 화자 분리, 오디오 저장/재생, 시스템+마이크 동시 전사 등 제외 범위는 구현하지 않았다.

## 28. 사용자가 확인해야 할 사항

1. 실제 Zoom/Windows 출력과 같은 WASAPI Loopback으로 30~60분 비민감 회의를 테스트한다.
2. 일본어·영어 final, pause/resume, stop finalize, 4종 브라우저 다운로드와 번역 Clipboard를 확인한다.
3. 회사 회의에서 OpenAI를 쓰기 전에 회사 보안정책과 참가자 동의를 확인하고 `.env`에 키와 분석 모델을 직접 설정한다.
4. 실제 OpenAI test를 원할 때만 `RUN_OPENAI_ANALYSIS_LIVE_TEST=1`을 일시적으로 설정한다.
5. `stop_all.bat`의 PID 정리는 실제 운영 시작/종료 흐름에서 확인한다.
6. 저장 데이터가 필요 없으면 앱이 아니라 사용자가 `data/sessions`에서 대상 세션을 검토 후 직접 삭제한다.

## 29. Phase 4에서 진행할 내용

Phase 4는 이번 작업에서 시작하지 않았다. 별도 승인 후에만 화자 분리·화자 이름 정책, 시스템 음성+마이크 동시 처리, overlay/media caption, 오디오 관련 기능, 고급 로컬 LLM 분석 또는 배포·다중 사용자 기능을 요구사항 기준으로 재검토한다.
