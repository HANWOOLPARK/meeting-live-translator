# Meeting Live Translator Phase 1 완료 보고서

- 완료 일시: 2026-07-10 (Asia/Seoul)
- 앱 버전: 0.1.0-phase1
- 기준 문서: 프로젝트 루트 PROJECT_SPEC.md
- 구현 범위: Phase 1만 구현. 번역, OpenAI API, 요약, Action Item 등 Phase 2 기능은 미구현.

## 1. 환경 검사 결과

- Windows 11, NT 10.0.26200.0.
- PATH의 python은 3.14.6이지만 프로젝트는
  `%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe`
  (3.11.9)로 전용 .venv를 생성함.
- 기존 WhisperLive:
  `%USERPROFILE%\Documents\translator\WhisperLive`.
- 기존 WhisperLive는 Collabora 공식 Git 원격, MIT 라이선스, clean main,
  commit d9459ebf2d7f5f5f0d7cb5fd01bc80827928932c.
- 기존 코드는 복사·수정하지 않았고 기존 whisper_env도 재사용하지 않음.
- 기존 환경의 faster-whisper 1.2.0, CTranslate2 4.8.1,
  torch 2.13.0+cpu 구성만 호환성 참고 정보로 사용.
- NVIDIA GPU와 nvidia-smi 없음. Intel(R) Graphics만 확인.
- ffmpeg, Node.js, npm은 PATH에서 찾지 못했으나 Phase 1 실시간 PCM 및
  순수 HTML/CSS/JavaScript 실행에는 필수가 아님.
- 실제 프로젝트 setup.bat 실행: PASS.

상세한 구현 전/후 환경 기록은 docs/environment_report.md에 있다.

## 2. 선택한 기술과 이유

- PyAudioWPatch 0.2.12.8: Windows WASAPI Loopback과 일반 입력을 같은
  PortAudio 계층에서 제공하며 요구사항에 지정됨.
- AudioCaptureBase 경계: 다른 캡처 백엔드로 교체할 수 있도록 장치 모델,
  캡처 lifecycle, PCM 처리를 PyAudioWPatch 호출에서 분리함.
- FastAPI 0.139.0 + WebSocket: REST 상태 제어와 브라우저 실시간 이벤트를
  같은 localhost 서버에서 제공.
- faster-whisper 1.2.0 + CTranslate2 4.8.1: 기존 확인 환경과 호환되는
  다국어 small 모델. CUDA 실제 모델 생성을 먼저 확인하고 CPU/int8로 fallback.
- Energy VAD + 400 ms pre-buffer + 800 ms grace: 추가 네이티브 VAD 의존성 없이
  짧은 발화 시작과 종료를 보존하는 교체 가능한 Phase 1 구현.
- 순수 HTML/CSS/JavaScript: Node.js 없이 정적 UI를 FastAPI에서 직접 제공.
- JSONL 세션 저장: 임시 자막은 저장하지 않고 확정 자막만 append.

## 3. 생성한 파일

작업 전 폴더에는 outputs와 work만 있었고 기존 프로젝트 파일은 없었다.
다음 구성을 독립된 meeting-live-translator 아래에 생성했다.

- 기준/운영: PROJECT_SPEC.md, README_KO.md, AGENTS.md, .env.example,
  .gitignore, pytest.ini.
- 실행: setup.bat, start_all.bat, stop_all.bat,
  scripts/check_audio_devices.py.
- 백엔드 진입/API: backend/app/main.py, services.py, errors.py,
  api/schemas.py, config/settings.py.
- 오디오: backend/app/audio/base.py, models.py, devices.py,
  processing.py, pyaudio_wpatch_capture.py.
- 캡처 제어: backend/app/capture/controller.py.
- 전사: backend/app/transcription/engine.py, buffer.py, vad.py,
  deduplicator.py, language.py, models.py.
- WebSocket/세션: backend/app/websocket/manager.py, events.py,
  backend/app/sessions/models.py, repository.py.
- 프론트엔드: frontend/static/index.html, app.js, style.css.
- 문서: docs/environment_report.md, phase1_plan.md, phase1_report.md.
- 테스트: tests/fakes.py, 9개 test_*.py,
  tests/manual_test_checklist.md.
- 데이터 디렉터리: data/sessions/.gitkeep.
- 의존성: backend/requirements.txt.

각 Python 패키지의 __init__.py도 함께 생성했다.

## 4. 수정한 기존 파일

- 기존 사용자 프로젝트 파일 수정 없음.
- 기존 WhisperLive 파일 수정 없음.
- 구현 과정에서 새로 생성한 소스와 문서는 실제 검증 결과에 맞게 반복 보완함.

## 5. 구현한 기능

