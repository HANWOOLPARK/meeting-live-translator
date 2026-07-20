# Phase 1 환경 검사 보고서

- 검사 일시: 2026-07-10 (Asia/Seoul)
- 검사 방식: 읽기 전용 명령 실행. 전역 패키지 설치 및 Windows 설정 변경 없음.
- 판정 기준: 실제로 확인하지 못한 항목은 미확인 또는 SKIP으로 표시.

## 1. 작업 경로와 초기 파일

- 최초 작업 경로: `%USERPROFILE%\Documents\Codex\2026-07-10\project-spec-md-phase-1`
- 최초 하위 항목: outputs\, work\
- 최초 상태에는 PROJECT_SPEC.md와 기존 소스가 없었음.
- 사용자가 첨부한 UTF-8 요구사항 원문을 기준 문서로 확인했으며, 독립 프로젝트
  meeting-live-translator\PROJECT_SPEC.md로 보존함.
- 기존 Git 저장소가 아니며 기존 변경사항도 없었음.

## 2. Python과 pip

| 항목 | 결과 |
| --- | --- |
| PATH의 python | `%USERPROFILE%\AppData\Local\Python\bin\python.exe` |
| PATH Python 버전 | 3.14.6 |
| PATH pip | 26.1.2 |
| PATH Python 설치 패키지 | pip 26.1.2만 확인 |
| py 런처 | C:\Windows\py.exe |
| py -0p | 등록된 Python을 찾지 못함 |
| 요구 버전 Python | `%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe` |
| 요구 버전 | Python 3.11.9 |
| Python 3.11 pip | 24.0 |
| 최초 작업 폴더의 가상환경 | 없음 |

PATH의 기본 python은 요구 버전이 아니므로 setup.bat에서 3.11 실행 파일을
명시적으로 탐색하고, 프로젝트 전용 .venv를 생성해야 한다.

## 3. 기존 WhisperLive

- 경로: `%USERPROFILE%\Documents\translator\WhisperLive`
- 원격 저장소: https://github.com/collabora/WhisperLive.git
- 브랜치/커밋: main, d9459ebf2d7f5f5f0d7cb5fd01bc80827928932c
- 검사 당시 작업 트리: clean
- 구조: whisper_live\, requirements\, tests\, docker\, run_server.py,
  run_client.py, setup.py, LICENSE, whisper_env\
- 라이선스: MIT, Copyright (c) 2023 Vineet Suryan, Collabora Ltd.
- 재사용 판정: 라이선스상 고지 유지 조건으로 재사용 가능하지만, 이번 프로젝트는
  코드를 복사하지 않고 faster-whisper 공개 API를 직접 사용하는 독립 구현으로 진행.
- 기존 WhisperLive 및 whisper_env는 수정하거나 복사하지 않음.

### 기존 WhisperLive 전사 구성

| 패키지/항목 | 확인 결과 |
| --- | --- |
| whisper_live | 0.9.0 |
| Python | 3.11.9 |
| faster-whisper | 1.2.0 |
| CTranslate2 | 4.8.1 |
| NumPy | 1.26.4 |
| PyTorch | 2.13.0+cpu |
| torchaudio | 2.11.0 |
| PyAudio | 0.2.14 |
| PyAudioWPatch | 미설치 |
| soundfile | 0.14.0 |
| 모델 기본 개념 | multilingual small 사용 가능, CPU에서는 int8 |

기존 체크아웃의 백엔드는 torch.cuda.is_available() 결과만으로 장치를 고른 뒤
모델을 생성하며 CUDA 모델 초기화 실패 후 CPU 재시도는 하지 않는다. Phase 1
요구사항과 달라 그대로 재사용하지 않는다. 기존 사용자 캐시에
Systran/faster-whisper-small 모델 스냅샷이 있으나 저장소에 복사하지 않는다.

## 4. GPU와 CUDA

- Win32_VideoController: Intel(R) Graphics, 상태 OK.
- NVIDIA GPU: 확인되지 않음.
- nvidia-smi: PATH 및 표준 설치 경로에서 찾지 못함.
- 기존 WhisperLive venv의 torch: 2.13.0+cpu.
- torch.cuda.is_available(): False.
- torch.version.cuda: None.
- CUDA 장치 수: 0.
- 현재 판정: CUDA 사용 불가, CPU/int8 경로가 필요.

런타임 구현은 이 사전 판정만 신뢰하지 않고 실제 faster-whisper CUDA 모델
초기화를 시도한 뒤 실패하면 CPU/int8로 자동 전환한다.

## 5. 외부 도구

| 도구 | 결과 |
| --- | --- |
| ffmpeg | PATH에서 찾지 못함 |
| Node.js | PATH에서 찾지 못함 |
| npm | PATH에서 찾지 못함 |
| nvidia-smi | 찾지 못함 |

faster-whisper는 PyAV를 통해 일반적인 오디오 파일을 처리하므로 서버의 실시간 PCM
경로에 외부 ffmpeg가 필수는 아니다. Phase 1 프론트엔드는 순수 HTML/CSS/JavaScript라
Node.js와 npm도 필수가 아니다. setup.bat에서는 ffmpeg 부재를 경고로 표시한다.

