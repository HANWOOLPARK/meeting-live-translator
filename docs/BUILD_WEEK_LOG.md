# OpenAI Build Week 개발 기록

## 2026-07-18 — 자막·Decision Radar 동시 보기 높이와 내부 스크롤 개선

- 사용자 문제·관찰: 실제 회의 화면에서 왼쪽 자막 목록 높이가 짧아 빈 공간이 크게 남고, 오른쪽 Radar 항목은 아래로 길게 늘어나 페이지 전체를 스크롤해야 했다. 자막과 Radar를 동시에 살피기 어려웠다.
- 사용자와 함께 한 제품 결정: 데스크톱에서는 자막과 Radar 카드가 같은 화면 기준 높이를 사용하고, 두 목록은 각각 카드 내부에서 독립적으로 위아래 스크롤한다. 좁은 화면에서는 세로 배치를 유지하면서 화면 높이에 맞는 bounded 높이를 사용한다.
- Codex가 제안·구현한 내용: `--live-panel-height`를 뷰포트 기반 `clamp()` 값으로 추가해 두 카드를 같은 높이로 맞췄다. 자막의 기존 `max-height: 515px`와 Radar의 `max-height: 640px`를 제거하고 flex 자식의 `min-height: 0`, 내부 `overflow-y: auto`, overscroll 격리와 명확한 Radar 스크롤바를 적용했다. 정적 자산 cache-buster도 갱신했다.
- 변경 파일·컴포넌트: `frontend/static/style.css`, `frontend/static/index.html`, `tests/test_decision_radar.py`, `README_KO.md`, 본 기록.
- 검증 결과: Radar·정적 UI 대상 테스트 `28 passed`; 전체 회귀 `293 passed, 3 skipped in 14.10s`; `app.js` Node syntax check PASS. SKIP 3개는 명시적 live API·로컬 모델 실행 조건이 필요한 기존 항목이다. 실제 장시간 회의에서 다양한 화면 배율과 항목 수를 사용한 최종 사용성 확인은 남아 있다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자가 제공한 실제 화면을 기준으로 외부 페이지 스크롤과 두 내부 목록의 스크롤 경계를 분리하고, 높이 계약·반응형 규칙·회귀 검증을 함께 반영했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인해야 한다.

## 2026-07-18 01:07 KST — 참석자 자막 최신순 고정

- 사용자 문제·관찰: 참석자 사이트의 확정 자막이 아래로 누적되어 최신 문장을 보려면 계속 아래로 내려가야 했고, 그 과정에서 오른쪽 Decision Radar와 함께 보기 어려웠다.
- 사용자와 함께 한 제품 결정: 읽기 전용 참석자 화면에서는 최신 확정 자막을 항상 목록의 맨 위에 표시한다. 새 확정 자막이 오면 자막 목록 내부만 맨 위로 이동하며 페이지와 Radar의 위치는 움직이지 않는다. 현재 발화 partial은 기존처럼 확정 목록 위에 유지한다.
- Codex가 제안·구현한 내용: 공유 상태·저장 순서·근거 `segment_id`는 바꾸지 않고, 표시용 배열만 복사 후 역순으로 렌더링했다. 자막 revision마다 내부 스크롤을 `top: 0`으로 맞췄다. 사용자가 과거 자막을 읽는 중에도 다음 확정 자막이 오면 최신 위치로 돌아가는 동작은 “항상 최신” 요구에 따른 의도된 동작이다.
- 변경 파일·검증: `viewer-site/app/room/[roomId]/viewer-room.tsx`, `viewer-site/tests/rendered-html.test.mjs`, `README_KO.md`, `docs/live_share_report.md`, 본 기록. viewer-site ESLint는 경고 없이 통과했고, production build와 3개 계약 테스트도 통과했다. secret scan과 diff 검사도 통과했으며, Sites source 커밋 `a9ee5e5`를 push하고 owner-only 비공개 버전 3으로 배포했다. 기존 세션·JSONL은 읽거나 수정하지 않았다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자 관찰을 자막 목록의 표시 순서와 스크롤 범위 문제로 분리하고, Radar 데이터·공유 범위·보관 정책을 변경하지 않는 최소 변경으로 구현·검증·비공개 Sites 갱신까지 수행했다.

이 문서는 OpenAI Build Week 제출을 위한 규정 준수 기록, 사전 프로젝트와
Submission Period 중 신규 작업의 구분, 사용자와 Codex의 협업 결정, 검증 증거를
한곳에 누적한다. 비밀키, 개인 음성, 원문 세션 내용은 기록하지 않는다.

마지막 규정 확인: 2026-07-15 15:39 KST  
공식 기준 문서: <https://openai.devpost.com/rules>  
공식 개요: <https://openai.devpost.com/>

## 1. 규정 요약과 준수 게이트

아래는 작업 편의를 위한 요약이다. 충돌할 경우 항상 공식 규정이 우선한다.

| 항목 | 확인 내용 | 현재 상태 |
|---|---|---|
| 권장 트랙 | Work & Productivity | 잠정 결정 |
| Submission Period | 2026-07-13 09:00 PT ~ 2026-07-21 17:00 PT | 진행 중 |
| 한국 시각 마감 | 2026-07-22 09:00 KST | 확인 |
| 기존 프로젝트 | 기간 중 Codex/GPT-5.6로 의미 있게 확장한 부분만 평가 | 해당 |
| 전후 구분 증거 | 날짜가 찍힌 Codex 세션, 커밋 기록 또는 동등한 증거 | Codex 세션 있음, Git 없음 |
| 필수 개발 도구 | Codex와 GPT-5.6 | 사용자 제공 모델 선택 화면과 공개 공유 대화에서 GPT-5.6 Sol 사용 확인 |
| 설명 | 기능과 동작을 설명하는 영문 프로젝트 설명 | 미작성 |
| 데모 영상 | 공개 YouTube, 오디오 포함, 3분 미만, Codex/GPT-5.6 사용 설명 | 미제작 |
| 저장소 | 공개 저장소 또는 지정 심사 계정과 공유한 비공개 저장소 | 미준비 |
| README | 설치·실행·샘플·Codex 협업 및 의사결정 설명 | 한국어 실행 문서만 있음 |
| Codex Session ID | 핵심 기능을 만든 작업의 `/feedback` Session ID | 확보 필요 |
| 심사 접근 | 무료로 실행 가능한 빌드·데모·테스트 지침 | Lite ZIP은 있으나 심사용 경로 미완성 |
| 제출 언어 | 영어 또는 모든 자료의 영어 번역 | 영문 자료 필요 |
| 제3자 권리 | SDK/API 약관과 오픈소스 라이선스 준수 | 고지 문서 있음, 최종 감사 필요 |
| 영상 저작권 | 허가 없는 상표·음악·저작물 금지 | 자체 제작 샘플 사용 필요 |

대한민국은 공식 참가 가능 지역 목록에 포함된다. 참가자의 성년 여부, 이해관계
충돌 여부와 Devpost 등록 완료 여부는 코드로 확인할 수 없으므로 제출자가 직접
확인한다.

## 2. 심사 기준

Stage 1은 주제 적합성과 필수 도구 사용의 기본 실현 가능성을 pass/fail로 확인한다.
Stage 2의 네 항목은 동일 가중치다.

1. Technological Implementation: Codex를 얼마나 깊고 능숙하게 사용했는가,
   실제 동작하는 비단순 구현인가.
2. Design: 기술 PoC가 아닌 일관되고 완결된 제품 경험인가.
3. Potential Impact: 구체적인 실제 사용자 문제를 설득력 있게 해결하는가.
4. Quality of the Idea: 창의적이고 기존 개념과 차별화되며 문제를 깊이 이해했는가.

## 3. 사전 프로젝트 기준선

Submission Period 시작은 한국 시각 2026-07-14 01:00이다. 이 시각 전에 이미
존재했던 기능은 Build Week 신규 성과로 주장하지 않는다.

- Windows WASAPI Loopback/마이크 캡처와 로컬 Whisper 전사
- Phase 2 비동기 번역 큐와 none/local/OpenAI Provider
- Phase 3 세션 lifecycle, JSONL, 내보내기, 회의 분석
- M2M100 CTranslate2 로컬 번역 sidecar와 PID 기반 시작/종료
- Gemini 번역 Provider
- 초기 Deepgram 스트리밍 STT 연동

위 기능은 제품의 기반과 기술 난이도를 설명하는 맥락으로만 사용하고, 심사 대상
신규 작업과 명확하게 구분한다.

## 4. Submission Period 중 의미 있는 확장

파일 시각과 현재 Codex 작업 기록을 기준으로 확인된 항목이다. 최종 제출 전에는
커밋 또는 Codex Session ID와 연결한다.

| 시기(KST) | 사용자 문제·결정 | Codex와 함께 해결한 내용 | 검증 증거 |
|---|---|---|---|
| 2026-07-14 오전 | 다른 사람에게 복잡한 개발환경 없이 전달하고 싶음 | 비밀정보·세션·모델을 제외한 Lite ZIP, 설치 스크립트, 로컬 모델 선택 설치 흐름을 설계·구현 | `make_lite_release.bat`, `scripts/build_lite_release.ps1`, ZIP 내용/해시 검사 |
| 2026-07-14 오후 | 일본어뿐 아니라 영어→한국어 사용 범위를 확장하고 싶음 | STT·번역 방향 제약을 UI/API에 반영하고 Provider별 가능한 방향을 명시 | 방향별 테스트 및 설정 검증 |
| 2026-07-14 오후 | 자막만 별도 창으로 보고 투명도와 원문/번역 표시를 바꾸고 싶음 | 자막 pop-out, 투명도 조절, 원문만/번역만/모두 보기 제품 흐름 구현 | 프런트엔드 회귀 테스트 |
| 2026-07-14 오후 | 빠른 대화에서 partial/final 중복, 누락, 번역 큐 밀림과 연결 단절이 걱정됨 | partial은 화면 전용, final만 번역, segment_id 매칭, bounded queue/retry, Deepgram 재연결·최근 오디오 버퍼·진단 지표 구현 | 자동 테스트와 diagnostics 확인 |
| 2026-07-14 저녁 | 실제 YouTube 자막 체감 지연을 줄이고 싶음 | 같은 60~90초 구간을 스피커→WASAPI→Deepgram→Gemini로 전후 측정하고 Deepgram `Finalize` 4초 상한, 최초 연결 재시도, 송신 timeout 구현 | 30초 final 3→7개, 최장 청크 12.57→4.04초, 전체 `228 passed, 3 skipped` |
| 2026-07-15 | Build Week 참가와 협업 증거를 지속적으로 남기고 싶음 | 공식 규정 확인, 사전/신규 경계, 심사 위험, 개발 로그와 체크리스트 생성 | 이 문서와 Codex 작업 기록 |
| 2026-07-15 | 프로젝트 구상 초기부터 GPT-5.6로 의논했다는 근거와 차별화 방향을 확인하고 싶음 | 사용자 제공 모델 선택 화면에서 GPT-5.6 Sol·높은 추론 수준을 확인하고, 공개 공유 대화에서 초기 문제 정의와 Worksite/Adaptive Context Engine 설계를 확인. 공유 URL은 민감정보 검토 전 공개 저장소에 복사하지 않음 | 사용자 제공 화면 2개와 공개 공유 대화(보조 증거), 핵심 Codex `/feedback` Session ID는 별도 확보 필요 |
| 2026-07-15 16:39 | 현장 용어뿐 아니라 사람 이름을 보정하고, 회의에서 나온 후보는 동의를 받은 뒤 추가하고 싶음 | Worksite Context Engine 구현: 영속 프로필, 일반 용어/사람 이름, 오인식 별칭, 원문 보존형 단일-pass 정규화, Deepgram Nova-3 keyterm, 번역 glossary, 분석 normalized text, 승인/무시 추천 보관함, UI/API/diagnostics 통합 | 최종 전체 `236 passed, 3 skipped`. 브라우저에서 프로필 0→10 keyterm 전환, 가상 이름 등록·삭제, console error 0, 375px 가로 overflow 없음 확인 |
| 2026-07-15 17:08 | 등록 용어가 늘어날수록 페이지가 길어지고, OpenAI 외에 기존 Gemini 설정으로도 회의를 분석하고 싶음 | 등록 용어·추천 후보를 350px 키보드 접근 가능 스크롤 목록으로 변경. 공식 Google Gen AI SDK 기반 Gemini 분석 Provider, 엄격한 구조화 응답·근거 ID 검증·오류 격리, 설정/API/UI/개인정보 안내를 통합 | 전체 `247 passed, 3 skipped`. 격리 브라우저에서 10개 항목 `clientHeight 350 < scrollHeight 690`, `overflow-y:auto`, Gemini `사용 가능`, 모델 표시, 외부 전송 경고, 오류 overlay 없음 확인 |
| 2026-07-15 18:12 | 영문 심사 자료와 함께 실제 제품도 영어로 조작할 수 있어야 함 | 한국어 기본의 `한국어 / English` UI 전환, 새로고침 유지, 메인·자막 창 동기화, 정적·동적 상태/오류/확인창/템플릿 영문화를 구현. 원문·번역·사용자 Context·분석 본문은 변환하지 않음 | 전체 `252 passed, 3 skipped`. 실제 브라우저에서 양방향 전환, 새로고침 유지, 두 창 동기화, 영문 화면의 의도된 한국어 버튼 외 잔여 한글 0, 오류 overlay/수집 console error 0 확인 |

### 2026-07-15 Context Engine 구현 상세

- 사용자 문제/결정: 사람 이름을 일반 용어와 구분해 추가하고, 회의 후보는 자동
  학습하지 말고 사용자에게 추가 여부를 묻는다.
- Codex 구현: `backend/app/context_engine/`, Context REST/WS/diagnostics, Deepgram
  반복 `keyterm`, final 원문과 별도 `context_normalization` append event, 정규화된
  번역·분석 입력, 프로필/항목/추천 UI를 추가했다.
- 변경 파일: `backend/app/context_engine/*`, `backend/app/api/schemas.py`,
  `backend/app/services.py`, `backend/app/main.py`, `backend/app/capture/controller.py`,
  `backend/app/transcription/deepgram_stream.py`, `backend/app/translation/manager.py`,
  `backend/app/sessions/{repository,assembler}.py`, `backend/app/analysis/*`,
  `frontend/static/{index.html,app.js,style.css}`, `tests/test_context_engine.py`,
  `tests/test_phase3_frontend_static.py`, `.gitignore`, `README_KO.md`.
- 검증: `python -m pytest -q` → 최종 `236 passed, 3 skipped`. 로컬 브라우저 실제 조작에서
  프로필 전환, 가상 사람 이름/별칭 등록과 삭제, 오류 overlay/console, 모바일
  overflow를 확인했다.
- 절충/위험: 실제 일본어/영어 음성에 대한 전후 정확도는 아직 측정하지 않았다.
  후보 추천은 약어·CamelCase·가타카나·호칭 기반 휴리스틱이며 사용자 승인이
  필수다. Deepgram keyterm 변경은 연결 중간 재구성하지 않고 다음 캡처부터 적용한다.
- GPT-5.6/Codex 증거: GPT-5.6 Sol 사용 화면과 초기 공유 대화는 앞선 기록에서
  확인했다. 이 핵심 구현 작업의 `/feedback` Codex Session ID는 아직 확보하지 않았다.

### 2026-07-15 스크롤 목록·Gemini 분석 확장

- 사용자 문제/결정: 등록 단어가 늘어나도 Context Engine 카드가 페이지 전체를
  계속 늘리지 않도록 목록 안에서 스크롤하고, 회의 분석에 Gemini 선택지를 추가한다.
- Codex 구현: 등록 항목과 추천 후보에 고정 높이·키보드 포커스·내부 스크롤을
  적용했다. `GeminiAnalysisProvider`는 기존 `GEMINI_API_KEY`와 번역 모델을 기본
  재사용하고 `GEMINI_ANALYSIS_MODEL`로 별도 모델을 선택할 수 있다. 실제 분석 요청만
  외부로 전송하며 Structured Output, Pydantic strict validation, final `segment_id`
  evidence 검증, bounded manager timeout/retry를 기존 OpenAI 경로와 공유한다.
- 변경 파일: `backend/app/analysis/gemini_provider.py`,
  `backend/app/analysis/__init__.py`, `backend/app/{services,main}.py`,
  `backend/app/{config/settings,api/schemas}.py`,
  `frontend/static/{index.html,app.js,style.css}`, `.env.example`, `README_KO.md`,
  `AGENTS.md`, `tests/test_gemini_analysis_provider.py`,
  `tests/test_phase3_{config,api,frontend_static}.py`.
- 검증: `.venv\Scripts\python.exe -m pytest -q` → `247 passed, 3 skipped`.
  별도 8878 포트 브라우저에서 본문, 오류 overlay 부재, 등록 항목 10개의 350px 내부
  스크롤(`scrollHeight=690`), Gemini 선택 시 `사용 가능`, 설정된 모델명, 비용·개인정보
  경고 표시를 확인하고 검증 탭·프로세스·포트를 정리했다.
