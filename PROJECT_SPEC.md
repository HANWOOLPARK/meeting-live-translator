# meeting-live-translator Phase 1 구현 요청

`PROJECT_SPEC.md`는 전체 프로젝트 요구사항입니다.

이번 작업에서는 Phase 1만 구현하세요.
Phase 2 이후의 번역, 회의 요약, Action Item 추출, OpenAI API 연동은 구현하지 마세요.

## 1. 작업 원칙

현재 작업 환경은 Windows 11, Python 3.11입니다.

기존에 WhisperLive가 설치되어 있고 마이크 음성 인식 테스트까지 완료된 상태입니다.

다음 원칙을 반드시 지켜주세요.

1. 현재 폴더와 기존 파일을 먼저 검사하세요.
2. 기존 파일을 삭제하거나 무단으로 덮어쓰지 마세요.
3. 기존 WhisperLive 프로젝트를 직접 수정하지 마세요.
4. 기존 프로젝트와 독립된 `meeting-live-translator` 폴더를 만드세요.
5. 전역 Python 환경에 패키지를 설치하지 말고 프로젝트 전용 `.venv`를 사용하세요.
6. 관리자 권한이 필요한 작업이나 Windows 시스템 설정 변경은 자동으로 실행하지 마세요.
7. 기존 WhisperLive 코드를 복사하기 전에는 라이선스와 재사용 가능 여부를 확인하세요.
8. 실행하거나 확인하지 않은 내용을 완료했다고 보고하지 마세요.
9. 판단할 수 없는 사항은 추측하지 말고 `미확인` 또는 `SKIP`으로 기록하세요.
10. Phase 1이 완료되면 작업을 멈추고 결과를 보고하세요.

## 2. 코드 작성 전 환경 검사

코드를 작성하기 전에 다음 항목을 검사하고 결과를 `docs/environment_report.md`에 저장하세요.

* 현재 작업 경로
* 현재 폴더의 파일과 하위 폴더
* 사용 가능한 Python 실행 파일
* Python 버전
* pip 버전
* 현재 설치된 Python 패키지
* 기존 가상환경 존재 여부
* 기존 WhisperLive 설치 경로와 구조
* WhisperLive에서 사용 중인 faster-whisper 관련 구성
* PyTorch, CTranslate2, faster-whisper 설치 여부와 버전
* NVIDIA GPU 존재 여부
* `nvidia-smi` 실행 가능 여부
* CUDA 사용 가능 여부
* ffmpeg 설치 여부
* Node.js와 npm 설치 여부
* 사용 가능한 오디오 관련 패키지
* 사용 가능한 Windows 오디오 출력 및 입력 장치

다음과 비슷한 명령을 사용할 수 있지만, 환경에 맞게 조정하세요.

```bat
cd
dir
where python
where py
py -0p
python --version
python -m pip --version
python -m pip list
where ffmpeg
where node
where npm
nvidia-smi
```

특정 명령이 실패하더라도 전체 검사를 중단하지 말고 실패 원인을 보고서에 기록하세요.

환경 검사 후 다음 내용을 `docs/phase1_plan.md`에 작성하세요.

* 선택한 오디오 캡처 방식
* 선택 이유
* 기존 WhisperLive와의 관계
* 재사용할 수 있는 구성
* 새로 구현할 구성
* 예상 프로젝트 구조
* Phase 1 테스트 방법
* 현재 확인된 위험 요소

환경 보고서와 계획서를 작성한 뒤 구현을 시작하세요.

## 3. Phase 1 범위

Phase 1에서는 다음 기능만 구현하세요.

### 필수 기능