## 6. 오디오 관련 패키지와 장치

검사 시점의 기존 WhisperLive 환경에는 PyAudio 0.2.14가 있으나
PyAudioWPatch, sounddevice, webrtcvad는 없었다. 일반 PyAudio로 35개 PortAudio
장치 항목을 조회했으며, WASAPI(hostApi 2) 예시는 다음과 같다.

| 인덱스 | 이름 | 입력 채널 | 출력 채널 | 기본 샘플레이트 |
| ---: | --- | ---: | ---: | ---: |
| 14 | Speaker (Realtek Speaker) | 0 | 2 | 48000 |
| 15 | CABLE In 16ch (VB-Audio Virtual Cable) | 0 | 2 | 48000 |
| 16 | CABLE Input (VB-Audio Virtual Cable) | 0 | 2 | 48000 |
| 17 | CABLE Output (VB-Audio Virtual Cable) | 2 | 0 | 48000 |
| 18 | 마이크 배열 (Intel Smart Sound Technology) | 2 | 0 | 48000 |

Windows AudioEndpoint에서 확인한 장치는 다음과 같다.

- 출력 또는 재생 endpoint: Speaker (Realtek Speaker), CABLE In 16ch,
  CABLE Input, AirPods Pro 헤드폰/Hands-Free, UHD TV.
- 입력 또는 녹음 endpoint: 마이크 배열, CABLE Output, AirPods Pro 헤드셋.
- 오디오 드라이버: Intel Smart Sound, Virtual Stereo Mix Device,
  VB-Audio Virtual Cable.

AirPods 및 UHD TV 일부 endpoint는 검사 시 Status=Unknown이었고, Realtek,
VB-Audio, 내장 마이크 endpoint는 Status=OK였다.

PyAudioWPatch가 사전 설치되어 있지 않아 실제 loopback 장치 생성 및 기본 출력과의
매칭은 이 단계에서는 SKIP이다. 프로젝트 .venv 설치 후 전용 장치 조회 스크립트와
수동 테스트로 다시 확인한다.

## 7. 실행한 주요 명령과 실패 기록

| 명령/검사 | 결과 | 오류 또는 비고 |
| --- | --- | --- |
| where.exe python / py | PASS | 경로 확인 |
| py -0p | FAIL | 등록된 Python 없음 |
| python --version | PASS | PATH Python은 3.14.6 |
| Python311\python.exe --version | PASS | 3.11.9 |
| python -m pip list | PASS | PATH 환경은 pip만 설치 |
| WhisperLive venv import 검사 | PASS | 관련 버전과 CPU-only torch 확인 |
| where.exe ffmpeg/node/npm | FAIL | PATH에서 찾지 못함 |
| nvidia-smi | FAIL | 명령 및 표준 경로 없음 |
| torch CUDA probe | PASS | 실행 성공, CUDA는 False |
| Get-PnpDevice AudioEndpoint | PASS | 장치 목록 확인 |
| 일반 PyAudio 장치 조회 | PASS | 35개 항목 확인 |
| PyAudioWPatch loopback 조회 | SKIP | 사전 설치되지 않음 |

초기 제한된 실행 컨텍스트에서는 Python 3.11 설치 폴더와 PnP 조회가 접근 거부되었으나,
읽기 전용 재검사에서 성공했다. PyAudio JSON 출력은 Windows 기본 cp949가 일본어
장치명을 인코딩하지 못해 한 번 실패했고 PYTHONIOENCODING=utf-8로 재실행했다.

## 8. 프로젝트 설치 후 재검증

선행 보고서와 계획서를 작성한 뒤 프로젝트 전용 `.venv`를 Python 3.11.9로
생성하고 `setup.bat`을 실제 실행했다.

- PyAudioWPatch 0.2.12.8 설치 및 import: PASS.
- faster-whisper 1.2.0, CTranslate2 4.8.1, NumPy 1.26.4 설치: PASS.
- faster-whisper 1.2.0의 누락된 직접 import 의존성인 requests를
  `backend/requirements.txt`에 명시해 실제 import를 재검증함.
- `setup.bat`: Python 탐색, .venv, 패키지, 핵심 import, CUDA 정보,
  오디오 장치 조회까지 exit code 0.
- 실제 장치 조회: 출력 11개, Loopback 3개, 마이크 8개, 경고 0개.
- 기본 출력 pa:14 Speaker (Realtek Speaker) ↔ 기본 Loopback pa:19 매칭.
- 추가 매칭: pa:15↔pa:20, pa:16↔pa:21.
- 실제 pa:19 stream lifecycle: running→paused→running→stopped, 오류 없음.
- 메모리 생성 440 Hz 테스트 톤: callback 53개, non-zero 51개,
  최대 RMS 0.17266.
- 실제 CUDA 모델 생성은 CUDA driver 오류로 실패했고 small 모델은
  CPU/int8로 자동 전환됨. CTranslate2 CUDA device count는 0.

이 절의 결과는 구현 후 확인값이며, 구현 전 환경에서 PyAudioWPatch가 없었다는
앞 절의 기록을 대체하지 않는다.