- 절충/위험: 비용과 실제 회의 내용 외부 전송을 피하기 위해 실 Gemini 생성 호출은
  실행하지 않았다. SDK 경계는 모의 응답·인증/429/timeout/5xx·잘못된 JSON·존재하지
  않는 evidence 자동 테스트로 검증했다. 실제 선택 모델의 계정 권한·quota·응답 지연은
  첫 사용자 실행에서 확인해야 한다.
- GPT-5.6/Codex 증거: 이 작업의 모델/추론 단계는 별도 실행 메타데이터로 확인하지
  않았고 `/feedback` Codex Session ID도 아직 확보하지 않았다.

### 2026-07-15 한국어·영어 UI 전환

- 사용자 문제/결정: Build Week 심사자가 제품을 직접 이해하고 조작할 수 있도록
  영문 UI 전환을 지금 구현하고, 영문 README·Devpost 설명·영상 자막은 기능 개발이
  끝난 뒤 별도로 작성한다. 한국어를 기본값으로 유지한다.
- Codex 구현: 빌드 도구 없는 공통 `i18n.js`에 한국어 원문 키 기반 영문 사전을
  만들고, 접근 가능한 `한국어 / English` 전환 버튼과 `localStorage` 지속성,
  `BroadcastChannel`/storage 이벤트 기반 메인·자막 창 동기화를 연결했다. 정적
  HTML뿐 아니라 장치·STT·Provider/Worker·세션·Context Engine·분석·WebSocket
  상태, 오류, 확인 대화상자와 `<template>` 복제 내용도 같은 언어를 사용한다.
  실제 원문·번역 결과·사용자 용어/이름·모델 분석 본문은 UI 사전에 통과시키지 않는다.
- 변경 파일: `frontend/static/i18n.js`, `index.html`, `app.js`, `style.css`,
  `captions.html`, `captions.js`, `captions.css`, `tests/test_ui_i18n.py`,
  `README_KO.md`, 이 문서.
- 검증: 정적 UI·자막·Phase 3·Deepgram 묶음
  `.venv\Scripts\python.exe -m pytest -q tests\test_ui_i18n.py tests\test_caption_window.py tests\test_phase3_frontend_static.py tests\test_deepgram_stt.py`
  → `35 passed`. 전체 `.venv\Scripts\python.exe -m pytest -q` →
  `252 passed, 3 skipped`; 세 SKIP은
  기존 OpenAI/로컬 live test의 자격증명·명시 플래그가 없어 실행하지 않은 항목이다.
  실행 중인 로컬 앱을 실제 브라우저로 열어 한국어→영어, 새로고침 유지, 새 자막
  창의 영어 상속, 자막 템플릿 영문화, 자막 창에서 한국어로 전환할 때 메인 창 동기화,
  의미 있는 본문 렌더링과 오류 overlay 부재를 확인했다. 마지막 저장 언어는 한국어로
  복원했다.
- 절충/위험: 언어 전환은 모든 동적 UI를 확실히 재구성하기 위해 페이지를 한 번
  새로고침한다. 캡처 중지 요청은 보내지 않지만 활성 캡처 도중 전환하는 실제 음성
  검증은 이번 작업에서 실행하지 않았다. 지원 UI 언어는 한국어와 영어 두 가지이며,
  API가 새 한국어 오류 문구를 추가하면 영문 사전도 함께 갱신해야 한다.
- GPT-5.6/Codex 증거: 이 작업의 실행 모델/추론 단계는 별도 메타데이터로
  독립 확인하지 않았고 `/feedback` Codex Session ID도 아직 확보하지 않았다.

### 2026-07-15 한국어→영어 번역 방향

- 사용자 문제/결정: 기존 일본어·영어→한국어와 한국어→일본어에 더해 실제
  한국어 회의도 영어로 전달할 수 있도록 UI에서 한국어→영어 방향을 선택한다.
  한국어 원문 방향은 기존 제품 안전 규칙과 동일하게 Deepgram STT 및 Gemini/OpenAI
  번역만 허용하고 로컬 Whisper와 한국어 입력을 지원하지 않는 로컬 M2M100은 막는다.
- Codex 구현: `ko_to_en`을 설정 공개 계약, FastAPI 요청 schema, 캡처 controller,
  번역 요청/결과 target 언어에 추가했다. Deepgram에는 `ko`, 번역 Provider에는 `en`을
  전달하며 OpenAI/Gemini 공통 지시문은 한국어 회의 발화를 자연스러운 영어로 번역하고
  영어 번역만 반환하도록 분기한다. UI 방향 선택·제목·안내·번역 중 언어 표시와 영문
  UI 사전을 연결하고, Deepgram 미선택 또는 외부 Provider 미적용 상태에서는 시작을
  차단한다. 정적 파일 버전을 올려 재시작 뒤 이전 JavaScript 캐시가 남지 않게 했다.
- 변경 파일: `backend/app/config/settings.py`, `backend/app/api/schemas.py`,
  `backend/app/capture/controller.py`, `backend/app/translation/models.py`,
  `backend/app/translation/openai_provider.py`, `backend/app/translation/local_provider.py`,
  `backend/app/translation/worker_provider.py`, `frontend/static/index.html`,
  `frontend/static/app.js`, `frontend/static/i18n.js`, `frontend/static/captions.html`,
  `.env.example`, `README_KO.md`, `tests/test_deepgram_stt.py`,
  `tests/test_translation_models_providers.py`, `tests/test_gemini_translation_provider.py`,
  `tests/test_local_translation_worker.py`, `tests/test_phase2_config_security.py`, 이 문서.
- 검증: 방향·Provider·schema·Deepgram·i18n 묶음
  `.venv\Scripts\python.exe -m pytest -q tests\test_translation_models_providers.py tests\test_local_translation_worker.py tests\test_gemini_translation_provider.py tests\test_phase2_config_security.py tests\test_deepgram_stt.py tests\test_ui_i18n.py`
  → `63 passed`. 전체 `.venv\Scripts\python.exe -m pytest -q` →
  `255 passed, 3 skipped`; 세 SKIP은 자격증명과 명시 실행 플래그가 필요한 기존
  OpenAI 분석/OpenAI 번역/로컬 번역 live test다. 실행 중인 로컬 앱의 실제 브라우저에서
  로컬 Whisper일 때 두 한국어 원문 방향이 비활성화되고, Deepgram 선택 뒤
  한국어→영어가 활성화되는 것을 확인했다. 선택 결과는 `ko_to_en`, 제목은
  `영어 번역 설정`, 로컬 Provider는 비활성, Gemini/OpenAI 적용 전 시작 버튼은
  비활성이었으며 오류 overlay와 콘솔 오류는 없었다.
- 절충/위험: 실제 회의 음성과 외부 API 비용을 발생시키는 Deepgram→Gemini/OpenAI
  live 호출은 실행하지 않았다. SDK 경계와 언어 전달은 모의 응답 및 controller 통합
  테스트로 검증했다. 기존 세션을 열람만 했고 캡처 시작·Provider 적용·세션 수정은
  하지 않았다. 실행 중인 서버는 중단하지 않았으므로 사용자는 `stop_all.bat` 후
  `start_all.bat`으로 새 백엔드 코드를 로드해야 한다.
- GPT-5.6/Codex 증거: 이 작업의 실행 모델/추론 단계는 별도 메타데이터로
  독립 확인하지 않았고 `/feedback` Codex Session ID도 아직 확보하지 않았다.

### 2026-07-15 보조 섹션 기본 접힘

- 날짜/시간(KST): 2026-07-15 20:05.
- 사용자 문제/결정: 설정과 결과가 한 페이지에 계속 쌓여 전체 화면을 한눈에 보기
  어렵다. 논의했던 오프라인 양방향 대화 모드는 구현하지 않고, `회의 용어와 사람 이름`,
  `현재 세션과 기록`, `회의 분석` 세 영역만 펼치고 접을 수 있게 하며 기본값은 접힘으로
  정했다.
- Codex 구현: 세 카드를 브라우저 표준 `details`/`summary` 기반 접이식 영역으로
  변경했다. 제목과 Context·세션·분석 상태 배지는 접혀도 유지하고 기존 폼, 데이터
  로딩, API와 분석 결과 DOM은 내부에 그대로 보존했다. 마우스 토글과 함께 Enter/Space
  키보드 토글 및 `aria-expanded` 동기화를 명시적으로 연결하고, 포커스 표시·회전
  화살표·모바일 여백을 추가했다. CSS와 JavaScript 캐시 식별자도 갱신했다.
- 변경 파일: `frontend/static/index.html`, `frontend/static/style.css`,
  `frontend/static/app.js`, `tests/test_phase3_frontend_static.py`, `README_KO.md`,
  이 문서.
- 검증: 정적 UI·i18n·자막 묶음
  `.venv\Scripts\python.exe -m pytest -q tests\test_phase3_frontend_static.py tests\test_ui_i18n.py tests\test_caption_window.py`
  → `22 passed`. 전체 `.venv\Scripts\python.exe -m pytest -q` →
  `256 passed, 3 skipped`; 세 SKIP은 자격증명과 명시 플래그가 필요한 기존
  OpenAI 분석/OpenAI 번역/로컬 번역 live test다. 실행 중인 로컬 앱의 실제
  브라우저에서 세 카드가 모두 `open=false`, `aria-expanded=false`, 높이 약 91px로
  시작하는 것을 확인했다. 현재 세션 카드는 Enter로 약 484px까지 펼쳐지고
  `aria-expanded=true`가 된 뒤 Space로 다시 접혔다. Context 카드는 클릭으로 펼쳐졌고
  기존 프로필 컨트롤이 유지됐다. 오류 overlay와 콘솔 오류는 없었다.
- 절충/위험: 펼침 상태는 의도적으로 저장하지 않으므로 새로고침이나 UI 언어 전환 후
  다시 기본 접힘으로 돌아간다. 접힌 동안에도 데이터와 상태 갱신은 계속되지만 상세
  내용은 사용자가 펼쳐야 확인할 수 있다. 캡처 시작, Provider 적용, 세션·분석 생성은
  실행하지 않았고 기존 세션 파일을 수정하지 않았다.
- GPT-5.6/Codex 증거: 이 작업의 실행 모델/추론 단계는 별도 메타데이터로
  독립 확인하지 않았고 `/feedback` Codex Session ID도 아직 확보하지 않았다.

### 실측 성능 기록

제공된 YouTube 영상의 한국어 음성 60~90초를 Windows Media Player로 실제
스피커에 재생하고 기본 WASAPI Loopback으로 수집했다. 파일을 STT API에 직접
업로드한 결과가 아니다.

| 지표 | 개선 전 | 개선 후 |
|---|---:|---:|
| 30초간 확정 원문 | 3개 | 7개 |
| 최장 원문 청크 | 12.57초 | 4.04초 |
| 첫 번역 완료 | 약 10.79초 | 최대 약 6.05초 |
| Gemini Provider 지연 | 0.73~0.84초 | 0.54~0.79초 |

## 5. 사용자와 Codex의 역할

### 사용자가 주도한 부분

- 실제 문제 정의: 일본어 회의, 영어 회의와 영상 시청에서 체감 가능한 자막
- 우선순위와 제품 결정: 로컬/외부 Provider 선택, 역방향 번역 제약, 별도 자막창,
  투명도, 원문/번역 표시 모드, Lite 배포
- 실제 하드웨어·YouTube 사용 경험을 통한 지연과 UX 피드백
- 비용·프라이버시·배포 대상에 대한 최종 판단

### Codex가 가속한 부분

- 요구사항을 단계별 아키텍처, 실패 격리와 테스트 가능한 인터페이스로 변환
- 오디오/STT/번역/UI 각 구간의 지연을 실측해 병목을 분리
- Deepgram/Gemini/M2M100의 실패가 원문 캡처를 막지 않도록 복구 경로 구현
- 보안 경계, PID 기반 프로세스 관리, 비밀정보 없는 Lite 배포 자동화
- 단위·통합·실환경 회귀 테스트와 문서화

### 공동 의사결정 사례

- `endpointing=150ms`는 짧은 문장 내 휴지까지 분리해 300ms를 유지했다.
- Gemini 자체 지연보다 Deepgram의 긴 `speech_final` 대기가 병목임을 실측했다.
- interim을 직접 번역하면 중복·문장 뒤집힘·비용이 커지므로, partial은 UI에만
  표시하고 공식 `Finalize`로 안정된 final을 앞당기는 방식을 선택했다.
- 배포 편의와 용량을 위해 로컬 모델을 ZIP에 포함하지 않고 선택 설치로 분리했다.
- 초기 기획 대화에서 범용 번역 경쟁보다 현장 용어가 STT→번역→분석 전 구간에서
  일관되게 보존되는 `Worksite/Adaptive Context Engine`을 차별화 축으로 정했다.
- Context 추천은 자동 학습으로 프로필을 변경하지 않고 사용자가 `추가/무시`해야만
  상태가 바뀌도록 했다. 사람 이름과 현장 용어 파일은 Git과 Lite ZIP에서 제외했다.
- Deepgram Nova-3는 공식 `keyterm` 반복 파라미터를 사용하며 프로필 변경 중 현재
  연결을 끊지 않는다. 정규화/glossary는 즉시, STT keyterm은 다음 캡처 연결부터
  적용하는 안정성 우선 정책을 선택했다.

## 6. 앞으로의 변경 기록 형식

모든 Build Week 작업은 아래 형식으로 이 문서에 한 줄 이상 추가한다.

```text
날짜/시간(KST):
사용자 문제 또는 관찰:
사용자가 내린 제품 결정:
Codex가 제안·구현한 내용:
변경 파일 또는 커밋:
검증 명령과 실제 결과:
실패·절충·남은 위험:
GPT-5.6/Codex Session ID:
```

측정하지 않은 성능은 추정치로 표시하고, 실행하지 않은 테스트는 PASS로 기록하지
않는다. API 키와 실제 회의 원문은 로그·README·영상·저장소에 넣지 않는다.

## 7. 현재 객관적 평가

### 심사 항목별 현재 점수(10점 만점, 자체 평가)

| 기준 | 점수 | 근거 |
|---|---:|---|
| Technological Implementation | 8.5 | 실제 오디오, 복수 Provider, 장애 격리, 세션, 배포와 Context Engine의 STT→정규화→번역→분석 연결. GPT-5.6 사용 화면·공유 대화는 확인했으나 핵심 Codex Session ID와 커밋 이력이 부족 |
| Design | 8.0 | 설정→컨텍스트 프로필→캡처→자막→번역→분리창→세션까지 일관된 제품. Windows 설치와 API 키 설정이 심사 마찰 요소 |
| Potential Impact | 8.0 | 언어 장벽이 있는 회의라는 구체적 문제와 실제 사용자가 분명함 |
| Quality of the Idea | 7.5 | 범용 실시간 번역에 사용자 통제형 현장 용어·사람 이름 기억과 근거 보존을 결합. 실제 다국어 라이브 데모 증거는 아직 필요 |

기능 완성도만 보면 제출 가능한 중상위권 프로젝트지만, 현재 그대로는 우승
유력작으로 보기 어렵다. 가장 큰 약점은 코드 양이 아니라 다음 세 가지다.

1. Context Engine이라는 구분점은 구현했지만 실제 전후 인식·번역 비교 영상이 없다.
2. Windows 전용 설치와 참가자 API 키 의존 때문에 심사자가 즉시 체험하기 어렵다.
3. 사전 프로젝트 대비 GPT-5.6/Codex 신규 기여 증거와 영문 제출 스토리가 없다.

### 우승권으로 올리기 위한 권장 제품 초점

주력 차별점은 초기 기획에서 합의한 **Worksite Context Engine**으로 둔다. 사용자가
회의/현장 프로필과 용어를 통제하고, 같은 컨텍스트를 Deepgram keyterm, 결정론적
원문 정규화, 번역 glossary, 회의 분석에 일관되게 전달한다. 원문과 정규화문은 모두
보존하고 새로운 용어는 자동 학습하지 않으며 사용자가 승인하거나 무시하게 한다.

2026-07-15에 첫 제품 수직 경로를 구현했다. 프로필과 사람 이름/용어/별칭 관리,
Deepgram keyterm, 원문과 별도 정규화 이벤트, 번역 glossary, 분석 입력, 승인형
추천 UI/API가 연결됐다. 추천 추출은 현재 결정론적 휴리스틱이므로 일본어 사람 이름은
호칭 패턴 등 명확한 후보만 제안하며 완전한 고유명사 판별을 주장하지 않는다.

이 위에 **장애가 나도 원문을 잃지 않고 모든 결정의 근거 문장으로 돌아갈 수 있는
다국어 회의 메모리**라는 제품 경험을 얹는다.

GPT-5.6 기반 `Decision Radar`는 주력 차별점 자체가 아니라 Context Engine의 결과를
회의 중 행동으로 바꾸는 보조 실시간 레이어다. 기존 Phase 3에 이미 회의 종료 후
결정·할 일·근거 분석이 있으므로, 단순 재실행은 신규성이 약하다.

- final segment만 입력으로 받아 결정, 담당자, 기한, 미해결 질문을 지속 갱신
- 모든 결과를 원문 `segment_id`에 연결해 클릭하면 근거 자막으로 이동
- 확신이 낮거나 번역이 엇갈린 항목은 추측하지 않고 `확인 필요`로 표시
- STT/LLM 장애 시 원문 기록은 계속되고 나중에 안전하게 따라잡기
- 데모에서는 일본어 회의 한 장면으로 “듣기→번역→결정 포착→근거 이동”을
  90초 안에 보여주기