* Windows 오디오 출력 장치 목록 조회
* WASAPI Loopback 장치 목록 조회
* 기본 시스템 출력 장치의 오디오 캡처
* 마이크 입력 장치 목록 조회
* 시스템 음성 또는 마이크 중 하나를 선택
* 입력 장치 새로고침
* 오디오 입력 레벨 표시
* 캡처 시작
* 일시정지
* 재개
* 중지
* 입력 장치 변경
* faster-whisper 기반 일본어 및 영어 전사
* 발화 단위 언어 자동 감지
* 임시 자막 표시
* 확정 자막 표시
* 중복 문장 제거
* 시간 표시
* WebSocket을 통한 브라우저 실시간 전달
* 기본 다크 모드 UI
* 오류가 발생해도 서버 전체가 종료되지 않는 예외 처리

### 이번 Phase에서 구현하지 않을 기능

* 한국어 번역
* OpenAI API
* 로컬 번역 모델
* 회의 요약
* Action Item 추출
* 결정사항 추출
* 질문사항 추출
* 시스템 음성과 마이크의 동시 전사
* 화자 분리
* 오디오 녹음 파일 저장
* React 또는 Vite 전환
* 유튜브 및 넷플릭스 전용 기능
* 배포 기능

미구현 기능은 UI에서 비활성 상태로 표시하거나 구현하지 않아도 됩니다.

## 4. 오디오 캡처 기술

Phase 1 기본 오디오 캡처 라이브러리는 `PyAudioWPatch`를 사용하세요.

다만 다른 모듈에서 PyAudioWPatch를 직접 호출하지 않도록 오디오 캡처 인터페이스를 분리하세요.

예시:

```text
AudioCaptureBase
PyAudioWPatchCapture
AudioDeviceInfo
AudioFrame
```

추후 다른 오디오 라이브러리 또는 Windows 네이티브 캡처 방식으로 교체할 수 있어야 합니다.

WASAPI Loopback 장치는 일반 입력 장치와 구분해서 표시하세요.

장치 정보에는 가능한 범위에서 다음 값을 포함하세요.

* device_id
* name
* host_api
* is_loopback
* is_default
* max_input_channels
* max_output_channels
* default_sample_rate

Zoom에서 선택한 출력 장치와 앱에서 선택한 Loopback 장치가 다를 경우 음성이 들어오지 않을 수 있다는 안내를 UI에 표시하세요.

헤드폰 또는 Bluetooth 헤드폰이 Windows 출력 장치로 선택되어 있다면 해당 출력 장치에 대응하는 Loopback 장치를 선택할 수 있게 하세요.

## 5. 전사 구조

`faster-whisper`를 사용하세요.

기본 모델은 `small`로 하되 다음 모델을 선택할 수 있도록 구조를 준비하세요.

* tiny
* base
* small
* medium

Phase 1에서는 모델을 실행 중 즉시 변경하지 않아도 됩니다. 모델 변경 시 캡처를 안전하게 중지하고 모델을 다시 로드하도록 구현할 수 있습니다.

### 장치 및 compute type 선택

다음 순서로 동작하세요.

1. NVIDIA GPU와 CUDA 사용 가능 여부를 실제 모델 초기화로 확인
2. CUDA 초기화가 성공하면 GPU 모드 사용
3. CUDA 초기화가 실패하면 오류를 기록하고 CPU로 자동 전환
4. CPU에서는 `int8` 사용
5. GPU compute type은 환경과 호환되는 안전한 값을 선택
6. GPU 실패로 인해 전체 앱이 종료되지 않게 처리

단순히 `nvidia-smi`가 실행된다는 이유만으로 CUDA 사용 가능하다고 확정하지 마세요.

### 실시간 처리 방식

완전한 스트리밍을 보장한다고 표현하지 말고, 짧은 오디오 버퍼를 반복 전사하는 near-real-time 방식으로 구현하세요.

목표 표시 지연은 약 2~4초로 하되 실제 측정값을 보고하세요.

다음 개념을 분리하세요.

* 오디오 수집 버퍼
* VAD 또는 음성 구간 감지
* 현재 발화 버퍼
* 임시 전사 결과
* 확정 전사 결과
* 중복 제거 기록

