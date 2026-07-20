# Local Translation 제품 통합 검증 보고서

검증일: 2026-07-12 (Asia/Seoul)

## 작업 범위

이번 변경은 이미 설치·검증된 아래 런타임과 모델을 정식 애플리케이션 실행 경로에 연결하는 작업만 수행했다.

- Worker 런타임: `.venv-translation`
- CTranslate2 모델: `models\translation\m2m100_418m-int8`
- 실행값: CPU, `int8`, `inter_threads=1`, `intra_threads=2`, `beam_size=1`, 번역 동시성 1, Windows `BelowNormal`

새 모델 다운로드나 변환은 수행하지 않았다. 메인 `.venv`에도 Torch, Transformers, SentencePiece를 설치하지 않았다. Phase 4의 다른 안정화 항목은 시작하지 않았다.

## 제품 통합 결과

- FastAPI lifespan이 별도 Worker 프로세스를 시작하고 모델 준비 완료까지 기다린다. 준비 실패는 서버 시작을 중단하지 않으며 원문 전사는 계속 사용할 수 있다.
- 하나의 공유 Supervisor가 Worker를 소유하고, `local` Provider는 이를 참조하는 얇은 adapter로 동작한다. Provider 전환이나 임시 health check가 Worker를 종료하지 않는다.
- Worker는 JSONL stdin/stdout 프로토콜을 사용하므로 별도 네트워크 포트를 열지 않는다.
- Worker 요청은 Supervisor 내부 lock으로 직렬화되어 실제 번역 동시성 1을 보장한다.
- Worker 종료·파이프 오류·타임아웃은 번역 실패로 격리되고 bounded backoff로 자동 복구된다.
- 연속 시작 실패는 5회에서 circuit breaker로 멈춰 영구 모델 오류가 CPU/RAM을 무한히 churn하지 않으며, 명시적 restart로 다시 시도할 수 있다.
- Worker는 모델 로드 전에 실제 interpreter PID를 통지하고 parent watchdog을 시작한다. 모델 로드 timeout에서도 실제 PID 종료를 확인하기 전 PID 파일을 지우거나 replacement를 시작하지 않는다.
- 이전 실행의 Worker PID 파일은 명령행 marker와 프로젝트 경로로 조정한 뒤에만 새 Worker PID로 교체한다.
- `.run\server.pid`와 `.run\translation-worker.pid`를 별도로 기록한다.
- 종료 스크립트는 PID, 명령행 marker, 프로젝트 절대 경로가 모두 일치하는 프로세스만 종료한다. Python 전체 종료 명령은 사용하지 않는다.
- `GET /api/diagnostics` 및 Worker 전용 상태 API는 경로·원문·비밀값을 노출하지 않는 상태만 반환한다.
- UI는 Local Worker의 준비/복구/사용 불가 상태, 실제 PID, 로컬 Provider 가용성을 주기적으로 갱신한다.
- `none`과 `openai` Provider의 기존 전환 경로는 유지했다.
- 모델 prewarm은 FastAPI readiness와 분리했다. Worker가 모델 로드 중이거나 실패해도 API/UI/원문 전사는 즉시 준비된다.

## 실제 실행 검증

### 시작 및 사전 로드

`start_all.bat` 한 번으로 메인 서버와 Worker가 실행됐다.

- 메인 서버 PID: `33248`
- 최초 Local Worker PID: `28624`
- Worker 상태: `ready`, `available=true`
- 실제 설정: CPU/int8, inter 1, intra 2, beam 1, concurrency 1, `below_normal`
- `.run\server.pid`와 `.run\translation-worker.pid`가 각각 실제 PID를 기록했다.
- 포트 8765는 메인 서버만 사용했고 Worker 리스닝 포트는 없었다.

수명주기 안전 보강 후 최종 재실행도 `start_all.bat` 한 번으로 성공했다.

- 최종 메인 서버 PID: `35088`
- 최종 최초 Worker PID: `27800`
- 모델 준비 중에도 `/api/diagnostics`의 서버 status는 계속 `ok`
- 강제 종료 후 새 실제 PID `28484`가 모델 ready 전에 PID 파일에 기록되고, 같은 PID로 `ready` 전환
- 후속 격리 복구 후 UI에 표시된 최종 Worker PID: `32780`
- 실행 중 `start_all.bat`을 다시 호출했을 때 health와 포트 owner를 확인하고 같은 서버/Worker PID를 재사용했으며 중복 프로세스를 만들지 않음

### UI 및 브라우저 새로고침

- UI에서 `로컬 모델`을 선택하고 설정 적용에 성공했다.
- UI 번역 테스트는 실제 Local Worker 응답으로 성공했다.
- 브라우저 새로고침 후에도 `로컬 모델` 선택이 유지됐다.
- 새로고침 후 Provider 가용성은 `사용 가능`, 번역 상태와 Local Worker는 `준비됨`으로 표시됐고 복구된 실제 PID `32780`이 표시됐다.
- WebSocket 연결과 기존 화면이 정상 유지됐으며 오류 overlay는 없었다.
- 정식 통합용 asset cache key로 갱신한 뒤 UI 번역 테스트가 `테스트 성공 · 로컬 모델 · 758ms`로 통과했다.