기존 Phase 3의 회의 분석을 그대로 재포장하지 말고, Submission Period 중
GPT-5.6와 Codex로 실시간 근거 연결·검증 UX를 새로 구현해야 의미 있는 확장이
된다.

권장 데모 흐름은 `범용 프로필의 용어 오인식 → 현장 프로필의 용어 정규화 → 번역
일관성 → Decision Radar의 할 일 포착 → 근거 segment 이동`이다. 시간 제약이 있으면
Context Engine을 먼저 완성하고 Decision Radar는 작은 수직 기능으로 제한한다.

## 8. 제출 전 체크리스트

- [ ] Devpost 참가 등록과 개인 자격 확인
- [x] 사용자 제공 모델 선택 화면과 공개 공유 대화에서 GPT-5.6 Sol 사용 확인
- [ ] `/feedback`으로 핵심 Codex Session ID 확보
- [ ] Git 저장소 생성 후 비밀정보 제외를 검사하고 기준선/신규 작업 커밋 구분
- [ ] Work & Productivity 트랙 확정
- [ ] 차별화 기능 하나를 완성하고 신규 작업만 명확히 설명
- [ ] `README.md` 영문판: 문제, 데모, 설치, 테스트, 아키텍처, Codex 협업
- [ ] 심사용 무료 테스트 빌드 또는 재현 가능한 Windows Lite 패키지 제공
- [ ] API 키·세션·사용자 경로·저작권 자료가 저장소와 영상에 없는지 검사
- [ ] 3분 미만 영문 또는 영문 자막 포함 공개 YouTube 데모 제작
- [ ] 영상에서 Codex와 GPT-5.6 사용, 사용자 결정, 전후 성능 수치 설명
- [ ] Devpost 영문 설명·이미지·저장소 URL·Session ID 입력
- [ ] 2026-07-22 09:00 KST보다 충분히 일찍 최종 제출

## 2026-07-15 21:10 KST — 근거 연결형 Decision Radar

- 사용자 문제 또는 관찰: 실시간 번역만으로는 회의에서 무엇이 결정됐고 누가 무엇을 해야 하는지 놓치기 쉽다. 단순 요약이 아니라 각 판단을 실제 원문에 연결해 검증할 수 있어야 하며, 기존 Context Engine의 사람 이름과 현장 용어도 활용해야 했다.
- 사용자가 내린 제품 결정: Deepgram final만 분석하고, 결정·Action Item·미해결 질문·확인할 이름/용어/번역을 계속 갱신한다. 항목은 승인·수정·삭제할 수 있게 하며 OpenAI와 Gemini 중 사용자가 명시적으로 Provider를 선택한다. 분석 실패가 원문 전사·번역·세션 저장을 막아서는 안 되고 기존 JSONL은 수정하지 않는다.
- Codex가 제안·구현한 내용: final 5개 또는 최대 10초 bounded batch, 동시성 1의 제한 queue, timeout/유한 재시도, strict Structured Output, 현재 batch의 실제 `segment_id` 대조, 중복 제거와 삭제 tombstone, 별도 atomic Radar 저장소를 구현했다. OpenAI 기본값은 공식 모델 문서를 확인해 짧은 주기의 저지연 구조화 분석용 `gpt-5.6-luna`로 정했고 `.env`에서 교체 가능하게 했다. Provider 조회만으로 외부 호출하지 않으며 적용 시 외부 전송 안내를 표시한다. 넓은 화면 3열, 중간 화면 2+1열, 좁은 화면 단일 열 UI와 한/영 문구를 추가했다.
- 변경 파일 또는 컴포넌트: `backend/app/decision_radar/`, `backend/app/config/settings.py`, `backend/app/services.py`, `backend/app/capture/controller.py`, `backend/app/api/schemas.py`, `backend/app/main.py`, `frontend/static/index.html`, `frontend/static/style.css`, `frontend/static/app.js`, `frontend/static/i18n.js`, `.env.example`, `README_KO.md`, `tests/test_decision_radar.py`, `tests/decision_radar_manual_test_checklist.md`, `docs/decision_radar_report.md`.
- 검증 명령과 실제 결과: `.venv\Scripts\python.exe -m pytest -q` → `264 passed, 3 skipped in 11.06s`. bundled Node로 `frontend/static/app.js`와 `frontend/static/i18n.js`의 `--check` → PASS. Playwright와 설치된 Edge로 localhost를 열어 1440/1024/760px 배치, 영어 UI, 세 Provider, Gemini 외부 전송 안내, 새로고침을 확인했고 마지막 실행에서 HTTP/console 오류는 0건이었다. 기존 세션 179개 파일의 정렬 집계 SHA-256은 전후 모두 `FD0D03ED08680FD5D1F4C138627997DE65C6EE2FC1265A9E7BAC368812948AB9`였다.
- 실패·예외·남은 위험: 최종 해시 재확인의 첫 PowerShell 명령은 현재 .NET에 `[IO.Path]::GetRelativePath`가 없어 실패했으며, 파일 쓰기 없이 문자열 기반 상대 경로 계산으로 교체해 기준 해시 일치를 확인했다. 실제 OpenAI/Gemini Radar 호출은 키·quota·비용을 사용하므로 실행하지 않았다. 따라서 실제 모델 접근 권한, 응답 지연, quota, 일본어/영어 회의 추출 품질은 수동 검증이 남았다. 화자 분리가 없으므로 담당자는 원문에 명시된 경우에만 안전하다. 장시간 회의에서 활성 DOM 보존 한계를 지난 근거는 캡처 종료 후 기록 조회가 필요할 수 있다. queue 초과 시 Radar 분석만 버리고 원문을 보존한다. 파생 Radar 파일에도 회의 내용이 포함될 수 있으므로 배포물과 공개 저장소에 포함하지 않아야 한다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 설계, 구현, 자동 테스트, 로컬 브라우저 검증, 문서화를 수행했다. Devpost 제출용 Codex Session ID는 이 기록에 임의로 만들지 않았으며 제출 전에 `/feedback` 결과로 별도 확인해야 한다.

## 2026-07-15 23:55 KST — Radar 결과 전용 창과 네이티브 투명 오버레이

- 사용자 문제 또는 관찰: 브라우저 자막 pop-out의 투명도는 Windows 창 자체에 적용되지 않아 회의·영상 위에 자연스럽게 겹칠 수 없었다. 사용자는 Provider 설정이 아니라 Decision Radar의 실제 결과 패널도 자막처럼 따로 떼어 보고 싶다고 명확히 했다.
- 사용자가 내린 제품 결정: Provider 선택·모델·적용은 메인 화면에 남기고 결정 사항, 해야 할 일, 미해결 질문, 확인 필요 네 결과 그룹만 별도 창으로 연다. 자막과 Radar 결과 창은 실제 Windows 투명화와 항상 위 동작을 제공하되, 기존 브라우저 사용과 서버·원문 전사는 네이티브 UI 실패와 분리한다.
- Codex가 제안·구현한 내용: `/decision-radar` 결과 전용 REST/WS 창, 메인 창과의 snapshot·근거 이동 채널, 한/영 UI, 0~85% 배경 투명도를 구현했다. 선택형 Electron shell은 frameless transparent always-on-top caption/radar overlay만 만들고 preload의 제한 IPC, localhost navigation 제한, permission 거부, renderer sandbox를 적용했다. 전역 Node 없이 공식 checksum을 확인하는 portable Node/Electron setup, `start_all.bat` 자동 native/브라우저 fallback, 검증된 desktop PID tree만 종료하는 `stop_all.bat`, Lite source-only 배포와 Node/Electron upstream notice를 연결했다.
- 변경 파일 또는 컴포넌트: `backend/app/main.py`, `frontend/static/index.html`, `style.css`, `app.js`, `i18n.js`, `captions.html/js/css`, `decision-radar.html`, `decision-radar-window.js/css`, `desktop/main.cjs`, `desktop/preload.cjs`, `desktop/package.json`, `desktop/package-lock.json`, `setup_desktop_overlay.bat`, `scripts/setup_desktop_overlay.ps1`, `scripts/start_desktop.ps1`, `start_all.bat`, `scripts/stop_project.ps1`, `scripts/build_lite_release.ps1`, `.gitignore`, `README_KO.md`, `DISTRIBUTION_KO.md`, `tests/test_decision_radar_window.py`, `tests/test_desktop_overlay.py`, `tests/test_ui_i18n.py`, `tests/desktop_overlay_manual_test_checklist.md`, `docs/decision_radar_report.md`, `docs/desktop_overlay_report.md`.
- 검증 명령과 실제 결과: Node `--check` 5개 파일과 PowerShell parser 4개 script PASS. 관련 pytest `20 passed in 3.40s`, 전체 `.venv\Scripts\python.exe -m pytest -q`는 `275 passed, 3 skipped in 14.52s`이며 최종 재실행도 `275 passed, 3 skipped in 13.86s`. 설치 script 재실행으로 Node 24.18.0/Electron 43.1.1 준비 성공. Windows UI에서 자막과 Radar 결과 native 창, 결과 전용 구성, Radar 85% 투명 배경과 불투명 글자를 확인했다. 실제 `start_all.bat → stop_all.bat → start_all.bat`에서 서버·Worker·desktop 개별 PID, health, 8765 port와 PID 파일 정리, 별도 Codex Node 생존을 확인했다. third-party notice 반영 후 다시 만든 Lite ZIP은 0.29 MiB, 필수 desktop source 포함, runtime·실제 세션·비밀 entry 0, SHA-256 `24F4730CD44BA190C75E9377D55BA2FB8FA4D1C61482203DEF3B970DB64A4A6A`. 기존 세션 179개 정렬 집계 SHA-256은 전후 `FD0D03ED08680FD5D1F4C138627997DE65C6EE2FC1265A9E7BAC368812948AB9`로 동일했다.
- 실패·절충·남은 위험: 첫 npm 실행은 Electron binary hook을 생략해 executable이 없었고 package-owned install hook과 존재 후검증을 추가해 해결했다. 첫 Electron launch는 hidden window option 때문에 UI까지 숨겨져 해당 option을 제거했다. 첫 browser fallback 자동화는 Playwright module 경로 오류, 좁은 창 언어 control 숨김, favicon 404가 있었고 각각 module 경로, 반응형 CSS, data favicon으로 수정했다. 최종 source 비밀 패턴 검사는 기존 Phase 3의 의도적인 synthetic redaction fixture 한 파일을 탐지했으며 실제 키가 아님을 값 비공개 상태로 확인했다. Lite는 tests를 제외하고 자체 secret scanner를 통과했다. Electron 공식 제약 때문에 Windows transparent overlay는 고정 크기이며 toolbar drag로 이동한다. 실제 외부 Radar API로 생성한 항목을 native 창에서 장시간 편집·근거 이동하는 실사용 검증은 비용·비민감 음성 조건이 필요해 SKIP이다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 결과 패널 경계를 사용자와 재확인하고 구현·설치·Windows UI·프로세스 안전성·회귀·배포를 검증했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-16 10:24 KST — 하단 한 줄 미디어 자막

- 사용자 문제 또는 관찰: 기존 자막 분리 창은 기록을 읽기에는 좋지만 높이가 커서 YouTube·Netflix 영상을 가렸다. 사용자는 화면 아래쪽에 폭이 넓고 높이가 낮은 한 줄 자막만 놓고 싶었고, Windows 투명 창에서 자유 resize가 어려운 조건도 함께 해결해야 했다.
- 사용자가 내린 제품 결정: 기존 전체 기록 **자막 창**은 유지하고 별도의 **미디어 자막** 모드를 추가한다. 미디어 자막은 현재 모니터 하단 중앙, 화면 너비 60%·80%·94% 프리셋, 최신 한 문장만 표시하며 원문만·번역만·원문+번역과 투명도를 선택할 수 있어야 한다.
- Codex가 제안·구현한 내용: 기본값을 `자동 · 번역 우선`으로 정해 translation이 도착하기 전에는 같은 final의 원문을 즉시 보여 주고, 같은 `segment_id`의 translation이 성공하면 그 자리를 번역으로 교체했다. 발화 중 partial은 final보다 먼저 임시 한 줄로 표시한다. 22~48px 사용자 기본 크기에서 시작해 창 폭을 넘으면 18px까지 1px씩 자동 축소하고, 그래도 넘을 때만 ellipsis를 사용한다. 설정 toolbar는 평소 숨기고 hover/focus 때만 보이게 했다. Electron은 메인 창이 있는 display의 `workArea`를 기준으로 하단 12px 여백에 배치하고, preload의 제한된 IPC가 60/80/94 값만 허용해 프로그램 방식으로 크기를 바꾼다. display 해상도·작업 영역 변화와 모니터 제거 시에도 다시 배치한다. 브라우저 fallback은 동일한 responsive 페이지를 새 창으로 연다.
- 변경 파일 또는 컴포넌트: `frontend/static/index.html`, `frontend/static/app.js`, `frontend/static/i18n.js`, `frontend/static/captions.html`, `frontend/static/captions.js`, `frontend/static/captions.css`, `desktop/main.cjs`, `desktop/preload.cjs`, `tests/test_caption_window.py`, `tests/test_desktop_overlay.py`, `tests/test_phase3_frontend_static.py`, `README_KO.md`, `docs/desktop_overlay_report.md`, `tests/desktop_overlay_manual_test_checklist.md`, 이 기록.
- 검증 명령과 실제 결과: bundled Node `--check`로 `app.js`, `captions.js`, `i18n.js`, `main.cjs`, `preload.cjs` PASS. 관련 pytest는 `17 passed in 2.04s`, 보강 계약 묶음은 `25 passed in 1.94s`, 전체 `.venv\Scripts\python.exe -m pytest -q`는 최종 `276 passed, 3 skipped in 12.38s`. 설치된 Edge와 Playwright의 격리 WebSocket으로 실제 세션을 읽지 않고 synthetic final/translation/partial을 주입했다. 최신 항목 1개만 표시, 자동 원문→번역 전환, partial 우선, 한 줄 유지, 1600px에서 36→26px 축소, 960px에서 최저 18px 후 ellipsis, 수평 overflow 없음, 60/80/94 설정, 한/영 UI를 확인했다. Windows 네이티브 버튼을 직접 눌러 별도 미디어 창이 열리고 기본 94%에서 `1605 × 220px`로 현재 모니터 하단 중앙에 배치되는 것을 확인했다. 서버 health `ok`, Worker ready, desktop ready를 다시 확인했다. 기존 세션 179개 정렬 집계 SHA-256은 기준과 같은 `FD0D03ED08680FD5D1F4C138627997DE65C6EE2FC1265A9E7BAC368812948AB9`였다. 새 Lite ZIP은 305,370 bytes, 105 entries, 필수 source 누락 0, 비밀·runtime·실제 세션 entry 0, SHA-256 `8B5D431059E0B23847680A8A9B600D8BD3F2F8B33086811F4BA3E0E454EC0F5A`다.
- 실패·예외·남은 위험: 제공된 `agent-browser` CLI가 PATH에 없어 첫 자동화 진입은 실패했고, bundled Playwright와 설치된 Edge로 교체했다. 첫 긴 문장 검증에서 CSS grid의 intrinsic `max-content` track 때문에 글자 축소가 실행되지 않고 바로 잘리는 문제를 발견해 bounded flex 폭으로 수정했다. 전체 회귀 첫 실행은 이전 cache-buster 날짜를 고정 비교하던 테스트 1개가 실패했으며, 세 정적 자산의 버전이 서로 같은지를 검증하도록 계약을 수정했다. 브라우저 console에는 기존 meta CSP의 `frame-ancestors` 무시 경고만 있었고 page/runtime 오류는 없었다. Windows 투명 창은 자유 resize 대신 프리셋만 지원한다. 18px에서도 너무 긴 문장은 의도적으로 ellipsis 처리된다. 실제 비민감 영상 음성과 번역을 네이티브 창에 장시간 표시하는 수동 검증은 이번 synthetic UI 검증에 포함하지 않아 SKIP이다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 사용자 스크린샷을 제품 제약으로 변환하고, 별도 모드 설계·구현·네이티브 Windows 확인·브라우저 격리 회귀·배포 갱신을 수행했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-16 11:08 KST — Gemini 구조화 분석 호환성 수정