짧은 발화가 잘리지 않도록 발화 시작 전 pre-buffer와 발화 종료 후 grace period를 사용하세요.

임시 자막은 최근 오디오 버퍼를 재전사한 결과로 표시할 수 있습니다.

일정 시간 무음이 감지되면 문장을 확정하세요.

임시 자막은 세션 기록에 저장하지 말고 확정된 문장만 저장 대상이 되도록 구조를 준비하세요.

중복 제거는 단순 완전 일치뿐 아니라 공백, 문장부호 및 부분 중복도 고려하세요. 다만 서로 다른 정상 문장을 과도하게 제거하지 않도록 보수적으로 구현하세요.

### 언어 감지

각 확정 발화마다 언어를 다시 감지하세요.

표시 가능한 언어 값:

```text
ja
en
mixed
unknown
```

일본어 문장 안에 영어 기술 용어가 포함된 경우 전체 발화가 일본어로 판정될 수 있습니다.

언어 감지 결과의 신뢰도가 낮거나 일본어와 영어 외의 언어로 감지되면 무조건 임의로 일본어 또는 영어로 바꾸지 말고 `unknown`으로 처리하세요.

## 6. 백엔드

다음을 사용하세요.

* Python 3.11
* FastAPI
* WebSocket
* faster-whisper
* PyAudioWPatch
* 프로젝트 전용 `.venv`

권장 구조:

```text
meeting-live-translator/
  backend/
    app/
      main.py
      api/
      audio/
        base.py
        devices.py
        pyaudio_wpatch_capture.py
        models.py
      transcription/
        engine.py
        buffer.py
        vad.py
        deduplicator.py
        models.py
      websocket/
        manager.py
        events.py
      config/
        settings.py
      sessions/
        models.py
    requirements.txt
  frontend/
    static/
      index.html
      app.js
      style.css
  data/
    sessions/
  docs/
    environment_report.md
    phase1_plan.md
    phase1_report.md
  scripts/
  tests/
  .env.example
  .gitignore
  README_KO.md
  AGENTS.md
  setup.bat
  start_all.bat
  stop_all.bat
```

구조는 필요하면 개선할 수 있지만 오디오, 전사, WebSocket, 설정을 한 파일에 모두 넣지 마세요.

### API 예시

필요에 따라 변경할 수 있지만 최소한 다음 기능을 제공하세요.

```text
GET  /api/health
GET  /api/audio/devices
POST /api/audio/refresh
GET  /api/settings
POST /api/capture/start
POST /api/capture/pause
POST /api/capture/resume
POST /api/capture/stop
WS   /ws/live
```

WebSocket 메시지에는 가능한 범위에서 다음 필드를 사용하세요.

```json
{
  "type": "partial_transcript",
  "source": "system",
  "text": "現在確認しています",
  "language": "ja",
  "language_probability": 0.91,
  "timestamp": "2026-07-10T20:30:15+09:00",
  "status": "transcribing"
}
```

확정 문장은 별도의 이벤트로 보내세요.

```json
{
  "type": "final_transcript",
  "segment_id": "unique-id",
  "source": "system",
  "text": "現在確認しています",
  "language": "ja",
  "language_probability": 0.91,
  "started_at": "2026-07-10T20:30:11+09:00",
  "ended_at": "2026-07-10T20:30:15+09:00"
}
```

상태 이벤트:

```text
idle
listening
paused
transcribing
error
stopped
```

오류 메시지에는 API 키, 환경변수 전체, 사용자 파일 내용 등 민감정보를 포함하지 마세요.

## 7. 프론트엔드

Phase 1은 Node.js를 필수로 요구하지 않는 단순 HTML, CSS, JavaScript로 구현하세요.

FastAPI에서 정적 파일을 제공하고 localhost에서 한 번에 실행되게 하세요.

