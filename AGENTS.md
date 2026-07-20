# AGENTS.md

## OpenAI Build Week 기록

- 2026-07-15 이후 이 프로젝트의 제품·코드·테스트·제출 자료 변경은
  `docs/BUILD_WEEK_LOG.md`에 같은 작업 안에서 함께 기록한다.
- 기록에는 KST 시각, 사용자가 제기한 문제, 사용자의 제품 결정, Codex가 제안하거나
  구현한 내용, 변경 파일/커밋, 실제 검증 결과, 절충과 남은 위험을 포함한다.
- Submission Period 시작 전 기능과 이후 신규 기능을 섞어 신규 성과로 주장하지 않는다.
- GPT-5.6 사용 여부와 Codex Session ID는 실제로 확인한 경우에만 기록한다.
- API 키, 개인 음성, 실제 회의 원문, 사용자 로컬 경로는 Build Week 문서·공개 README·
  데모 자료에 기록하지 않는다.
- 실행하지 않은 테스트를 PASS로 쓰거나 측정하지 않은 성능을 실측값으로 쓰지 않는다.
- 공식 규정과 이 기록이 충돌하면 <https://openai.devpost.com/rules>가 우선한다.
- 아래 초기 Phase 범위 이후 사용자가 명시적으로 승인해 이미 추가된 Deepgram,
  Gemini, 로컬 번역 sidecar, 다국어 방향, 자막 pop-out/표시 모드, Lite 배포와
  안정화 기능은 현재 프로젝트 기준선으로 보존한다. 새로운 범위 확장은 계속 사용자의
  명시적 요청을 따른다.

## 기준과 범위

- 상위 작업 폴더의 `PROJECT_SPEC.md`가 전체 프로젝트 요구사항 기준이며, 이 프로젝트의 `PROJECT_SPEC.md`는 Phase 1 최초 요청 기록이다.
- Phase 3 작업은 사용자가 제공한 Phase 3 요청서와 전체 프로젝트 요구사항을 함께 따른다.
- 현재 구현 범위는 Phase 3의 세션 기록·내보내기·회의 분석까지다.
- Phase 3A 세션·내보내기 테스트를 통과한 뒤에만 Phase 3B 분석을 구현한다.
- 화자 분리, 화자 이름 판정, 동시 시스템·마이크, 오디오 녹음/재생, React/Vite/Tauri/Electron, overlay/Media Caption Mode, 특정 프로세스 캡처, DRM, 배포·로그인·다중 사용자·협업, 대형 로컬 LLM 설치는 추가하지 않는다.
- 기존 `WhisperLive` 저장소와 가상환경을 수정하거나 코드를 무단 복사하지 않는다.

## 개발 환경

- Windows 11, Python 3.11, 프로젝트 전용 `.venv`를 사용한다.
- 전역 패키지 설치, 관리자 권한 요청, Windows 오디오/시스템 설정 변경을 하지 않는다.
- 설치: `setup.bat`
- 실행: `start_all.bat`
- 종료: `stop_all.bat`
- 테스트: `.venv\Scripts\python.exe -m pytest -q`
- 장치 진단: `.venv\Scripts\python.exe scripts\check_audio_devices.py`

## 구조 경계

- `backend/app/audio/`: 장치 모델·조회·PyAudioWPatch 어댑터. 다른 앱 모듈은 PyAudioWPatch를 직접 호출하지 않는다.
- `backend/app/transcription/`: VAD, 발화 버퍼, faster-whisper 엔진, 언어 판정, 중복 제거.
- `backend/app/capture/`: 캡처·전사 lifecycle 조정.
- `backend/app/translation/`: Provider, 용어집, bounded 비동기 번역 큐와 오류 격리.
- `backend/app/websocket/`: 연결과 공개 이벤트.
- `backend/app/sessions/`: append-only final/translation 이벤트, lifecycle, legacy JSONL 호환, 복구와 atomic export. partial과 원본 PCM은 저장하지 않는다.
- `backend/app/analysis/`: none/rule-based/OpenAI/Gemini 분석, chunking, evidence 검증과 취소. 외부 분석은 사용자 명시 요청 전에는 실행하지 않는다.
- `frontend/static/`: 빌드 도구가 필요 없는 HTML/CSS/JavaScript.

오디오 callback에서는 복사와 bounded queue 삽입만 수행한다. 모델 추론, 파일 I/O, WebSocket 송신을 callback에 넣지 않는다. 예외는 FastAPI 프로세스를 종료하지 않도록 캡처 세션 경계에서 안전한 공개 오류로 변환한다.

## 공개 계약

- REST: 기존 health/audio/settings/capture/translation 계약과 Phase 3 sessions/download/analysis 계약.
- start body: `{ "source": "system|microphone", "device_id": "opaque-id", "model": "tiny|base|small|medium" }`.
- WebSocket: 기존 이벤트와 translation/session/analysis 상태 이벤트, 초기 `snapshot`. 대형 세션·분석 전체 본문은 WS로 반복 전송하지 않는다.
- 상태: `idle`, `listening`, `paused`, `transcribing`, `error`, `stopped`.
- 언어: `ja`, `en`, `mixed`, `unknown`. 낮은 신뢰도나 지원 외 언어를 ja/en으로 강제하지 않는다.
- 오류 응답과 로그에 API 키, 전체 환경변수, 사용자 파일 내용, 로컬 모델 캐시 경로를 노출하지 않는다.

계약을 바꾸면 백엔드 스키마, 프론트 정규화, 자동 테스트, `README_KO.md`를 함께 검토한다. partial 자막은 번역하지 않고 final만 번역 큐에 등록한다.

## 변경과 검증 원칙

- 기존 사용자 변경을 보존하고 관련 없는 파일을 정리하거나 되돌리지 않는다.
- 장치 ID는 opaque string으로 다룬다. 출력과 Loopback 매칭이 모호하면 추측하지 않는다.
- CUDA는 실제 모델 초기화 성공으로만 확정한다. 실패하면 오류를 기록하고 CPU `int8`로 fallback한다.
- near-real-time이라고 표현하며 완전한 streaming이라고 쓰지 않는다.
- 테스트용 오디오는 비민감 샘플만 사용한다.
- 실행한 검증만 `PASS`/`MANUAL PASS`로 기록한다. 실패는 `FAIL`/`MANUAL FAIL`, 미실행·전제 부족은 구체적 사유와 함께 `SKIP`이다.
- 각 결과에는 명령, 오류 요약, 실패 또는 SKIP 사유를 남긴다.

Phase 3 완료 시 `docs/phase3_report.md`를 작성하고 Phase 4 기능 구현을 시작하지 않는다.