- 사용자 문제 또는 관찰: Gemini 번역은 정상인데 Decision Radar만 `unknown_provider_error`로 실패해 무료 사용량 초과인지 구분하기 어려웠다. 런타임 diagnostics는 Gemini Radar 활성, 성공 batch 0, queue 0, `unknown_provider_error`를 보였고 로그에는 429·`RESOURCE_EXHAUSTED`·quota·timeout이 없었다.
- 사용자가 내린 제품 결정: OpenAI Radar 경로는 그대로 유지하고 Gemini 사용 경로만 수정한다.
- Codex가 제안·구현한 내용: Gemini Radar와 기존 Gemini 회의 분석이 엄격한 Pydantic 모델을 구형 `response_schema`로 전달하던 부분을 공식 `response_json_schema=<Payload>.model_json_schema()` 방식으로 통일했다. OpenAI Responses API의 `text_format`은 변경하지 않았다. Gemini status를 case-insensitive로 정규화하고 400 `INVALID_ARGUMENT`은 `INVALID_RESPONSE`, 400 `FAILED_PRECONDITION`은 `PROVIDER_UNAVAILABLE`, 429 `RESOURCE_EXHAUSTED`는 `RATE_LIMITED`로 안전하게 분리했다. API 키와 upstream의 비공개 오류 본문은 UI·로그·예외 문자열에 노출하지 않는다.
- 변경 파일 또는 컴포넌트: `backend/app/analysis/gemini_provider.py`, `backend/app/decision_radar/providers.py`, `tests/test_gemini_analysis_provider.py`, `tests/test_decision_radar.py`, `README_KO.md`, `docs/decision_radar_report.md`, 이 기록.
- 검증 명령과 실제 결과: Gemini 분석·Radar·번역 모의 묶음은 첫 실행에서 기존 status 대소문자 결함을 찾아 1 failed/24 passed였고 casefold 정규화 후 `25 passed in 0.71s`. 전체 `.venv\Scripts\python.exe -m pytest -q`는 `278 passed, 3 skipped in 13.80s`. SKIP 3개는 기존 OpenAI 분석·OpenAI 번역·로컬 번역 live flag 항목이다. 캡처가 stopped인 상태에서 `stop_all.bat → start_all.bat`으로 새 코드를 로드하고 Gemini 번역·Radar 선택을 복원했다. 이후 health `ok`, capture `idle`, Worker `ready`, Radar `idle`, `last_error_code=null`을 확인했다. 작업 시작 이후 수정된 세션 파일은 0개이며, 사용자의 직전 실제 시험으로 현재 존재하는 193개 파일의 집계 SHA-256은 `25D4D632C732D670C544C79D26F18B15653B2942DCEDDE280DD149490FD085DA`다. 갱신한 Lite ZIP은 305,528 bytes, 105 entries, 필수 Gemini/Radar source 포함, 비밀·runtime·실제 세션 entry 0, SHA-256 `D146C216A49EDFD9F178E9AFC4038132FD886FF65AE817C405B100F79EDECD8C`다.
- 실패·예외·남은 위험: 첫 모의 실행은 `status`를 대문자로 만든 뒤 소문자 marker와 비교하던 기존 분류 결함을 드러냈고 이를 수정한 후 재실행했다. 실제 Gemini 생성 요청은 사용자의 quota·비용과 회의 원문 외부 전송을 발생시키므로 자동 실행하지 않았다. 따라서 실제 계정에서 새 schema 요청이 성공하는지와 Radar 품질·지연은 사용자가 비민감 입력으로 한 번 확인해야 하며 그 전에는 MANUAL PASS로 기록하지 않는다. 진단 당시 raw upstream 400 본문을 보존하지 않아 과거 오류의 정확한 HTTP status를 사후 100% 확정할 수는 없지만, 이후 같은 400은 더 이상 `unknown_provider_error`로 뭉개지지 않는다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 로컬 diagnostics·로그·공식 Gemini 모델/SDK 문서를 대조해 quota 가설과 schema 호환성 가설을 분리하고, Gemini 전용 수정·오류 분류·회귀·프로세스 재시작·배포 갱신을 수행했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-16 12:06 KST — Decision Radar 의미 판별 정밀도 보강

- 사용자 문제 또는 관찰: 실제 일본어 샘플에서 Radar의 근거 ID는 올바른 원문을 가리켰지만, 인용된 일반 조언과 조건부 기간 설명을 Action으로 승격하고 같은 취지의 질문을 중복 생성하며 의견 불확실성을 번역 확인으로 분류했다. 전체 세션 분석은 같은 Gemini 모델로 결정·Action을 만들지 않아 단순히 무료 Flash-Lite 모델의 추론 강도 문제로만 볼 수 없었다.
- 사용자가 내린 제품 결정: 모델 교체보다 애플리케이션의 의미 판별 구조를 먼저 개선한다. 기존 세션과 JSONL은 수정하지 않고 OpenAI/Gemini 공통 Radar 경로에 앞뒤 문맥, 엄격한 발화 행위 규칙, 오탐 철회를 추가한다.
- Codex가 제안·구현한 내용: 기본 batch 5개/최대 10초는 유지하면서 각 요청에 직전 최대 20개 final rolling context를 제공하고 새 묶음을 `focus_segment_ids`로 구분했다. 새 항목은 focus 근거를 반드시 하나 이상 포함하도록 서버에서도 검증한다. 인용·전언·시청자 요청·예시·일반 조언·의견·제안·수사적 질문·가정·조건·가능성·기간 예상을 명시적 참가자 합의나 미래 약속 없이 결정/Action으로 만들지 않는 정밀도 우선 prompt 계약을 추가했다. 새 문맥이 기존 항목을 오탐·중복·해결된 질문으로 입증하면 `retract_item_ids`로 미검토 제안만 철회할 수 있으며, 승인·사용자 수정 항목과 존재하지 않는 ID는 각각 서버 보호·Provider 경계 검증으로 차단한다. context 크기는 `DECISION_RADAR_CONTEXT_SEGMENTS`로 제한하고 settings·diagnostics에 공개한다.
- 변경 파일 또는 컴포넌트: `backend/app/decision_radar/models.py`, `structured.py`, `prompts.py`, `providers.py`, `manager.py`, `backend/app/config/settings.py`, `backend/app/services.py`, `.env.example`, `README_KO.md`, `tests/test_decision_radar.py`, `tests/decision_radar_manual_test_checklist.md`, `docs/decision_radar_report.md`, `dist/meeting-live-translator-lite-20260716.zip`, 이 기록.
- 검증 명령과 실제 결과: `.venv\Scripts\python.exe -m pytest -q tests\test_decision_radar.py` → `12 passed in 0.65s`. 전체 `.venv\Scripts\python.exe -m pytest -q` → `282 passed, 3 skipped in 11.18s`; SKIP은 기존 OpenAI 분석·OpenAI 번역·로컬 번역 live flag 항목이다. 로컬 회귀 세션의 본문을 출력하거나 문서에 남기지 않고 과거 두 오탐 지점의 20개 context에 요청·전언·조건 신호가 포함되는지만 검사했으며 두 지점 모두 세 신호를 포함했다. 설치된 `google-genai`에서 새 `retract_item_ids` 필수 JSON Schema를 `GenerateContentConfig`로 네트워크 없이 구성하는 검사도 PASS였다. 캡처 `stopped` 상태에서 프로젝트 전용 `stop_all.bat → start_all.bat`을 실행하고 기존 Gemini 번역·회의 분석·Radar 선택을 복원했다. 이후 health `ok`, capture `idle`, local Worker `ready`, Radar `idle`, context 20, queue 0, `last_error_code=null`, startup stderr 오류 0을 확인했다. 작업 전후 세션 산출물은 201개이고 정렬 집계 SHA-256은 `5001E02E416E6FB903A5C8914BF11AABA360F177228E3CC6351EA4111FC892D4`로 동일했다. 갱신한 Lite ZIP은 307,133 bytes, 105 entries, rolling context·철회 schema·새 환경변수 포함, 금지된 비밀·runtime·실제 세션 entry 0, SHA-256 `CF30A46E4740E153B00806CFB7065F7953368ECEBBF4E4C942D8A534DC1E14E3`다.
- 실패·절충·남은 위험: 첫 Lite 빌드는 현재 PowerShell 실행 정책이 로컬 스크립트 로드를 차단해 파일 변경 없이 실패했고, 시스템 정책을 바꾸지 않는 일회성 `powershell.exe -ExecutionPolicy Bypass -File` 실행으로 성공했다. 첫 민감정보 집계식은 중간 PowerShell 구문 오류 후 파일 내용이 아니라 입력 경로 문자열을 검색해 로컬 경로 13건을 잘못 집계했으며, `Select-String -LiteralPath`로 수정해 세션 ID·근거 ID·키 패턴·로컬 경로가 변경 파일 내용에 0건임을 확인했다. 이 진단 실패들은 파일을 쓰지 않았다. 실제 Gemini/OpenAI 생성 호출은 quota·비용과 원문 외부 전송을 발생시키므로 실행하지 않았다. 따라서 개선 후 실제 모델의 오탐 감소율은 아직 MANUAL PASS가 아니며 비민감 샘플 재시험이 필요하다. rolling context는 의미 정확도를 높이는 대신 요청 입력 토큰을 늘릴 수 있어 기본 20개로 상한을 뒀다. 모델이 의미를 완벽히 이해한다고 보장하지 않으므로 결과는 계속 제안 상태로 표시하고 사용자 승인을 유지한다. 과거에 이미 승인·수정된 항목은 안전 정책상 자동 정리하지 않는다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 실제 결과와 근거를 대조해 모델 한계와 애플리케이션 문맥 경계를 분리하고, rolling context·focus 검증·보호된 철회·회귀·프로세스 재시작·문서화를 수행했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-17 17:19 KST — Decision Radar 설정 적용 시 UI 잠금 제거

- 사용자 문제 또는 관찰: Decision Radar Provider 설정을 적용한 직후 약 1분 동안 플랫폼의 버튼과 기능이 반응하지 않는 것처럼 보였다. 외부 모델 연결 확인이 화면을 막는지 실제 Electron 화면과 서버 로그를 함께 확인해 달라고 요청했다.
- 사용자가 내린 제품 결정: 외부 API 전송과 비용 안내는 유지하되, Radar 설정 중에도 자막·번역 등 다른 기능은 계속 조작할 수 있어야 한다.
- Codex가 제안·구현한 내용: 설정 API를 직접 계측해 Provider 적용이 실제 모델 호출 없이 SDK·키·모델의 로컬 가용성만 확인하고 3.3~15.6ms에 응답함을 확인했다. 전체 Electron 창을 잠그던 브라우저 기본 `window.confirm`을 제거하고, 첫 클릭에서 카드 내부 경고와 `외부 API 적용 확인` 버튼을 표시한 뒤 두 번째 클릭에서 적용하는 비차단 2단계 확인으로 교체했다. Provider 선택을 바꾸면 대기 중 확인 상태를 취소하며 한국어·영어 문구와 정적 자산 캐시 버전을 함께 갱신했다.
- 변경 파일 또는 컴포넌트: `frontend/static/app.js`, `frontend/static/i18n.js`, `frontend/static/index.html`, `tests/test_decision_radar.py`, 이 기록.
- 검증 명령과 실제 결과: Radar·i18n 관련 `.venv\Scripts\python.exe -m pytest -q tests\test_decision_radar.py tests\test_ui_i18n.py`는 `17 passed`. 실제 Electron에서 OpenAI Radar 선택 후 첫 클릭 시 네이티브 모달이 나타나지 않고 카드 내부 확인 상태가 표시되는 것을 확인했다. 확인 대기 중 번역 Provider 드롭다운은 65ms에 반응했고, 두 번째 클릭 후 적용·화면 복귀는 약 377ms였다. 설정 API 네 차례 계측은 3.3~15.6ms였다. 첫 전체 회귀는 자산 캐시 버전 불일치 계약으로 `1 failed, 281 passed, 3 skipped`였고 세 자산 버전을 통일한 뒤 재실행하여 `282 passed, 3 skipped in 12.96s`를 확인했다. SKIP은 기존의 명시적 live flag가 필요한 OpenAI 분석·OpenAI 번역·로컬 번역 테스트다.
- 실패·예외·남은 위험: 과거 체감 1분을 동일하게 재현하지는 못했지만, 서버가 그 시간 동안 diagnostics에 계속 응답했고 실제 화면에서 기본 확인 대화상자가 열린 동안 모든 컨트롤이 차단되는 현상을 재현해 고신뢰 원인으로 확정했다. 이번 검증은 Provider 설정만 바꿨으며 OpenAI 분석 요청이나 회의 원문 전송은 실행하지 않았다. 삭제 등 별도의 파괴적 확인 대화상자는 이번 범위에서 변경하지 않았다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 런타임 로그, API 계측, 실제 Windows Electron 조작, 코드 계약, 자동 회귀를 대조해 UI 잠금 원인을 찾고 비차단 확인 UX로 수정했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-17 17:46 KST — Radar 근거 오류의 안전한 부분 수용

- 사용자 문제 또는 관찰: 짧은 고정 대본으로 OpenAI `gpt-5.4-mini` Radar를 실제 시험했을 때 견적 전송 Action은 올바르게 생성됐지만, 다음 묶음에서 `분석 결과에 존재하지 않는 근거 문장이 포함되었습니다` 오류가 발생해 같은 응답의 결정과 질문까지 사라질 수 있었다.
- 사용자가 내린 제품 결정: 근거 검증 안전장치는 유지하면서, 모델이 근거 ID 하나를 잘못 만들었다는 이유로 같은 응답의 올바른 항목까지 모두 버리지 않도록 개선한다.
- Codex가 제안·구현한 내용: Provider 공통 구조화 결과를 항목별로 검증한다. 실제 rolling context ID와 모델이 만든 ID가 섞인 항목은 잘못된 참조만 제거하고 현재 focus의 실제 근거가 하나 이상 남으면 수용한다. 실제 근거가 전혀 없거나 focus 근거가 없는 항목만 폐기하며, 수용 가능한 항목과 유효한 철회가 모두 없으면 기존 `INVALID_EVIDENCE` 오류를 유지한다. 버린 근거 참조와 항목 수를 `discarded_evidence_references`, `discarded_suggestions` diagnostics로 누적하고 회의 내용 없이 서버 경고 로그에 숫자만 남긴다.
- 변경 파일 또는 컴포넌트: `backend/app/decision_radar/models.py`, `backend/app/decision_radar/providers.py`, `backend/app/decision_radar/manager.py`, `tests/test_decision_radar.py`, `tests/decision_radar_manual_test_checklist.md`, `docs/decision_radar_report.md`, 이 기록.
- 검증 명령과 실제 결과: 첫 Radar 단위 실행은 새 로직이 아니라 테스트 fixture가 구조화 스키마의 문자열 필드에 `null`을 넣어 `1 failed, 12 passed`였고 빈 문자열로 계약을 바로잡았다. 재실행한 `.venv\Scripts\python.exe -m pytest -q tests\test_decision_radar.py`는 `13 passed in 0.65s`. 혼합 응답에서 유효한 결정·확인 항목을 유지하고 잘못된 ID 두 개와 근거 없는 Action 하나만 폐기하는 것을 검증했으며, 모든 근거가 무효이거나 새 focus 근거가 없는 기존 거부 테스트도 유지됐다. 전체 회귀는 `283 passed, 3 skipped in 13.92s`; SKIP은 기존 live flag 필요 항목이다. 캡처 `stopped`를 확인한 뒤 프로젝트 전용 프로세스를 재시작했고 health `ok`, capture `idle`, Worker `ready`를 확인했다. 런타임 선택을 기존 Gemini 번역과 OpenAI `gpt-5.4-mini` Radar로 복원했으며 Radar `idle`, 오류 없음, 새 부분 폐기 카운터 0을 확인했다.
- 실패·예외·남은 위험: 모델이 반환한 텍스트의 의미 자체가 틀렸지만 우연히 실제 focus ID를 붙인 경우는 서버가 사실 여부를 독립적으로 증명할 수 없으므로 계속 사용자 승인 절차가 필요하다. 이번 자동 검증은 실제 OpenAI 재호출과 추가 비용을 발생시키지 않았으므로 사용자가 같은 비민감 대본을 다시 재생해 부분 수용 동작을 수동 확인해야 한다. 재시작 시 런타임 Provider 선택이 기본값으로 돌아가 즉시 기존 선택으로 복원했으며 원문 캡처는 실행하지 않았다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 실제 오류 코드와 안전 경계를 분석해 전체 거부와 무검증 수용 사이의 항목별 부분 수용 정책을 설계하고, 공통 Provider 경로·diagnostics·자동 회귀·런타임 복원·문서화를 수행했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-17 19:15 KST — 실제 세션 Radar 품질 검토와 비용 최적화