화면에는 최소한 다음 내용을 표시하세요.

* 앱 제목
* 오디오 소스 선택
* 출력 또는 입력 장치 선택
* Whisper 모델 표시
* 시작
* 일시정지
* 재개
* 중지
* 장치 새로고침
* 입력 볼륨
* 현재 상태
* WebSocket 연결 상태
* 임시 자막
* 확정 원문 자막
* 감지 언어
* 문장 시간
* 오류 안내
* 자동 스크롤
* 글자 크기 조절
* 다크 모드

한국어 번역 영역은 Phase 2 예정이라고 표시할 수 있지만 가짜 번역 결과를 생성하지 마세요.

## 8. 실행 파일

### setup.bat

다음을 수행하세요.

* 프로젝트 경로 확인
* Python 3.11 확인
* `.venv` 생성
* 가상환경 활성화
* pip 업데이트
* 패키지 설치
* 핵심 패키지 import 테스트
* ffmpeg 존재 여부 확인
* NVIDIA 및 CUDA 관련 정보 확인
* 오디오 장치 조회 테스트
* 오류 발생 시 원인을 읽을 수 있게 출력

전역 Python 환경을 수정하지 마세요.

### start_all.bat

다음을 수행하세요.

* `.venv` 존재 확인
* 가상환경 활성화
* FastAPI 서버 시작
* 서버 준비 상태 확인
* 기본 브라우저 열기
* PID를 프로젝트 내부 파일에 저장

### stop_all.bat

다음을 지키세요.

* 이 프로젝트가 저장한 PID만 종료
* 모든 `python.exe` 또는 `node.exe`를 일괄 종료하지 않음
* PID가 이미 종료된 경우 오류 없이 정리
* PID 파일 정리

## 9. 테스트

자동 테스트와 수동 테스트를 구분하세요.

최소 테스트:

1. 오디오 장치 목록 조회
2. Loopback 장치 식별
3. 기본 출력 장치와 Loopback 장치 매칭
4. 오디오 캡처 클래스 시작 및 종료
5. 오디오 레벨 계산
6. 일본어 샘플 WAV 전사
7. 영어 샘플 WAV 전사
8. 발화별 언어 감지
9. 중복 문장 제거
10. WebSocket 연결
11. partial 이벤트 수신
12. final 이벤트 수신
13. API 키가 없는 환경에서 서버 실행
14. CUDA 초기화 실패 시 CPU fallback
15. 잘못된 장치 선택 시 서버가 종료되지 않는지 확인

하드웨어가 필요한 테스트는 자동 테스트와 별도로 `tests/manual_test_checklist.md`에 작성하세요.

테스트 결과는 다음 상태 중 하나로 보고하세요.

```text
PASS
FAIL
SKIP
MANUAL PASS
MANUAL FAIL
```

실행하지 않은 테스트를 PASS라고 기록하지 마세요.

각 테스트에 다음 내용을 남기세요.

* 실행 명령
* 결과
* 오류 메시지 요약
* 실패 또는 SKIP 사유

테스트용 오디오는 민감한 실제 회의 녹음을 사용하지 마세요.

## 10. Phase 1 완료 보고

작업 완료 후 `docs/phase1_report.md`에 다음 구조로 보고하세요.

1. 환경 검사 결과
2. 선택한 기술과 선택 이유
3. 생성한 파일 목록
4. 수정한 파일 목록
5. 구현한 기능
6. 실행한 테스트
7. 테스트 결과
8. 실제 측정한 전사 지연
9. CPU 및 GPU 동작 여부
10. 확인된 버그
11. 알려진 제한사항
12. 사용자가 직접 확인해야 할 항목
13. Phase 2에서 진행할 내용

마지막으로 콘솔에도 같은 내용을 간단히 요약하세요.

Phase 2 기능을 임의로 구현하지 말고 Phase 1 보고 후 작업을 멈추세요.


