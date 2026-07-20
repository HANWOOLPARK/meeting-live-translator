# Phase 1 구현 계획

## 1. 범위

PROJECT_SPEC.md의 Phase 1만 구현한다. 한국어 번역, OpenAI API, 로컬 번역 모델,
회의 요약, Action Item/결정/질문 추출, 동시 시스템·마이크 전사, 화자 분리,
녹음 저장, React/Vite, 배포 기능은 구현하지 않는다.

## 2. 오디오 캡처 방식

- 기본 백엔드: PyAudioWPatch의 WASAPI loopback 및 일반 입력 스트림.
- 외부 모듈은 PyAudioWPatch를 직접 사용하지 않고 AudioCaptureBase,
  AudioDeviceProvider, AudioDeviceInfo, AudioFrame 경계를 통해 접근한다.
- 시스템 소스는 출력 장치에 대응하는 loopback 입력을 사용한다.
- 마이크 소스는 일반 입력 장치를 사용한다.
- 캡처 callback은 PCM 복사와 bounded queue 삽입만 수행하고 전사와 WebSocket
  전송은 별도 worker에서 수행한다.

선택 이유는 Windows WASAPI loopback 지원이 Phase 1에서 명시되었고, 출력 장치와
loopback 장치의 대응 관계를 PyAudioWPatch가 제공하기 때문이다.

## 3. 기존 WhisperLive와의 관계

- 기존 저장소와 가상환경은 읽기 전용으로 조사했고 수정하지 않는다.
- MIT 라이선스를 확인했으나 애플리케이션 코드는 복사하지 않는다.
- faster-whisper 1.2.0, CPU/int8 동작, multilingual small 모델 캐시 존재 사실만
  호환성 참고 정보로 사용한다.
- 새 프로젝트 전용 .venv와 독립 API/UI/세션 구조를 만든다.

## 4. 구현 구성

### 재사용하는 외부 구성

- Python 3.11.9 설치.
- faster-whisper 공개 API.
- 사용자의 기존 Hugging Face 모델 캐시는 faster-whisper의 기본 캐시 정책에 따라
  읽힐 수 있으나 프로젝트로 복사하지 않는다.

### 새로 구현하는 구성

- Windows 출력·loopback·마이크 장치 조회와 보수적 장치 매칭.
- PyAudioWPatch 캡처 어댑터와 입력 레벨 계산.
- PCM 정규화, pre-buffer, energy VAD, silence grace, 발화 buffer.
- latest-only 임시 전사와 우선순위가 높은 확정 전사 worker.
- CUDA 실제 모델 초기화 후 CPU/int8 fallback.
- 발화별 ja/en/mixed/unknown 판정과 보수적 중복 제거.
- 캡처 상태 제어, WebSocket 이벤트 방송, 확정 자막 세션 저장.
- FastAPI REST/WS API와 순수 HTML/CSS/JavaScript 다크 UI.
- setup/start/stop Windows 배치 파일.

## 5. 기본 처리 파라미터

- 처리 형식: mono 16 kHz float32.
- 캡처 frame: 약 20~30 ms.
- pre-buffer: 400 ms.
- 발화 최소 길이: 250 ms.
- silence grace: 800 ms.
- 임시 전사 시작: 약 1.2초.
- 임시 전사 간격: 약 1.5초.
- 임시 전사 최대 창: 12초.
- 최대 발화: 20초 후 안전하게 분리.
- 언어 신뢰도 0.60 미만 또는 ja/en 외 언어: unknown.

완전한 스트리밍이라고 표현하지 않으며 짧은 발화 buffer를 반복 처리하는
near-real-time 방식으로 구현한다.

## 6. 예상 구조

    meeting-live-translator/
      backend/
        app/
          main.py
          api/
          audio/
          capture/
          transcription/
          websocket/
          config/
          sessions/
        requirements.txt
      frontend/static/
      data/sessions/
      docs/
      scripts/
      tests/
      PROJECT_SPEC.md
      .env.example
      .gitignore
      README_KO.md
      AGENTS.md
      setup.bat
      start_all.bat
      stop_all.bat

## 7. API와 상태 정책

- 필수 REST: health, audio/devices, audio/refresh, settings,
  capture/start, pause, resume, stop.
- 보조 REST: capture/state 및 settings 변경.
- WebSocket: /ws/live.
- 지속 상태는 idle/listening/paused/stopped/error이고, 전사 작업 중 표시 상태는
  transcribing으로 계산한다.
- stop은 반복 호출해도 안전하게 처리한다.
- 활성 캡처 중 장치나 모델 변경은 기존 캡처를 안전하게 중지한 뒤 새 start 요청으로
  적용한다.
- 잘못된 장치, 캡처, 모델 오류는 해당 세션을 recoverable error로 만들며 FastAPI
  프로세스는 계속 동작한다.

## 8. 테스트 방법

### 자동 테스트

- 가짜 장치 provider와 capture를 주입해 장치 분류, loopback 매칭, 상태 전이를 검사.
- silence/sine PCM으로 입력 레벨과 VAD/buffer를 검사.
- scripted transcriber로 ja/en/unknown, partial/final, dedup을 검사.
- 가짜 CUDA 모델 factory 실패로 CPU/int8 fallback을 검사.
- FastAPI TestClient로 REST 및 WebSocket 이벤트를 검사.
- API 키가 없어도 서버가 시작하고 민감정보를 오류에 포함하지 않는지 검사.
- 잘못된 장치 요청 후 health가 계속 정상인지 검사.

### 실제 환경 및 수동 테스트

- PyAudioWPatch 설치 후 Windows 출력/loopback/마이크 목록을 조회.
- 기본 출력과 loopback 매칭, Bluetooth/Zoom 장치 안내를 확인.
- 실제 캡처 시작·일시정지·재개·중지와 입력 레벨을 확인.
- 비민감 일본어·영어 WAV 및 로컬 small 모델로 실제 전사와 지연을 측정.
- 하드웨어나 샘플이 없으면 PASS로 추정하지 않고 SKIP 또는 수동 미확인으로 기록.

## 9. 현재 위험 요소

- 사전 환경에는 PyAudioWPatch가 없어 설치 후 실제 loopback 검증이 필요.
- NVIDIA GPU/CUDA가 없어 GPU 성공 경로는 자동 fake 테스트만 가능.
- ffmpeg가 PATH에 없어 관련 수동 테스트는 제한될 수 있음.
- Bluetooth endpoint가 비활성일 때 loopback 장치가 노출되지 않을 수 있음.
- 출력과 loopback 이름 매칭은 드라이버마다 달라 완전한 자동 매칭을 보장할 수 없음.
- Energy VAD는 음악을 음성으로 오인할 수 있음.
- 최초 small 모델 로드 시간은 정상 전사 지연과 별도로 측정해야 함.
- 실제 일본어·영어 테스트용 비민감 WAV가 없으면 해당 테스트는 SKIP.
- mixed 언어는 문자군과 모델 언어 결과를 조합한 보수적 휴리스틱이므로 완전한
  코드 스위칭 감지는 보장하지 않음.