- 사용자 문제 또는 관찰: 한 세션의 Radar 시험을 마친 뒤 저장 로그와 결과가 실제 회의 결정을 제대로 추론했는지 검토하고, 필요한 의미 판별 개선과 비용 최적화를 함께 요청했다. 같은 시험에서 번역도 OpenAI mini를 사용해 API 요청 수가 많아졌다는 정보를 추가했다.
- 사용자가 내린 제품 결정: 반복 개발 시험에서는 고비용 Radar 모델을 피하고 mini를 사용한다. 기존 세션과 JSONL은 수정하지 않은 채 핵심 결정 회수율은 유지하고 중복 Action·과잉 질문과 반복 입력을 줄인다.
- Codex가 제안·구현한 내용: 비공개 최신 세션의 final 166개, OpenAI mini 번역 166개, Radar 성공 batch 44개와 저장된 28개 제안을 대조했다. 기대한 핵심 결정 4개와 핵심 미해결 질문 2개는 모두 포착했지만, 하나의 업무를 수행·공유로 나눈 Action, 위험을 질문으로 승격한 항목, 근거·보류를 별도 결정으로 만든 항목이 있었다. 인명은 STT 원문에 남지 않은 경우가 많아 담당자 추정이 불가능했고 제품명 철자 확인도 잘못 분류됐다. 공통 OpenAI/Gemini prompt에 업무 병합, 이후 요약으로 약한 제안 교체, 근거·선호·위험·결정 보류의 분류 제한, 철자 모호함의 `needs_confirmation` 강제, 근거 없는 화자·담당자 추정 금지를 추가했다. 이전 항목은 evidence·timestamp를 제외한 비교용 최소 필드만 보내고, 과거 context의 번역과 원문과 같은 normalized text 및 시간 필드를 생략했다. 기본 묶음을 10개/최대 20초, context 16개로 바꾸고 기본 모델과 개인 `.env` Radar 모델을 `gpt-5.4-mini`로 설정했다. diagnostics에 Provider 시도 수, 분석 focus 수, 누적·평균 입력 문자 수를 추가했다.
- 변경 파일 또는 컴포넌트: `backend/app/decision_radar/models.py`, `prompts.py`, `providers.py`, `manager.py`, `backend/app/config/settings.py`, `.env`, `.env.example`, `README_KO.md`, `tests/test_decision_radar.py`, `docs/decision_radar_report.md`, 이 기록.
- 검증 명령과 실제 결과: Radar·설정 관련 묶음은 `38 passed`, 전체 `.venv\Scripts\python.exe -m pytest -q`는 `285 passed, 3 skipped in 11.40s`; SKIP은 기존의 명시적 live flag가 필요한 OpenAI 분석·OpenAI 번역·로컬 번역 시험이다. 최신 166개 final을 외부 API 없이 시간순 재생한 결과 이전 설정은 48회/1,038,809 입력 문자, 새 설정은 26회/327,924 입력 문자로 계산되어 호출 수 45.8%, 전체 입력 문자 68.4% 감소를 확인했다. 캡처 중지 상태에서 프로젝트 전용 프로세스를 재시작하고 health `ok`, capture `idle`, local Worker `ready`, OpenAI mini 번역, OpenAI `gpt-5.4-mini` Radar `idle`, batch 10, wait 20초, context 16을 확인했다. 세션 산출물은 작업 전후 235개, 3,801,691 bytes이며 내용 집계 SHA-256 `2F515FFB821C85A24665462E93AF8B64D16995D7FE40BE3DADF8D833B5BE8BD0`로 동일했다.
- 실패·절충·남은 위험: OpenAI 사용 화면의 총 254회는 최소 이번 세션의 번역 166회와 Radar 44회, 합계 210회를 포함하며 나머지는 같은 기간의 앞선 시험이나 다른 요청일 수 있다. 번역은 final마다 즉시 보여 주기 위해 기본적으로 한 번씩 호출하므로 지연을 늘리지 않고 묶기 어렵고, 이번 최적화는 반복 문맥 비용이 큰 Radar를 우선 대상으로 했다. 오프라인 검증은 새 분류 규칙의 구조와 비용 감소를 증명하지만 실제 모델의 의미 정밀도 향상률은 같은 비민감 대본을 한 번 재시험해야 확정된다. 20초는 최대 대기이며 final 10개가 먼저 모이면 즉시 분석한다. 라이브 API 재시험은 추가 비용과 원문 외부 전송을 발생시키므로 자동 실행하지 않았다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 사용자의 실제 세션 산출물, Radar 상태, API 사용량 단서, 타임스탬프를 함께 분석해 품질 결함과 비용 원인을 분리하고, 공통 prompt·데이터 최소화·batch 정책·관측 지표·회귀·실행 경로 복원·보존 해시 검증까지 수행했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-17 19:45 KST — Context Engine 관련 용어 선택 전송

- 사용자 문제 또는 관찰: Worksite Context Engine의 용어와 사람 이름이 많아지면 전체 목록이 번역과 Radar 요청마다 반복되어 컨텍스트와 입력 토큰이 무거워진다고 관찰했다.
- 사용자가 내린 제품 결정: Deepgram STT 정확도를 위한 전체 keyterm 목록은 유지하되, 외부 번역과 Radar에는 현재 문맥과 관련된 항목만 보내도록 최적화한다.
- Codex가 제안·구현한 내용: Context Engine 정규화가 별칭 교체뿐 아니라 정확한 canonical 표기의 등장도 `context_matches`에 기록하고 같은 항목의 반복 등장은 한 final 안에서 중복 제거하도록 했다. 캡처는 활성 프로필 전체 glossary 대신 해당 final에서 발견된 canonical만 번역 큐에 전달한다. 번역 Manager는 기본·사용자·최근 문맥 후보를 로컬에서 대조해 현재 문장과 최근 3개 문맥에 실제 등장한 용어만 최대 10개 Provider 요청에 포함하며, 관련 용어가 없으면 OpenAI/Gemini 공통 glossary 지시문을 완전히 생략한다. Radar도 활성 프로필 전체와 모든 별칭을 보내지 않고 rolling context의 실제 `context_matches`에서 canonical과 실제 매칭 표기만 최대 10개 구성한다. Deepgram keyterm 경로와 로컬 번역의 용어 보호는 유지했다. 번역 diagnostics에 검토한 후보 수와 실제 전송 용어 수, Radar diagnostics에 실제 전송 context 항목 수를 추가했다.
- 변경 파일 또는 컴포넌트: `backend/app/context_engine/engine.py`, `backend/app/capture/controller.py`, `backend/app/translation/glossary.py`, `translation/manager.py`, `translation/openai_provider.py`, `translation/__init__.py`, `backend/app/decision_radar/manager.py`, 관련 테스트, `README_KO.md`, `docs/decision_radar_report.md`, 수동 체크리스트, 이 기록.
- 검증 명령과 실제 결과: Context·번역·Gemini·Radar 관련 묶음은 첫 실행에서 새 정책과 반대되는 기존 테스트 가정 두 개가 실패했고, 미사용 전체 목록을 기대하던 fixture를 매칭 기반 계약으로 수정한 뒤 `54 passed in 0.99s`. 전체 `.venv\Scripts\python.exe -m pytest -q`는 `287 passed, 3 skipped in 12.13s`; SKIP은 기존 live flag 필요 항목이다. 저장된 가장 긴 비공개 시험 세션 462 final을 외부 API 없이 재생했을 때 request당 후보 17개를 전부 보낸 기존 방식은 용어 항목 7,854회 전송, 새 방식은 39회로 99.5% 감소했다. 공통 번역 지시문 전체 문자 수는 381,612자에서 249,357자로 34.7% 감소했고 462회 중 423회는 관련 glossary가 없어 해당 블록을 생략했다. 회의 원문과 용어 내용은 공개 문서에 기록하지 않았다.
- 실패·절충·남은 위험: 단어 경계는 NFKC·대소문자 무시와 영숫자 경계를 사용하며 현재·최근 문맥에 없는 용어는 외부 모델이 미리 참고하지 않는다. 따라서 STT가 등록 별칭과도 전혀 다른 문자열로 오인식하면 번역 glossary가 그 용어를 받지 못할 수 있지만, Deepgram에는 전체 canonical·별칭 keyterm을 계속 전달해 앞단에서 보완한다. 최대 10개를 넘는 관련 용어가 한 짧은 문맥에 동시에 등장하면 등록 순서상 앞의 10개만 전달된다. 라이브 API 호출은 비용과 원문 외부 전송을 피하기 위해 자동 실행하지 않았다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 실제 코드의 전체 목록 전송 경로를 추적하고 사용자의 저장 세션을 비공개 오프라인 재생해 원인을 정량화한 뒤, STT 정확도와 외부 API 토큰 비용의 경계를 분리한 선택 전송·diagnostics·회귀·문서화를 수행했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-17 22:43 KST — 설치 없는 참석자 초대 링크 공유

- 사용자 문제 또는 관찰: 진행자의 로컬 앱 화면을 설치 없이 다른 참석자와 거의 실시간으로 함께 보고 싶었다. 번역 자막과 Decision Radar만 공유하되 외부 전송 범위, 보관 기간, 추가 지연, 과거 세션과 민감정보의 노출 가능성을 명확히 통제해야 했다.
- 사용자가 내린 제품 결정: 로컬 FastAPI를 인터넷에 직접 열지 않고 별도 cloud relay와 읽기 전용 참석자 사이트를 사용한다. 공유 범위는 임시·확정 원문, 번역, Radar와 근거 ID로 제한하고 오디오·API 키·Provider 설정·과거 세션은 제외한다. 명시적 종료 시 즉시 삭제, 비정상 종료 시 15분 유휴 만료, 방 최대 수명 8시간을 UI에 표시하고 사용자가 확인한 뒤만 공유한다.
- Codex가 제안·구현한 내용: WebSocket fan-out에 장애 격리된 보조 sink를 추가하고, 허용 목록 sanitizer·256개 bounded queue·120ms batch·유한 재시도·30초 heartbeat를 갖는 `ShareRelayManager`를 구현했다. Sites/Vinext+D1 relay는 방 생성 secret과 방별 host token을 분리하고 현재 보기 상태만 저장한다. 참석자 UI는 450ms 폴링으로 partial/final/translation/Radar를 표시하며 한·영 전환, 원문+번역/번역만, 근거 문장 이동, 진행자 연결·종료 상태를 제공한다. 메인 UI에는 외부 전송·비전송·보관 경계, 동의 체크, 시작·종료, 링크 복사·열기와 diagnostics 상태를 추가했다. 사이트 소셜 미리보기는 imagegen으로 새로 만들고 프로젝트 asset으로 포함했다.
- 변경 파일 또는 컴포넌트: `backend/app/sharing/`, `backend/app/websocket/manager.py`, `backend/app/config/settings.py`, `backend/app/api/schemas.py`, `backend/app/main.py`, `frontend/static/index.html`, `style.css`, `app.js`, `i18n.js`, `.env.example`, `.share.env.example`, `.gitignore`, `README_KO.md`, `tests/test_live_share.py`, `tests/test_websocket_manager.py`, `viewer-site/`, `docs/live_share_report.md`, 이 기록.
- 검증 명령과 실제 결과: 공유 단위/API/WebSocket 묶음은 `13 passed`. 전체 `.venv\Scripts\python.exe -m pytest -q`는 `293 passed, 3 skipped in 19.46s`; SKIP은 기존 live OpenAI 분석·번역과 로컬 번역 flag 항목이다. 참석자 사이트는 `pnpm test`의 production build와 3개 계약 테스트, `pnpm run lint`, 비밀 패턴 scan을 모두 통과했다. 로컬 D1 relay에서 방 생성→partial/final/translation/Radar→조회→명시적 삭제→410을 확인했고, 실제 메인 UI에서 동의 전 시작 비활성, 링크 생성, diagnostics 비밀값 부재, 종료 후 링크 숨김·410을 확인했다. 참석자 브라우저에서 번역·Radar·근거 이동·한영 전환·종료 내용 제거와 새 탭 console error/warning 0을 확인했다. Sites owner-only 비공개 배포 버전 1에서도 D1 E2E가 `200→생성→3 events→조회→삭제→410`으로 통과했다. 기존 세션 254개, 3,934,097 bytes의 집계 SHA-256은 작업 전후 `D6A748D68FA5481A360A1189E42BA1C4FFD7951B3963237DF409AC87D786E3EF`로 동일했다.
- 실패·절충·남은 위험: 최초 Node 렌더 테스트는 Cloudflare 전용 `cloudflare:` 모듈을 일반 Node loader가 직접 열지 못해 실패했으며 production build 계약과 실제 브라우저 E2E로 역할을 분리했다. 첫 로컬 relay 생성은 Vite local vars binding 누락으로 401이었고 production env와 동일한 local binding을 추가했다. 두 PowerShell E2E 초안은 예약 변수 `$Host`/`$Home` 사용과 viewer page/API URL 혼동으로 실패했으나 실제 상태를 쓰지 않은 테스트 방이었고 모두 유휴 만료 대상이다. 공식 Sites package script는 Windows에 `bash` 명령이 없어 wrapper가 실패했으며 bundled Git의 Bash-compatible `sh.exe`로 같은 공식 내부 script를 직접 실행해 archive 검사를 통과했다. 현재 사이트는 사용자 1명만 접근 가능한 비공개 production 배포다. 로그인 없는 참석자 공개는 보안 범위를 넓히는 외부 상태 변경이므로 명시적 승인 후 공개 전환·최종 `.share.env` 연결·공개 E2E가 남았다. 방 URL 소유자는 텍스트를 볼 수 있으므로 링크 재전달 통제와 참가자 동의가 계속 필요하다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 공유 데이터 경계, 만료·삭제 정책, 비차단 relay, 읽기 전용 UI, Sites 배포 및 D1 E2E, 비밀 스캔, 브라우저·회귀·세션 불변 검증과 문서화를 수행했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-17 23:41 KST — 회의 중 Decision Radar 탐색 구조 개편

- 사용자 문제 또는 관찰: 결정·Action·미해결·확인 항목이 세로로 한꺼번에 늘어나 회의 도중 전체 페이지를 오르내려야 했고, 무엇을 먼저 봐야 하는지 판단하기 어려웠다. 큰 번역 설정 패널도 실시간 결과 공간을 줄였다. 참석자 사이트에서도 같은 문제가 반복될 수 있었다.
- 사용자가 내린 제품 결정: 번역 설정은 화면 위의 가로 상태 바로 줄이고, Radar는 결정 사항·Action Items·미해결 문제를 탭으로 탐색한다. 현재 결과는 자막처럼 최신 항목을 자동으로 따라가되 사용자가 과거 내용을 읽을 때는 강제로 끌어내리지 않는다. 미해결 문제는 회의 중 기본 초점이 아니므로 필요할 때만 연다. 진행자와 참석자 UI는 같은 정보 구조를 사용한다.
- Codex가 제안·구현한 내용: 기본 `핵심` 탭에 결정과 Action을 함께 묶고 `결정`, `Action`, `미해결` 탭을 추가했다. 기존 `needs_confirmation`은 버리지 않고 미해결 탭에 질문과 함께 보존했다. Radar만 고정 높이 내부 스크롤을 사용하며 최신 위치에서는 새 항목을 자동 추적한다. 사용자가 위로 스크롤하면 자동 추적을 멈추고 `새 항목 N개 · 최신으로` 버튼을 표시한다. 숨겨진 탭은 개수와 새 항목 점만 갱신하고 강제로 전환하지 않는다. 번역 설정은 번역 방향·Provider·상태가 보이는 전체 폭 가로 바로 올리고 상세 설정은 기본 접힘으로 만들었다. 참석자 Sites UI에도 동일한 탭·읽기 일시정지·복귀 동작을 적용했다.
- 변경 파일 또는 컴포넌트: `frontend/static/index.html`, `style.css`, `app.js`, `i18n.js`, `tests/test_decision_radar.py`, `viewer-site/app/room/[roomId]/viewer-room.tsx`, `viewer-site/app/globals.css`, 사이트 계약 테스트, `README_KO.md`, `docs/live_share_report.md`, 이 기록.
- 검증 명령과 실제 결과: 메인 UI·i18n·Radar 대상 테스트 `20 passed`; JS와 i18n syntax check PASS. 전체 `.venv\Scripts\python.exe -m pytest -q`는 `293 passed, 3 skipped in 11.35s`; SKIP은 기존 live OpenAI 분석·번역과 로컬 번역 flag 항목이다. 참석자 사이트 `pnpm run lint`는 경고 없이 PASS했고 `pnpm test`의 production build와 3개 계약 테스트도 PASS했다. 변경 파일 비밀 패턴 scan과 Git diff check가 PASS했으며 Sites 소스 커밋 `0e9f70a`를 push하고 owner-only 비공개 버전 2를 저장·배포했다. 실행 중 FastAPI가 새 asset 버전과 두 새 컨트롤을 실제 응답하는 것도 확인했다. 현재 사용자 세션 261개, 3,973,717 bytes의 작업 전후 집계 SHA-256은 `49630F55F63D3782B5C8AA312E40C8B46BCC3449AE41CC3CA364CF62ED53C345`로 동일했다.
- 실패·절충·남은 위험: 첫 참석자 검증 명령은 Node 경로가 없는 셸에서 실패해 bundled Node를 PATH에 명시한 뒤 통과했다. 한 번은 루트에 `package.json`이 없는데 viewer 명령을 루트에서 실행해 실패했으며 `viewer-site`에서 재실행해 통과했다. 이 작업에서는 공개 접근 정책을 변경하지 않았고 owner-only 배포만 갱신했다. 활성 로컬 공유방을 끊지 않기 위해 서버를 재시작하지 않았으며 정적 asset 버전 변경으로 새로고침 시 새 UI가 로드된다. 실제 장시간 회의에서 탭별 새 항목 누적과 사용자의 스크롤 의도를 반복 확인하는 사용성 시험은 남아 있다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 사용자의 실사용 문제를 정보 우선순위와 스크롤 상태 모델로 분해하고, 진행자·참석자 양쪽에 같은 탐색 계약을 구현해 회귀·비밀·세션 불변·비공개 Sites 배포까지 검증했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.