- Windows 오디오 출력, WASAPI Loopback, 마이크 목록과 기본 장치 조회.
- 출력↔Loopback 보수적 이름/host API 매칭 및 UI 안내.
- 시스템 음성 또는 마이크 한 소스 선택.
- 장치 새로고침, 입력 레벨, start/pause/resume/stop.
- 캡처 중 장치/모델 변경 시 기존 캡처의 안전한 stop 후 재시작 경로.
- PCM16 downmix, 16 kHz resample, bounded frame queue와 overflow 보호.
- pre-buffer, energy VAD, silence grace, 최대 발화 분리.
- latest-only partial과 우선 처리 final 전사.
- stop/pause 전에 이미 캡처된 queue backlog를 처리한 뒤 final flush.
- tiny/base/small/medium 구조, 기본 small.
- 실제 CUDA 모델 생성 실패 시 서버를 유지하고 CPU/int8 자동 fallback.
- 발화마다 언어 재감지 및 ja/en/mixed/unknown 보수적 표시.
- NFKC·공백·문장부호·고유사도·부분 중복을 고려한 보수적 dedup.
- partial/final/state/audio_level/error WebSocket 이벤트.
- 클라이언트별 bounded WebSocket queue와 느린 연결 격리.
- 확정 자막만 data/sessions/<session-id>.jsonl에 저장.
- localhost 다크 UI, 자동 재연결, 자동 스크롤, 글자 크기, 반응형 레이아웃.
- Phase 2 한국어 번역 비활성 안내. 가짜 번역이나 외부 API 호출 없음.
- 민감한 예외 문자열을 API/장치 warning에 노출하지 않는 오류 처리.
- 실제 Uvicorn 자식 PID 추적, 캡처 stop API 호출 후 해당 PID만 종료.

## 6. 실행한 테스트

주요 명령:

    setup.bat
    .venv\Scripts\python.exe -m pytest -q
    .venv\Scripts\python.exe scripts\check_audio_devices.py --strict
    start_all.bat
    stop_all.bat

추가 실측:

- 실제 pa:19 loopback stream start/pause/resume/stop.
- 메모리 생성 440 Hz 톤 재생과 callback RMS 측정.
- Windows SAPI Haruka·Zira 합성 WAV의 실제 small 모델 전사.
- 합성 일본어·영어를 실제 기본 출력으로 재생하고 loopback→VAD→전사→
  WebSocket→브라우저→JSONL 전체 흐름 확인.
- 인앱 브라우저 DOM, 콘솔, WebSocket, desktop/mobile 레이아웃,
  start/pause/resume/stop 조작 확인.
- start_all/stop_all의 실제 server PID, health, PID 파일 정리 확인.

## 7. 테스트 결과

자동 테스트 최종 결과: 53 passed in 0.70s.

| 번호 | 요구 테스트 | 결과 | 근거 |
| ---: | --- | --- | --- |
| 1 | 오디오 장치 목록 | PASS | 실제 출력 11, Loopback 3, 마이크 8 |
| 2 | Loopback 식별 | PASS | 실제 pa:19/20/21 |
| 3 | 기본 출력↔Loopback 매칭 | PASS | pa:14↔pa:19 및 2개 추가 매칭 |
| 4 | 캡처 start/stop | PASS | 실제 running/paused/running/stopped |
| 5 | 오디오 레벨 | PASS | 53 frame, 최대 RMS 0.17266 |
| 6 | 일본어 WAV 전사 | PASS | 정확한 일본어 문장, ja 0.9880 |
| 7 | 영어 WAV 전사 | PASS | 정확한 영어 문장, en 0.9973 |
| 8 | 발화별 언어 감지 | PASS | 실제 ja/en 및 자동 mixed/unknown |
| 9 | 중복 제거 | PASS | 자동 공백/문장부호/부분/정상 반복 |
| 10 | WebSocket 연결 | PASS | TestClient와 실제 브라우저 연결 |
| 11 | partial 이벤트 | PASS | 자동 및 실제 일본어/영어 partial |
| 12 | final 이벤트 | PASS | 자동 및 실제 브라우저/JSONL |
| 13 | API 키 없이 실행 | PASS | health 200, 브라우저 실행 |
| 14 | CUDA 실패→CPU fallback | PASS | 실제 CUDA 생성 실패 후 CPU/int8 |
| 15 | 잘못된 장치 오류 격리 | PASS | 404/400 후 health 200 |

수동 체크리스트 집계:

- MANUAL PASS 7
- MANUAL FAIL 0
- SKIP 6

상세 명령, 오류, SKIP 사유는 tests/manual_test_checklist.md에 기록했다.

## 8. 실제 측정한 전사 지연

모델 cold load:

- small 모델 CUDA 시도→CPU/int8 준비: 2.238초.

파일 단위 실제 추론:

- 일본어 6.047초 WAV: 2.639초.
- 영어 6.159초 WAV: 2.573초.

실제 loopback 발화 종료→final 이벤트 5회:

- 2.863초
- 2.820초
- 3.153초
- 2.875초
- 2.940초

모두 목표 2~4초 범위였다. 최초 partial은 재생 시작 후 3.770초에 관찰했지만
발화 종료 기준 partial 5회는 동일 조건으로 측정하지 않아 수동 M-12 전체 판정은
SKIP으로 남겼다.

## 9. CPU 및 GPU 동작

- CUDA actual construction: FAIL.
- 원인: CUDA driver version is insufficient for CUDA runtime version.
- NVIDIA GPU/nvidia-smi: 없음.
- CPU fallback: PASS.
- 실제 runtime: device=cpu, compute_type=int8, cuda_fallback=true.
- CUDA 성공 경로: 이 환경에 호환 GPU가 없어 실제 성공 여부는 SKIP.

## 10. 확인된 버그

현재 알려진 Phase 1 blocker: 없음.

구현 중 발견하고 수정한 항목:

- faster-whisper 1.2.0 실제 import에 필요한 requests 명시 누락.
- venv launcher PID와 실제 Uvicorn child PID 불일치.
- stop 시 이미 queue에 있던 final job을 기다리지 않는 종료 경쟁.
- pause/stop 직전 callback backlog를 비워 마지막 발화를 잃는 문제.
- pause/resume/stop 요청 취소 시 backend와 controller 상태가 갈라지는 문제.
- 모델 load 요청 취소 후 transcribing 상태가 남는 문제.
- 긴 pause 시간이 자막 wall-clock 시각에 반영되지 않는 문제.
- final queue 생성 시점에 in-flight partial을 너무 일찍 폐기하던 문제.
- 드라이버 raw exception이 API warning으로 노출될 수 있던 문제.
- dedup 기록이 JSONL 저장보다 먼저 반영되던 순서 문제.

각 동시성/회귀 문제에 자동 테스트를 추가했다.

## 11. 알려진 제한사항

- 시스템과 마이크 중 한 소스만 전사하며 동시 전사는 Phase 2 이후 범위.
- Energy VAD는 음악/효과음을 음성으로 오인할 수 있음.
- 장치 ID는 PortAudio index이므로 재부팅·장치 변경 후 새로고침 필요.
- Bluetooth/비활성 endpoint는 대응 Loopback이 노출되지 않을 수 있음.
- 소리 재생이 끝난 뒤 loopback이 충분한 무음 callback을 주지 않으면 마지막
  문장은 pause/stop flush 때 확정될 수 있음.
- 첫 모델 캐시가 없으면 다운로드 시간이 추가됨.
- final 추론은 stop과 shutdown에서 제한 시간 동안 기다리지만 극단적으로 느린
  추론이나 프로세스 강제 종료에서는 마지막 저장을 보장할 수 없음.
- 실제 마이크, Zoom 통화, Bluetooth 전환, 실제 mixed 발화, 장시간 회의는 SKIP.
- 모바일 390×844 DOM 측정은 가로 overflow 없이 PASS했으나 full-page screenshot은
  브라우저 자동화 CDP timeout으로 2회 실패함. UI DOM/콘솔 검증은 PASS.
- ffmpeg가 PATH에 없으므로 외부 ffmpeg 명령을 쓰는 확장 기능은 미확인.

## 12. 사용자가 직접 확인해야 할 항목

1. 실제 회의에서 사용하는 마이크의 캡처·장치 변경.
2. Zoom 출력과 앱 Loopback이 같은 장치인지.
3. AirPods/Bluetooth Stereo와 Hands-Free endpoint 선택.
4. 실제 일본어·영어 대화와 mixed 기술 용어 발화.
5. 30분 이상 회의에서 CPU 사용률, 온도, 지연, 메모리.
6. 사용하려는 GPU 환경이 있다면 CUDA 성공 경로와 compute type.
7. 자동 스크롤/글자 크기와 선호 브라우저의 모바일/창 크기.

## 13. Phase 2에서 진행할 내용

이번 작업에서는 아래 기능을 구현하지 않았다.

- 한국어 번역과 번역 모델/OpenAI API 연동.
- 회의 요약.
- Action Item, 결정사항, 질문사항 추출.
- 시스템 음성과 마이크 동시 전사.
- 화자 분리.
- 배포 기능.

Phase 2에서는 확정 원문 이벤트를 입력으로 별도 번역·요약 파이프라인을 설계하고,
API 키와 민감정보 처리 정책을 별도 검토해야 한다.

## 콘솔 요약

Phase 1 구현 완료. 자동 테스트 53 PASS, 실제 장치/loopback/capture/일본어·영어
전사/WebSocket/UI/CPU fallback/start-stop PID 검증 완료. 실제 final 지연은
2.820~3.153초. 마이크·Zoom/Bluetooth·mixed·장시간 회의·GPU 성공 경로는 SKIP.