### 실제 시스템 음성 번역

Windows 시스템 loopback과 SAPI 음성을 사용해 제품 API/캡처 경로를 검증했다. 검증 세션 `2026-07-12_15-35-31_d8f158`에는 다음 결과가 실제 Local Worker 번역으로 저장됐다.

- 일본어 시스템 음성 원문 `システムテスト` → 한국어 `시스템 테스트`
- 영어 시스템 음성 원문 `Please confirm the BMS interface requirements by Friday.` → 한국어 `금요일까지 BMS 인터페이스 요구 사항을 확인하시기 바랍니다.`
- 복구 후 영어 원문 `The data center operation test starts at 3 p.m.` → 한국어 `data center operation test는 오후 3시에 시작됩니다.`

추가 일본어 시스템 음성 세션 `2026-07-12_15-32-26_d059e9`에서도 일본어 확정 원문 7개와 Local Worker 한국어 번역 7개가 생성됐다.

### Worker 장애 격리와 자동 복구

실행 중 Worker PID `28624`만 명령행 marker와 프로젝트 경로를 확인한 뒤 강제 종료했다.

- 즉시 캡처 상태: `listening`
- Worker 상태 변화: `ready(28624)` → `restarting` → `ready(21332)`
- 장애 중 원문 전사: `The original transcript must continue while the local translation worker restarts.` 정상 확정
- 복구 후 번역: 새 PID에서 정상 완료
- dropped frames: 0

후속 부하 중 요청 타임아웃이 발생한 경우에도 Supervisor가 다시 복구해 UI/diagnostics에서 `ready`와 새 PID `13256`을 표시했다. 원문 캡처와 서버는 계속 동작했다.

### 기존 Provider 회귀

실행 중 실제 API로 `local → none → openai(키 없음) → local`을 확인했다.

- `none` 전환 성공
- OpenAI 키 미설정 상태의 `openai` 전환은 기존처럼 HTTP 409로 안전하게 거부
- 실패 후 기존 `none` Provider 유지
- `local` 재전환 성공
- 전환 전후 Worker PID `13256` 유지: Provider close가 공유 Worker를 종료하지 않음

### 종료

`stop_all.bat` 실제 실행 결과:

- 종료 코드 0
- 최종 서버 PID `35088` 종료
- 최종 Worker PID `32780` 종료
- 두 가상환경 launcher 프로세스도 잔존하지 않음
- 포트 8765 listener 없음
- `.run\server.pid` 없음
- `.run\translation-worker.pid` 없음
- 프로젝트 marker가 있는 서버/Worker 프로세스 없음
- 무관한 Python 프로세스 일괄 종료 없음

## 자동 검증

- 전체 테스트: `194 passed, 3 skipped`
- `backend`, `scripts` compileall: 통과
- 메인 `.venv` `pip check`: 통과
- `.venv-translation` `pip check`: 통과
- 메인 `.venv`: `torch`, `transformers`, `sentencepiece` 모두 미설치
- 번역 런타임: CTranslate2 4.8.1, Transformers 4.57.6, SentencePiece 0.2.1, psutil 7.0.0

## 기존 JSONL 무결성

통합 전 보호 대상으로 기록한 기존 JSONL 6개의 최종 SHA-256은 모두 동일했다.

| JSONL | SHA-256 |
|---|---|
| `4322cb3e-66e7-4e36-ad1a-aa85da3feba6.jsonl` | `49d9eddfadf85da8382b7d7a71a66f5a66bb000d5ec694245c4244c87820b07c` |
| `4df58b13-8694-4af2-ab9d-8a6303d1021b.jsonl` | `8fd1c69c54f6c333eb40d362e76b276c3283b95e8ab879de97156faaa6b9ca76` |
| `8dc44dd7-392a-431b-b09a-6ac62769564b.jsonl` | `b0b3921a70376d20f19d3e510f6d87584d08bfbe8eda6934720859e93e4bc7aa` |
| `c538b76d-efb6-45b7-a4c7-1d7b6845dbe4.jsonl` | `6263a917a4b6b9fd6ee6a54101a22da9da7e525be0a8cece1ea9798734a4b2d2` |
| `dc7d7d81-ec27-4163-a5ca-61cc0c579b09.jsonl` | `33d6213a5b0121371de8863f0924fe879af349932ef9b5e831c65929d7ecda36` |
| `f83124b0-550c-4345-972b-0ff8bb35bba8.jsonl` | `e0f2628f2f2480ab0a067b1669613de94a9e507c31b27947e0c9bcf4368f3ed6` |

실제 검증 때문에 새 테스트 세션과 JSONL이 추가됐지만, 위 기존 세션/JSONL은 수정하거나 삭제하지 않았다.