## 2026-07-18 01:01 KST — 참석자 실시간 공유 패널 접기

- 사용자 문제 또는 관찰: 메인 화면의 세로 길이를 줄인 뒤에도 참석자 실시간 공유 안내와 제어 영역이 항상 펼쳐져 있어 회의 중 자막과 Radar에 집중하기 어려웠다.
- 사용자가 내린 제품 결정: 실시간 공유 영역도 기존 회의 용어·세션·회의 분석처럼 필요할 때 접고 펼칠 수 있게 한다.
- Codex가 제안·구현한 내용: 공유 카드를 기본 닫힘인 접근성 `details/summary` 구조로 전환했다. 접힌 제목 줄에는 공유 상태 배지를 유지해 활성·지연·미설정 상태를 펼치지 않고 확인할 수 있고, 펼치면 기존 전송 범위·보관 기간·동의·시작·종료·링크 제어가 그대로 나타난다. 기존 공통 키보드 Enter/Space와 `aria-expanded` 동기화 로직을 재사용하고 정적 asset 버전을 갱신했다.
- 변경 파일 또는 컴포넌트: `frontend/static/index.html`, `frontend/static/style.css`, `tests/test_phase3_frontend_static.py`, `README_KO.md`, 이 기록.
- 검증 명령과 실제 결과: JS·i18n syntax check PASS. 접이식 UI·공유 API·i18n 대상 테스트는 `23 passed in 0.95s`. 전체 `.venv\Scripts\python.exe -m pytest -q`는 `293 passed, 3 skipped in 20.54s`; SKIP은 기존 live API flag 항목이다. 실행 중 FastAPI 응답에서 새 asset 버전과 `liveShareDetails`·`liveShareDetailsBody`를 확인했다. 현재 세션 275개, 4,080,347 bytes의 집계 SHA-256은 작업 전후 `07575DDA52977B0BE9BA07A0766AE238014FE779274576474EB41825219D9EBA`로 동일했다.
- 실패·절충·남은 위험: 공유가 활성 상태여도 패널을 자동으로 강제 확장하지 않는다. 사용자가 회의 화면을 간결하게 유지하려는 목적을 우선하며, 링크 복사나 공유 종료가 필요할 때 직접 펼쳐야 한다. 실제 브라우저 장시간 사용성 확인은 다음 실사용 회의에서 진행한다.
- GPT-5.6/Codex 증거: 이 Codex 작업에서 기존 공통 접이식 접근성 계약을 재사용해 기능 로직과 저장 데이터는 건드리지 않고 화면 밀도를 개선하고, 전체 회귀와 세션 불변을 검증했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인해야 한다.
## 2026-07-18 21:05 KST · Decision Radar 항목 보존 및 변경 기록

- 사용자 문제·관찰: 실시간 분석이 다음 이야기로 넘어갈 때 이미 표시된 핵심 내용이 사라져 회의의 누적 맥락과 결정 이력을 신뢰하기 어려웠다.
- 사용자와 함께한 제품 결정: 모델의 후속 판단을 실제 삭제로 처리하지 않고, 현재 유효한 항목은 누적 유지한다. 명시적으로 철회된 제안만 상태를 변경하고 접을 수 있는 `변경 기록`에 보존한다. 승인되거나 사용자가 수정한 항목은 기존처럼 자동 변경 대상에서 제외한다.
- Codex가 제안·구현한 내용: Radar 저장 스키마를 v2로 올리고 `active/superseded/resolved/retracted` 수명주기 필드와 변경 사유·시각을 추가했다. 기존 `retract_item_ids` 응답은 삭제 대신 `retracted` 상태 전환으로 병합한다. 모델 프롬프트는 주제 전환·미언급·단순 상세화만으로 철회하지 않도록 보수적으로 변경했다. 메인 UI, 분리 결과 창, 초대 링크 Viewer는 활성 항목만 탭과 개수에 포함하고 과거 항목을 변경 기록에서 근거와 함께 표시한다.
- 변경 파일: `backend/app/decision_radar/models.py`, `backend/app/decision_radar/manager.py`, `backend/app/decision_radar/prompts.py`, `backend/app/sharing/manager.py`, `frontend/static/index.html`, `frontend/static/app.js`, `frontend/static/style.css`, `frontend/static/decision-radar.html`, `frontend/static/decision-radar-window.js`, `viewer-site/lib/relay.ts`, `viewer-site/app/room/[roomId]/viewer-room.tsx`, `viewer-site/app/globals.css`, `tests/test_decision_radar.py`, 본 기록.
- 실제 검증: Radar·공유 집중 테스트 `20 passed`; 전체 회귀 `293 passed, 3 skipped`; 메인 및 분리 창 JavaScript syntax check PASS; Viewer production build PASS. SKIP 3개는 명시적 live API·로컬 모델 실행 조건이 필요한 기존 항목이다.
- 배포 결과: 참석자 Viewer 소스 커밋 `d66364e`를 Sites 비공개 버전 4로 배포했고 기존 URL에서 성공 상태를 확인했다. 접근 정책은 사용자 본인 1명만 허용하는 custom 상태를 유지했다.
- 실패·위험: 첫 Viewer build 명령을 프로젝트 루트에서 실행해 `package.json`을 찾지 못했으나 Viewer 디렉터리와 번들 Node 경로로 재실행해 통과했다. 기존 저장 데이터는 lifecycle 필드가 없으면 `active`로 읽으므로 호환되며, 과거 기록은 메모리·공유 한도를 위해 최대 200개까지만 유지한다. 실제 장시간 회의에서 모델 철회 빈도와 기록 가독성은 추가 관찰 대상이다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자가 보고한 실시간 소실 현상을 병합 로직의 hard delete까지 추적하고, 데이터 호환성·사용자 승인 보호·세 UI 동기화·회귀 검증을 함께 설계하고 구현했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인한다.
## 2026-07-18 22:18 KST · Deepgram 언어별 발화 조립과 번역 확정 경계

- 사용자 문제·관찰: 4초마다 강제 확정된 일본어 전사가 날짜·수식어·서술어 중간에서 잘리면서 번역이 어색해지고, Decision Radar가 다음 조각에 있는 기한을 미해결 질문으로 오판했다. 영어와 일본어의 발화 구조가 다른데 동일한 분절값을 사용하고 있었다.
- 사용자와 함께한 제품 결정: 화면 반응성과 번역 정확도를 분리해 4초에는 안정된 partial만 표시하고, 일본어는 `500ms/1300ms/8초`, 영어는 `400ms/1000ms/6초`, 한국어는 초기값 `450ms/1200ms/7초` 프로필을 번역 방향에 따라 자동 선택한다. 실제 발화 종료·문장/절 경계에서만 번역용 final을 만들고 경계가 없으면 10초에 강제 마감한다.
- Codex가 제안·구현한 내용: Deepgram `Finalize`의 `from_finalize` 결과를 더 이상 즉시 product final로 승격하지 않고 같은 발화 버퍼의 안정 partial로 누적한다. `speech_final`, `UtteranceEnd`, 강한 문장부호, 언어별 soft limit 이후 절 경계 또는 10초 hard limit에서만 final을 한 번 생성한다. 일본어 조각은 공백 없이, 영어 조각은 단어 공백을 유지해 결합한다. 언어별 설정·레거시 전역 fallback·실제 적용 프로필 diagnostics를 추가하고 현재 `.env`의 비밀이 아닌 timing 값도 새 기본값으로 마이그레이션했다.
- 변경 파일: `backend/app/transcription/deepgram_stream.py`, `backend/app/capture/controller.py`, `backend/app/config/settings.py`, `.env`, `.env.example`, `tests/test_deepgram_stt.py`, `README_KO.md`, `frontend/static/index.html`, 본 기록.
- 실제 검증: Deepgram·설정·번역·Radar 집중 회귀 `63 passed`; 전체 회귀 `298 passed, 3 skipped in 12.03s`. 별도 런타임 설정 확인에서 `ja=(500,1300,8)`, `en=(400,1000,6)`, `ko=(450,1200,7)`, checkpoint `4`, hard limit `10`이 로드됨을 확인했다. SKIP 3개는 명시적인 live OpenAI/로컬 모델 실행 플래그가 필요한 기존 항목이다.
- 실패·위험: 첫 전체 회귀에서 이전 Radar UI 작업의 i18n cache-buster만 예전 값으로 남은 정적 계약 실패 1건을 발견해 세 자산 버전을 일치시킨 뒤 전체 회귀가 통과했다. 한국어 프로필은 실측 전 초기값이다. 실제 Deepgram 네트워크·회의 음성에서 발음, 미디어 무음 간격, 지연 분포를 확인하는 수동 A/B는 남아 있다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자의 실제 대본 로그에 나타난 날짜 분절과 Radar 오판을 현재 `Finalize` 병합 로직까지 추적하고, UI partial과 번역 final의 수명주기를 분리해 언어별 설정·하위 호환·진단·회귀 테스트를 함께 구현했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인한다.
# Deepgram 발화 경계 운영 보강 · 2026-07-18 22:45 KST

- 사용자 문제·관찰: 4초마다 전사를 강제 확정하면 일본어 날짜·고유명사·서술어가 뒤 문맥을 보기 전에 잘릴 수 있지만, 20~30초 연속 발화에서는 번역이 지나치게 늦어질 수 있었다.
- 사용자와 함께한 제품 결정: 4초는 같은 발화 카드의 interim 표시 기준으로만 사용하고 Provider 가설은 확정하지 않는다. 일본어 `500/1300/8초`, 영어 `400/1000/6초`, 한국어 초기값 `450/1200/7초`를 선택하며, 자연 경계가 없을 때만 10초를 강제 상한으로 사용한다.
- Codex가 제안·구현한 내용: 4초 `Finalize` 전송을 제거하고 `speech_final`, `UtteranceEnd`, 문장부호, 언어별 soft 절 경계에서만 product final을 생성한다. 10초 hard `Finalize`에는 요청 사유와 오디오 경계를 보관해 늦은 응답이 잘못된 final로 승격되지 않게 했다. 빈 응답·무응답 watchdog·늦게 도착한 중복 응답·종료 직전 trailing interim을 안전하게 처리하고, 일본어는 기본 무공백, 영어·한국어는 단어 공백을 보존한다. 번역과 Decision Radar에는 계속 final만 전달한다.
- 설정 호환성: 새 `HARD_LIMIT`을 생략하면 `max(10초, 모든 언어 프로필 MAX)`로 자동 확장해 기존 10초 초과 설정도 시작 실패하지 않는다. 명시한 hard limit이 soft profile보다 작으면 안전하게 설정 오류로 거부한다. 실제 적용 프로필은 번역 방향을 따르며 diagnostics의 `stt_runtime`에서 확인한다.
- 변경 파일: `backend/app/transcription/deepgram_stream.py`, `backend/app/capture/controller.py`, `backend/app/config/settings.py`, `.env`, `.env.example`, `tests/test_deepgram_stt.py`, `README_KO.md`, `frontend/static/index.html`, 본 기록.
- 실제 검증: Deepgram 운영 타이밍 단위 회귀 `32 passed`; Deepgram·설정 보안 회귀 `51 passed`; 전체 `.venv\Scripts\python.exe -m pytest -q` 결과 `310 passed, 3 skipped in 15.03s`. SKIP 3개는 명시적인 live OpenAI/로컬 모델 실행 플래그가 필요한 기존 테스트다. 기존 세션·JSONL은 읽거나 수정하지 않았다.
- 남은 실측: 자동 테스트는 분절 상태기계와 중복 방지를 검증했다. 실제 일본어·영어 회의 음성의 억양, 네트워크 지연 분포, 체감 자막 속도는 사용자 환경에서 A/B 관찰해 언어별 soft 값을 미세 조정할 수 있다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 요구를 언어별 발화 프로필과 partial/final 수명주기로 분해하고, 별도 리뷰가 재현한 지연 응답·빈 ack·무응답·공백 손실을 회귀 테스트로 전환한 뒤 구현과 전체 회귀까지 완료했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인한다.

## 선택적 로컬 Whisper 전사 재검증 · 2026-07-19 00:11 KST

- 사용자 문제·관찰: Deepgram의 `speech_final`이 일본어 조사, 영어 접속사, 한국어 연결 어미처럼 의미가 끝나지 않은 짧은 조각을 확정하면 번역과 Decision Radar가 불완전한 문장을 사실로 받아들이는 문제가 있었다. 반대로 모든 문장을 다시 전사하면 CPU 부하와 지연이 커지므로, 정상 문장은 현재 속도를 유지하면서 위험 구간만 재확인해야 했다.
- 사용자와 함께한 제품 결정: 완성된 문장과 `はい`·`네`·`Yes` 같은 정상적인 짧은 응답은 즉시 확정한다. 구조적으로 미완성인 `speech_final`만 다음 결과, `UtteranceEnd`, 또는 1.5초 최대 대기시간까지 보류한다. 단어별 신뢰도·짧은 조각·미완성 어미·강제 경계를 위험 사유로 분류하고, 위험 문장만 기존 로컬 Whisper 캐시로 재검증한다. 모델 자동 다운로드, 음성 파일 저장, 기존 세션 재작성은 하지 않는다.
- Codex가 제안·구현한 내용: Deepgram 단어별 confidence와 절대 시작·종료 오프셋을 수집하고 일본어·영어·한국어별 문장 완성도 판정 및 후보 병합 상태기계를 추가했다. 약 14초 PCM16 롤링 버퍼를 메모리에만 유지하며 재연결 replay 오디오를 중복 적재하지 않는다. 선택적 재검증은 CPU `int8`, `beam_size=1`, 동시 실행 1개, 대기 후보 2개, 약 4초 상한으로 제한한다. 기존 `MLT_WHISPER_MODEL` 캐시가 없거나 로딩·추론·시간초과가 발생하면 Deepgram 결과를 즉시 유지한다. 두 결과가 다르면 미완성 문장이 명확히 완성되거나 승인된 Context Engine 인명·용어 근거가 더 강할 때만 Whisper를 채택한다.
- 원문 보존과 전달 계약: 기존 `FinalTranscript` 자료형과 과거 JSONL 형식은 변경하지 않았다. 새 세션에는 `transcription_quality` 이벤트를 append-only로 기록하며 원래 Deepgram 텍스트와 선택 결과를 감사할 수 있다. `save_original=false`이면 이 품질 이벤트에서도 모든 텍스트를 제외한다. 승인된 인명·용어와 등록된 오인식 별칭의 결정론적 Context Engine 보정은 선택된 전사 뒤에 적용하고, 번역과 Radar에는 동일한 확정 `segment_id`를 정확히 한 번만 전달한다.
- 진단과 설정: diagnostics의 `server.stt.selective_recheck`에 활성화 상태, 캐시 전용 여부, 모델, 메모리 버퍼 바이트·초, queue 길이, 요청·채택·실패·시간초과·건너뜀 수를 추가했다. `.env.example`과 `README_KO.md`에 후보 대기시간, 재검증 모델·버퍼·시간초과·queue·local-files-only 설정과 장애 시 fallback을 문서화했다.
- 변경 파일: `backend/app/transcription/deepgram_stream.py`, `backend/app/transcription/audio_ring.py`, `backend/app/transcription/engine.py`, `backend/app/transcription/__init__.py`, `backend/app/capture/controller.py`, `backend/app/config/settings.py`, `backend/app/sessions/repository.py`, `.env.example`, `README_KO.md`, `tests/test_deepgram_stt.py`, `tests/test_audio_ring.py`, `tests/test_selective_recheck.py`, `tests/test_transcription_engine.py`, 본 기록.
- 실제 검증: 일본어·영어·한국어 미완성 조각 결합, 정상 짧은 응답 즉시 확정, `UtteranceEnd` 단일 확정, partial/final 중복 방지, 단어 confidence 위험도, Context Engine 원문 보존, 선택적 Whisper 채택·캐시 부재·실패·시간초과 fallback, 비저장 세션 텍스트 제거, 재연결 절대 오디오 오프셋과 14초 롤링 버퍼를 자동 테스트했다. 집중 회귀는 `54 passed in 9.86s`; 전체 `.venv\Scripts\python.exe -m pytest -q`는 `327 passed, 3 skipped in 17.33s`; Python `compileall`과 프런트엔드 JavaScript 4개 `node --check`는 모두 통과했다. SKIP 3개는 명시적 API 키·live 실행 플래그가 필요한 기존 OpenAI 분석·번역 및 로컬 번역 테스트다.
- 캐시·불변성 확인: `FasterWhisperEngine('small', prefer_cuda=False, local_files_only=True).ensure_loaded()`를 실제 실행해 기존 캐시에서 CPU `int8`로 로드되는 것을 확인했으며 다운로드는 발생하지 않았다. 작업 전후 `data/sessions`는 345개, 4,713,890바이트로 같고, 각 파일 SHA-256을 상대 경로와 결합한 집계 SHA-256도 `AF7B82ACB755A0E63ED6D43F980DB6E27E86A829E06BE5D44F9F1EBF1634018F`로 동일하다.
- 실패·위험·후속 실측: 자동 테스트에서는 실제 Deepgram 유료 네트워크 호출이나 실제 회의 음성을 전송하지 않았다. 문장 완성도와 confidence 임계값은 일본어·영어·한국어 사람 음성 A/B로 미세 조정할 수 있다. faster-whisper의 네이티브 추론 스레드는 Python timeout 시 강제 종료할 수 없으므로, 앱은 결과를 기다리지 않고 Deepgram으로 진행하며 해당 작업이 끝날 때까지 새 재검증을 건너뛴다. 이 때문에 전사·번역·Radar는 멈추지 않지만 과부하 구간에서는 재검증률이 낮아질 수 있다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자가 합의한 Deepgram→위험도 판정→선택적 Whisper→Context Engine→번역·Radar 순서를 상태기계, 메모리 전용 오디오 수명주기, 보수적 결과 선택, append-only 감사 메타데이터와 장애 격리로 구현하고 전체 회귀·구문·세션 불변성까지 검증했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인한다.

## Deepgram Nova-3 + Gemini 실회의 음성 검증 · 2026-07-19 00:41 KST

- 사용자 문제·검증 목표: 자동 테스트만으로는 실제 사람 음성에서 Deepgram 문장 경계, 단어 confidence, 선택적 로컬 Whisper, Gemini 번역 속도와 품질을 판단하기 어려웠다. 사용자가 유료 Deepgram 호출을 승인하고 실제 일본어 Zoom 회의 영상을 시스템 오디오로 약 1분 재생해 제품 전체 경로를 확인했다.
- 사용자와 Codex의 검증 과정: Codex가 서버를 최신 코드로 재시작하고 UI에서 `Deepgram nova-3`, 일본어→한국어, `Gemini API gemini-3.1-flash-lite`, 시스템 Loopback, 선택적 로컬 Whisper `small/cpu/int8` 상태를 확인했다. 사용자는 공개 일본어 회의 영상 `https://www.youtube.com/watch?v=-3YHidnEqx4`의 회의 구간을 직접 재생하고 중지했다. 실제 평가 세션은 `2026-07-19_00-30-00_0e635f`이며 76.669초, final 13개다. 브라우저 재생 준비 중 생성된 무음 세션 `2026-07-19_00-25-03_fed5c0`은 196.530초, segment 0개로 평가에서 분리했다.
- 전달·저장 무결성: 실제 세션은 `final_transcript`, `transcription_quality`, `context_normalization`, `translation`이 각각 13개이며 모든 `segment_id`가 1:1로 대응했다. 중복 final, 누락 번역, queue 잔여, 저장 경고, 오디오 파일 저장은 없었다. 실제 세션 종료 후 Deepgram `last_error=null`, reconnect 0, dropped audio 0, capture dropped frame 0이었다. Decision Radar는 이 검증에서 의도적으로 꺼 두어 STT와 번역만 측정했다.
- Gemini 속도: 번역 13/13 성공. API 자체 latency는 최소 590ms, 중앙값 675ms, 평균 710.9ms, 최대 918ms였다. 발화 종료부터 번역 저장까지는 전체 중앙값 2.716초였고 정상 문장 8개의 중앙값은 1.827초, Whisper 재검증 문장 5개의 중앙값은 3.717초였다. 따라서 Gemini가 병목인 구간은 약 0.6~0.9초이고, 위험 문장에서는 로컬 재검증이 대부분의 추가 지연을 차지했다.
- Deepgram·Whisper 품질: 13개 중 5개가 위험 문장으로 판정됐다(`low_word_confidence` 4, `short_fragment` 1). Whisper 재검증 5개는 최소 1.328초, 중앙값 1.426초, 최대 2.987초였고 실패·timeout·queue skip은 없었다. 보수적 충돌 정책으로 채택은 0개였다. 이 중 Deepgram `にちは。お世になております。`에 대해 Whisper `こんにちは、お世話になっております。`가 명백히 더 정확했으므로 현재 채택 규칙은 정확도보다 보수성에 치우쳤다. 반대로 `聴解→調解`, 두 화자 문장 삭제, `いえいえ→いいよいいよ`처럼 Whisper가 더 나쁜 후보도 있어 전체 결과 교체를 느슨하게 허용하면 오히려 품질이 내려간다.
- 실제 문장 경계 한계: `先日`이 `UtteranceEnd`로 확정되고 다음 final이 `は打ち合わせありがとうございました。`로 분리돼, 현재 `speech_final` 후보 보류만으로는 false `UtteranceEnd` 조각을 결합하지 못했다. 마지막 `ですけれども。`도 독립 문장으로 남아 한국어 `그런데 말입니다.`가 별도 카드로 생성됐다. `けれども`, `ですが`, `先日`, `本日` 같은 일본어 연결 표현과 짧은 시간 부사에 대한 경계 판정 보강이 필요하다.
- 번역 품질 판단: 원문 오류가 있어도 Gemini가 `お世話になっております`, 이벤트 기획 설명 등 핵심 의미를 대부분 자연스럽게 복원했다. 13개 모두 이해 가능한 한국어였으나 `でも役に立ったらうれしいです。→하지만 도움이 되었다면 기쁘겠습니다.`, 분리된 `先日`, 독립된 `ですけれども`는 문맥상 어색했다. 정확한 WER은 영상의 기계 판독 가능한 기준 자막이 없어 산출하지 않았으며, 정성적으로는 번역이 전사 원문보다 견고했지만 문장 경계 품질의 영향을 여전히 받았다.
- 기존 데이터 불변성: 새 준비·평가 세션 디렉터리와 평가 세션의 호환 JSONL만 제외하고 기존 파일을 다시 집계했다. 기존 345개, 4,713,890바이트, 집계 SHA-256 `AF7B82ACB755A0E63ED6D43F980DB6E27E86A829E06BE5D44F9F1EBF1634018F`가 테스트 전과 동일했다.
- 다음 제품 결정 후보: (1) 짧고 미완성인 `UtteranceEnd`도 0.6~1.0초의 작은 grace window에서 다음 final과 결합, (2) 일본어 연결 어미·시간 부사 규칙 확장, (3) Whisper 전체 문장 채택 대신 Deepgram 저신뢰 span과 Whisper 차이를 정렬해 국소 보정, (4) 지연 우선 모드에서는 재검증 중에도 원문을 먼저 표시하고 번역만 후속 갱신하는 방식을 A/B한다. 이번 검증에서는 결과를 객관적으로 남기기 위해 제품 코드는 추가 변경하지 않았다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 실제 설정·제품 UI·유료 Deepgram 스트림·Gemini 번역·로컬 Whisper·append-only 품질 이벤트를 하나의 재현 가능한 세션으로 연결하고, 사용자 재생 구간의 52개 이벤트를 segment 단위로 대조해 지연 분포, 올바른 fallback, 잘못된 경계와 과도하게 보수적인 채택 규칙을 분리해 기록했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인한다.

## Deepgram Nova-3 + OpenAI 번역 후속 실회의 비교 · 2026-07-19 00:56 KST

- 사용자 문제·검증 목표: 직전 Gemini 실회의 시험과 같은 공개 일본어 회의 영상 구간을 OpenAI 번역으로 다시 실행해, 번역 Provider 차이와 Deepgram 문장 분절·선택적 Whisper 지연을 분리하고 다음 패치 우선순위를 정하고자 했다. 사용자가 이미 완료한 저장 세션만 읽었으며 추가 유료 API 호출은 하지 않았다.
- 비교 전제: OpenAI 세션은 75.954초·final 8개, 직전 Gemini 세션은 76.669초·final 13개였다. 재생 시작 위치와 Deepgram 경계가 완전히 같지 않아 번역 문장별 정답률을 직접 순위화하지 않고, Provider 자체 latency와 각 Provider가 받은 원문에 대한 충실도, 공통 의미 구간을 나눠 평가했다.
- 전달·장애 격리 결과: OpenAI 세션은 `final_transcript`, `transcription_quality`, `context_normalization`, `translation`이 각각 8개이며 `segment_id`가 모두 1:1로 대응했다. 누락·중복 번역·세션 경고·저장 오디오는 없었다. 종료 후 diagnostics에서 Deepgram reconnect 0, dropped audio 0, capture dropped frame 0, 번역 queue 0, 선택적 Whisper 요청 4·채택 0·실패 0·timeout 0·skip 0을 확인했다.
- 속도 비교: OpenAI `gpt-4o-mini`의 Provider latency는 최소 1.116초, 중앙값 1.887초, 평균 2.124초, 최대 4.000초였고 첫 호출이 최대값이었다. Gemini `gemini-3.1-flash-lite`의 직전 실측 중앙값은 0.675초였으므로 이번 구간에서 OpenAI 중앙값은 약 2.8배였다. 발화 오디오 종료부터 번역 저장까지의 중앙값은 OpenAI 6.243초, Gemini 2.716초였다. 다만 OpenAI 실행에서는 번역 이전 전사 확정·품질 기록 단계도 중앙값 4.433초로 Gemini 1.871초보다 늦었으므로 전체 차이를 모두 OpenAI 모델에 귀속할 수 없다.
- 품질 판단: 완성된 긴 발화에서는 OpenAI 번역이 자연스러웠지만 일관된 품질 우위는 확인되지 않았다. 강제 경계로 일본어 보조 표현이 두 final에 갈린 구간은 앞 조각을 완료된 미래형, 다음 조각을 독립된 과거형처럼 번역해 합쳐 읽을 때 의미가 깨졌다. 문장 끝이 아닌 동사 기본형에서 잘린 구간도 완료된 과거 사건처럼 번역됐다. 인사 교환에서는 복수 응답 일부를 압축했다. 반대로 Gemini의 어색한 접속사 번역 일부는 Provider 추론보다 Deepgram 원문 오인식의 직접 영향이었다. 따라서 현재 품질의 1차 병목은 번역 모델보다 문장 경계와 STT 원문이다.
- 다음 패치 우선순위: (1) hard `Finalize` 응답을 `speech_final`보다 우선해 반드시 `hard_limit`으로 기록하고 위험 판정을 누락하지 않는다. (2) `UtteranceEnd`도 짧거나 미완성이면 언어별 0.6~1.0초 grace에서 다음 결과와 결합하며, 종결부호를 제거한 뒤 `けれども`·`ですが` 같은 의미상 연결 표현을 검사한다. (3) forced/incomplete final은 UI에 원문 후보를 즉시 표시하되 번역용 canonical final만 짧게 보류해 정확히 한 번 전달한다. (4) Whisper 전체 문장 교체 대신 Deepgram 저신뢰 단어 구간과 Whisper 차이를 정렬해 삭제·시제 변경 위험이 없는 국소 보정만 허용한다. (5) Deepgram 수신, 조립 대기, 재검증, 번역 queue, Provider, 브라우저 표시 시간을 별도 계측해 다음 A/B에서 병목을 직접 확인한다. (6) 번역 Provider 비교는 동일한 저장 원문을 양쪽에 재생하는 비오디오 fixture로 분리한다. (7) OpenAI SDK client는 Provider 적용 뒤 외부 생성 요청 없이 background에서 미리 구성해 첫 번역의 로컬 초기화 지연을 제거하되, UI 설정 적용을 다시 동기식으로 막지 않는다.
- 절충·남은 위험: OpenAI 프롬프트 축약, 이전 문맥 수 감소, 출력 token 상한은 비용과 변동성을 줄일 수 있으나 이번 실측의 핵심 오류인 문장 분절을 해결하지는 못한다. 세션 시작 시 유료 예열 요청은 첫 호출 지연을 숨길 수 있지만 비용과 외부 전송을 추가하므로 기본 동작으로 권장하지 않는다. 이번 작업은 분석과 기록만 수행했으며 제품 코드는 변경하지 않았다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자가 남긴 OpenAI 실회의 세션 32개 이벤트와 직전 Gemini 52개 이벤트를 원문·번역·품질·시간축·diagnostics 기준으로 대조해 Provider latency와 앞단 전사 지연을 분리하고, 번역 오류를 만든 실제 경계 상태기계의 후속 패치 순서를 도출했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인한다.

## 실회의 비교 후 STT·번역 지연 패치 · 2026-07-20 12:13 KST

- 사용자 문제·관찰: 같은 공개 회의 구간을 Gemini와 OpenAI 번역으로 각각 시험한 결과, 번역 Provider 차이보다 Deepgram의 잘못된 발화 경계와 위험 문장 재검증 대기가 전체 체감 지연과 의미 왜곡에 더 크게 작용했다. 특히 짧은 `UtteranceEnd`, 일본어 연결 표현, hard `Finalize` 경계, 첫 SDK client 구성 시간을 서로 분리해 다룰 필요가 있었다.
- 사용자와 함께한 제품 결정: 완성 발화는 지연 없이 확정하고, 의미상 미완성인 발화만 짧게 보류한다. 위험 원문은 재검증 중에도 임시 자막으로 즉시 보여 주되 저장·번역·Radar에는 canonical final만 정확히 한 번 전달한다. Whisper는 전체 문장을 느슨하게 바꾸지 않고 Deepgram 저신뢰 구간의 작은 차이만 보수적으로 반영한다. Provider 비교는 동일 원문을 동일 조건으로 보내는 별도 명시적 도구로 분리한다.
- Codex가 구현한 경계 보강: `UtteranceEnd`도 미완성 발화이면 다음 결과를 기다리게 했고 일본어 0.9초, 영어 0.7초, 한국어 0.8초의 언어별 grace를 추가했다. 일본어 시간 부사·연결 조사·연결 어미를 종결부호 제거 후 판정하고, 정상적인 짧은 응답은 즉시 확정한다. hard `Finalize`가 `speech_final`로 도착해도 `hard_limit` 사유를 우선 보존한다. 보류 timeout 시 최신 interim을 결합하며, 늦게 온 안정 결과는 단어 timestamp로 이미 확정한 접두부를 제거해 보이지 않은 접미부만 살린다.
- Codex가 구현한 검증·전달 보강: 위험 final은 `quality_review` 임시 자막을 먼저 방송하고, 기존 메모리 전용 PCM·캐시 전용 Whisper 재검증 뒤 canonical final을 만든다. 단어별 confidence 위치와 두 전사를 정렬해 짧은 삽입·교체만 허용하고 의미 삭제, 절 감소, 근거 없는 한자 교체는 거부한다. 강제 또는 미완성 경계 메타데이터를 번역 요청에 전달해 Provider가 없는 시제·결정·문장 종결을 만들어내지 않도록 했다. 원래 Deepgram 결과와 선택 근거는 새 세션의 append-only 품질 이벤트에만 추가하며 기존 `FinalTranscript`와 과거 JSONL은 변경하지 않았다.
- 지연 진단과 Provider 준비: STT에는 오디오 끝→Provider 수신과 canonical 처리, 번역에는 queue 대기·Provider·전체 지연의 최근·평균·최대값을 추가했다. OpenAI와 Gemini SDK client 구성은 선택된 Provider에서만 background로 수행하고 상태 조회·설정 적용은 이를 기다리거나 생성 API를 호출하지 않는다. 로컬 실행에서 설정 조회는 첫 18ms·이후 약 4~6ms, Gemini 적용 125ms, OpenAI 적용 158ms로 관찰됐고 Provider 전환 후 정리까지 포함한 가장 긴 측정도 740ms였다. 이 측정 중 번역 생성 호출은 0회였다.
- 동일 원문 A/B 도구: UTF-8 한 줄당 한 문장을 OpenAI와 Gemini에 context 없이 동시에 보내는 `scripts/compare_translation_providers.py`를 추가했다. 세션 저장과 자동 재시도는 하지 않으며 `RUN_TRANSLATION_AB_TEST=1`과 `--confirm-external-calls`가 모두 있어야 외부 호출한다. 이번 자동 검증에서는 비용과 외부 전송을 막기 위해 거부 경로만 실행했고 실제 유료 A/B는 수행하지 않았다.
- 변경 파일·컴포넌트: Deepgram 조립기, 캡처 controller, 언어별 settings, Context/Whisper 선택 로직, 번역 request·manager·OpenAI·Gemini Provider, 세션 repository, A/B helper·CLI, 환경 예시, 한국어 README, 관련 단위·API 테스트와 본 기록.
- 실제 검증: Deepgram·선택적 재검증·번역·API 집중 회귀 `106 passed`; Gemini/OpenAI 준비 경로 회귀 `45 passed`; Windows 타이머 해상도에서 대기 queue가 0ms로 보이던 경계는 최소 1ms로 보정하고 동일 테스트를 20회 연속 통과시켰다. 최종 전체 `.venv\Scripts\python.exe -m pytest -q`는 `339 passed, 3 skipped in 21.08s`; SKIP 3개는 명시적 live OpenAI 분석·번역 또는 로컬 번역 실행 플래그가 필요한 기존 테스트다. Python `compileall`, 프런트엔드 JavaScript 4개 구문 검사, A/B 이중 승인 거부 검사가 모두 통과했다. 재시작 후 FastAPI와 로컬 번역 Worker가 각각 고유 PID로 `ready`였고 새 언어별 grace와 번역 latency 진단을 실제 API에서 확인했다.
- 기존 데이터 불변성과 남은 실측: 작업 전후 `data/sessions`는 364개, 4,810,055바이트이며 파일별 SHA-256을 상대 경로와 결합한 집계 SHA-256 `8F263043093F9A4527F9A3DB575C53A26831118BF4355EB018E9CB87B7829290`가 동일하다. 실제 유료 STT·번역 호출을 이번 패치 검증에서 추가하지 않았으므로, 다음 실제 회의 A/B에서 `server.stt.latency`와 `server.translation_queue.latency`로 잘린 문장 수, 국소 보정 채택률, 오디오 끝→번역 완료 지연을 다시 평가해야 한다. 브라우저 paint 시간은 서버 진단과 분리된 후속 계측 대상이다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 실제 두 Provider 세션의 병목 분석을 Deepgram 상태기계, 보수적 span 보정, 임시·canonical 자막 수명주기, 불완전 원문 번역 계약, 비동기 SDK 준비, 세부 latency 계측과 재현 가능한 A/B 도구로 전환하고 전체 회귀·실행 상태·기존 세션 불변성까지 검증했다. Devpost 제출용 Codex Session ID는 임의로 기록하지 않으며 제출 전에 `/feedback` 결과로 확인한다.

## OpenAI·Gemini 동일 원문 10문장 A/B · 2026-07-20

- 사용자 요청과 실험 설계: 사용자가 직접 수동 비교하는 대신 동일한 일본어 회의 문장 10개를 OpenAI와 Gemini 번역 Provider에 context 없이 각각 보내 속도·품질·성공률을 비교하도록 승인했다. 결정, 담당자, 기한, 미해결 비용, 후속 회의가 섞인 합성 문장을 사용했으며 세션·JSONL·Radar에는 저장하거나 전달하지 않았다.
- 실행 중 발견한 도구 오류: 첫 실행은 두 Provider 요청 처리를 마친 뒤 Windows CP949 콘솔이 일본어 JSON을 출력하지 못해 결과 표시 단계에서 실패했다. API 호출이 이미 끝난 상태였으므로 같은 입력을 다시 실행했고 외부 호출 시도는 계획보다 한 세트 늘었다. 재발 방지를 위해 비교 CLI의 stdout·stderr를 UTF-8로 명시했으며 API 키나 Provider 원문·응답을 제품 로그에 추가하지 않았다.
- 두 번째 실행 결과: OpenAI `gpt-4o-mini`는 10/10 성공, Provider latency 중앙값 1,132ms·평균 1,212.5ms였다. Gemini `gemini-3.1-flash-lite`는 6/10 성공, 성공 건 중앙값 721ms·평균 약 756.7ms였고 4건은 `GEMINI_QUOTA_EXHAUSTED`로 안전하게 실패했다. 첫 문장 전체 경과시간은 SDK cold client 준비가 포함되어 OpenAI 3,277ms, Gemini 2,771ms였으며 Provider latency와 분리되어 기록됐다.
- 품질 판단: 양쪽이 모두 성공한 6문장에서는 Gemini가 일부 회의 표현을 더 간결하고 자연스럽게 옮겼고 OpenAI도 의미·담당자·날짜·시간을 대체로 정확히 유지했다. OpenAI 결과 1건에는 일본어 일부가 번역되지 않고 섞이는 명확한 결함이 있었으며, 나머지 9건은 실용적으로 이해 가능한 수준이었다. 따라서 성공 결과의 자연스러움은 Gemini가 근소 우세했지만 이번 연속 실행의 가용성은 OpenAI가 명확히 우세했다.
- 제품 해석과 남은 위험: Gemini 성공 건의 중앙 지연은 OpenAI보다 약 36% 짧았으나 무료 quota에서 번역과 Radar를 함께 운용하면 누락 위험이 커질 수 있다. 현재 제품처럼 원문을 계속 유지하고 Provider 실패만 해당 segment에 격리하는 정책이 필요하다. 한 번의 합성 10문장 시험은 통계적 모델 순위를 확정하지 않으며, 실제 회의에서는 Gemini를 속도 우선·OpenAI를 안정성 우선 후보로 두고 diagnostics의 성공률과 warm latency를 함께 비교해야 한다.
- 검증: UTF-8 출력 수정 뒤 동일 A/B CLI가 일본어 원문과 한국어 결과를 정상 출력했다. 비교는 명시적 이중 승인 환경에서만 실행됐고 종료 후 승인 환경변수를 제거했다. 기존 세션 저장소는 수정하지 않았다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자의 실제 비용 승인 아래 동일 입력·무문맥·무재시도 조건을 고정해 두 Provider를 비교하고, 콘솔 인코딩 실패를 도구 결함으로 분리해 수정한 뒤 성공률·지연·번역 품질·무료 quota 위험을 제품 의사결정으로 정리했다.

## NVIDIA Riva Translate 4B A/B 비교 추가 · 2026-07-20

- 기존 동일 원문 10문장 비교 도구에 NVIDIA 호스팅 `nvidia/riva-translate-4b-instruct-v1.1`을 세 번째 비교 대상으로 추가했다. 제품 UI나 기본 번역 실행 경로에는 등록하지 않고 명시적 A/B 도구에만 격리했다.
- NVIDIA 공식 OpenAI 호환 Chat Completions 엔드포인트를 사용하며 `temperature=0`, 자동 재시도 0, 문장별 최대 출력 512 토큰으로 제한했다. 입력은 기존 OpenAI·Gemini와 동일한 context-free 원문이며 세션과 JSONL에는 저장하지 않는다.
- 세 외부 API로 원문이 전송된다는 이중 승인 게이트를 유지했다. `NVIDIA_API_KEY`가 없으면 health check 단계에서 실제 번역 호출 전에 전체 비교를 거부하는 것을 확인했다.
- 성공 응답, 정확한 모델·언어 방향 프롬프트, 키 부재, 빈 응답, client 종료를 단위 테스트로 검증했다. 실제 NVIDIA 호출과 품질·지연 비교는 로컬 `.env`에 NVIDIA 키를 설정한 뒤 같은 10문장 fixture로 수행하도록 남겼다.

## 유료 Gemini 3.1 Flash-Lite와 OpenAI 재비교 · 2026-07-20

- 동일한 합성 일본어 회의 문장 10개를 context-free 조건에서 `gpt-4o-mini`와 `gemini-3.1-flash-lite`에 동시에 전달했다. 사용자가 유료 Gemini 전환 후 명시적으로 실제 외부 호출을 승인했으며 세션·JSONL에는 기록하지 않았다.
- 양쪽 모두 10/10 성공했다. 이전 무료 Gemini 비교에서 발생했던 quota 실패 4건은 이번 실행에서는 발생하지 않았다.
- Provider latency는 OpenAI 중앙값 1,280.5ms·평균 1,468.2ms, Gemini 중앙값 636.5ms·평균 731.0ms였다. 첫 요청을 포함해도 Gemini가 더 빨랐고, warm 중앙값 기준 약 2.0배 빨랐다.
- 두 모델 모두 날짜·시간·결정 여부·미결 상태를 보존했다. Gemini는 3개사와 수정 견적서의 수식 관계를 더 직접적으로 보존했고, OpenAI는 `進捗会議`를 `진행 회의`로 더 자연스럽게 옮겼다. 전체적으로 품질은 동급 내지 Gemini 근소 우세, 지연과 이번 실행의 연속 성공성은 Gemini 우세로 판단했다.
- 비교 CLI에 `--providers openai gemini`와 같은 선택 옵션을 추가해 NVIDIA 키가 없어도 승인된 두 Provider만 독립 비교할 수 있게 했다. 기존 기본값은 세 Provider 전체 비교로 유지했다.

## 다국어 영어 데모 전환과 공개 제출 기반 · 2026-07-20 15:23 KST

- 사용자 문제·제품 결정: 영어권 심사위원에게 일본어→한국어 Replay를 보여 주는 것보다 영어 결과가 즉시 이해되도록 언어 구성을 바꾸기로 했다. 먼저 제품에 일본어→영어와 영어→일본어를 추가해 실제 Gemini 번역을 검증하고, 최종 공개 Replay는 한국어 원문→영어 번역·영어 Decision Radar로 다시 기록하기로 확정했다.
- 번역 방향 구현: 설정·API 스키마·캡처 controller·한/영 UI에 `ja_to_en`, `en_to_ja`를 추가했다. 두 방향은 로컬 Whisper 또는 Deepgram STT를 사용할 수 있지만 기존 로컬 M2M100 Worker가 목표 한국어 전용이므로 Gemini/OpenAI 번역이 적용된 경우에만 캡처를 시작한다. 한국어 원문 방향은 기존처럼 Deepgram 전용이며, 여섯 방향의 원문·목표 언어를 하나의 계약으로 검증한다. 기존 `.env` 기본 방향과 Provider는 자동 변경하지 않았다.
- Radar 언어 연결: final WebSocket/Radar payload에 목표 언어를 추가하고 Radar batch가 해당 목표를 Provider prompt에 전달하도록 했다. 한국어, 영어, 일본어 결과 지시와 미정 표기 `미정`, `TBD`, `未定`을 분리했다. 이전 이벤트처럼 목표 언어가 없는 입력은 한국어를 기본값으로 유지한다. 따라서 최종 한국어→영어 데모에서는 번역뿐 아니라 결정·Action·미해결 항목도 영어로 생성된다.
- 실제 외부 번역 검증: 세션 저장과 Radar를 거치지 않는 명시적 외부 호출 도구로 Gemini `gemini-3.1-flash-lite`에 일본어→영어 2문장과 영어→일본어 2문장을 각각 1회 전송했다. 4/4 성공했고 Provider latency는 733–952ms, 전체 중앙값 843ms였다. 인명, 금요일 오후 3시 기한, 8월 20일 결정, 월 서버 비용 미결 상태가 모두 보존됐다. 임시 입력 파일은 실행 후 제거했고 기존 세션에는 기록하지 않았다.
- 공개 Replay 기반 변경: Replay exporter가 세션의 실제 `translation_direction`과 각 translation event의 목표 언어 일치를 검증하고 언어쌍을 fixture에 기록하도록 수정했다. 공개 UI의 원문·번역 언어 표시는 fixture를 따라 자동 전환된다. 한국어→영어 가상 회의 대본과 의도된 평가 신호를 별도 공개 문서로 만들었으며, 실제 Provider 결과를 모범 답안으로 재작성하지 않는 원칙을 명시했다. 공개 fixture 단위 테스트는 사설 세션·segment ID 제거, 근거 연결, 언어쌍, 원본 fixture SHA-256 불변을 검증한다.
- 공개 저장소 준비: 영문 README, MIT License, 개인정보·장애 격리·Codex/GPT-5.6·Build Week 전후 범위를 추가했다. `work`, 키, PID, 런타임, 모델, 가상환경, 세션, Context/Radar 로컬 저장소는 Git 추적에서 제외된다. 기존 viewer-site 커밋 이력은 완전한 비공개 Git bundle로 프로젝트 바깥에 검증·보존한 뒤 중첩 저장소를 제거하고 단일 루트 Git 저장소를 초기화했다. Lite allowlist에는 영문 README와 License를 추가했다.
- 변경 파일·컴포넌트: 번역 settings/schema/controller, Radar models/manager/prompts/providers, 메인 UI와 i18n, `.env.example`, `README_KO.md`, 영문 `README.md`, `LICENSE`, `.gitignore`, Replay exporter/model/UI, 공개 데모 대본, Lite builder, 관련 Python·JavaScript 테스트와 본 기록.
- 자동 검증: 새 방향·Radar·Replay 집중 회귀 `53 passed`, 전체 `.venv\\Scripts\\python.exe -m pytest -q`는 `352 passed, 3 skipped in 18.67s`였다. SKIP 3개는 명시적 라이브 OpenAI 분석·번역 또는 로컬 번역 실행 플래그가 필요한 기존 테스트다. Python `compileall`, 프런트·Electron·Replay JavaScript 7개 구문 검사, viewer production build와 viewer 테스트 `7/7`이 통과했다. 작업 시작 시 보존한 기존 JSONL 85개의 경로·길이·SHA-256을 다시 비교해 변경 0, 누락 0을 확인했다.
- 남은 외부 조건: 현재 PC에 한국어 Windows TTS 음성이 없어 최종 60–90초 Deepgram 실제 음성 실행은 수행하지 않았다. `Build Week Demo EN` Context profile과 대본은 준비했고 기존 활성 profile은 복원했다. 공개 fixture는 아직 이전 일본어→한국어 실제 실행본이므로 한국어 음성 실행·근거 검증 전에는 최종 배포로 주장하지 않는다. GitHub CLI가 설치되어 있지 않아 공개 원격 저장소 생성·push·Release는 아직 수행하지 않았다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자의 심사위원 관점 언어 변경을 여섯 방향 계약, Provider 호환성, 목표 언어 연동 Radar, 실제 비용 제한 번역 검증, 동적 공개 Replay 스키마, 데이터 불변성과 단일 공개 저장소 경계로 전환했다. Devpost 제출용 Codex Session ID는 제출 전에 실제 `/feedback` 결과로 확인한다.

## 검증된 한국어→영어 Replay와 Luna 최종 선택 · 2026-07-20 17:00 KST

- 사용자 결정: 영어권 심사위원용 최종 데모는 `Deepgram Nova-3 한국어 전사 → 승인된 Context Engine 보정 → Gemini 3.1 Flash Lite 영어 번역 → GPT-5.6 Luna 영어 Decision Radar`로 고정했다. Terra는 최종 데모에 사용하지 않는다.
- 모델 선택 근거: 동일한 13개 확정 문장 입력에서 Terra는 9개 항목(결정 3, Action 5, 미해결 1), Luna는 12개 항목(결정 3, Action 6, 미해결 3)을 생성했고 Luna의 근거 ID는 모두 유효했다. 비교 과정에서 Terra 외부 요청 3건이 발생했으며, 그 후 추가 Terra 호출을 중단했다.
- 실제 오디오 실행: 개인정보가 없는 89.04초 합성 업무회의 오디오를 사용자가 승인한 유료 Deepgram과 선택된 Gemini·OpenAI Provider로 실제 실행했다. 확정 원문 13개와 영어 번역 13개가 모두 생성됐고, 번역 Provider latency는 중앙값 843ms, p95 1,172ms, 최대 1,265ms였다.
- 최종 Radar 결과: revision 4에서 결정 3, Action 4, 미해결 질문 3으로 총 10개 항목이 만들어졌다. 10개 항목의 `evidence_segment_ids`는 10/10 모두 실제 공개 원문 segment에 존재했고 누락 근거는 0개였다. 실제 모델 출력을 모범 답안으로 재작성하지 않았다.
- 전사 보강: Deepgram smart formatting이 고신뢰 한국어 날짜를 비정상 형식으로 만드는 경우를 `malformed_date_format` 위험으로 분류했다. 기존 캐시의 로컬 Whisper가 유효한 명시적 날짜를 제공하고 문장 구조가 보존될 때만 선택하며, 원래 Deepgram 결과는 append-only 품질 메타데이터에 보존한다. 번역 prompt에는 한국어 날짜의 숫자+조사 경계를 명시했다.
- 공개 fixture: 사설 세션 ID·내부 경로·키·원래 segment ID를 제거한 43개 상대 시간 이벤트, 112,637ms Replay를 `viewer-site/public/demo/verified-session.json`에 내보냈다. 오디오는 디스크·JSONL·fixture에 저장하지 않았다. `/demo`는 키와 Provider 호출 없이 재생·일시정지·처음부터·1×/2×·근거 이동을 제공한다.
- UI 검증: 새 dev server의 랜딩과 `/demo`를 비로그인 상태로 열었고 Nova-3, Gemini 3.1 Flash Lite, GPT-5.6 Luna 표시, 중앙값·p95, 10/10 근거, Replay 제어를 확인했다. 근거 버튼 클릭 후 대상 원문 highlight 1개, console error·warning 0개였다.
- 회귀·배포 검증: 전체 Python은 `358 passed, 3 skipped in 20.23s`, JavaScript 7개 구문 검사와 viewer lint·production build·7개 Replay 테스트가 통과했다. 236개 Git 후보의 키 패턴·사용자 경로·사설 세션 ID는 0건이었다. Lite ZIP은 355,155 bytes, 112 entries, 금지 entry 0, manifest 1, SHA-256 `FA0326E19D21962AE711801EAC648CED73A86FD0CEB16F6E45FE5C3D1FA5F9E5`다. 새 폴더에서 `setup.bat /no-local → start_all.bat → stop_all.bat`를 실행해 health `ok`, 서버 PID 기록, 종료 후 listener 0·PID 파일 0을 확인했다.
- 기존 기록 불변성: 작업 전 보존한 216개 기존 세션 파일(그중 JSONL 91개)을 파일별 SHA-256으로 재비교했고 변경 0, 누락 0이었다. 추가 32개는 이후 사용자가 승인한 실제 Provider·데모 검증에서 새로 생성된 파일이며 Git·Lite 배포물에는 포함하지 않는다.
- GPT-5.6/Codex 증거: 본 Codex 작업에서 사용자의 Terra→Luna 비용·품질 가설을 동일 입력 비교와 실제 오디오 E2E로 검증하고, 재생 가능한 키 없는 공개 fixture, 근거 무결성 검사, 배포·데이터 불변성 검증으로 전환했다. Devpost의 필수 Codex Session ID는 실제 `/feedback` 결과만 기록한다.
