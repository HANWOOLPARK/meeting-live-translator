# Meeting Live Translator Lite 배포 안내

이 ZIP은 Windows 11용 소스 기반 Lite 배포본입니다. 가상환경, 로컬 번역 모델, API 키, 기존 세션, 로그는 포함하지 않습니다.

## 받는 사람이 할 일

1. ZIP을 영문·숫자 위주의 짧은 경로에 완전히 압축 해제합니다. ZIP 내부에서 직접 실행하지 않습니다.
2. Python 3.11이 없다면 [Python 공식 사이트](https://www.python.org/downloads/)에서 현재 사용자용으로 설치합니다.
3. 프로젝트 폴더에서 `setup.bat`을 실행합니다.
4. 로컬 M2M100 번역이 필요하면 설치 질문에 `Y`를 입력합니다. 필요하지 않으면 Enter를 눌러 건너뜁니다.
5. 생성된 `.env`를 메모장으로 열고 사용할 외부 Provider의 API 키와 모델만 직접 입력합니다. 자신의 키만 사용하고 다른 사람에게 전달하지 않습니다.
6. Windows 바탕화면까지 비치는 자막·Radar 항상 위 창이 필요하면 최초 한 번
   `setup_desktop_overlay.bat`을 실행합니다. 필요하지 않으면 건너뜁니다.
7. `start_all.bat`으로 실행하고 `stop_all.bat`으로 종료합니다.

자동화된 설치 선택도 지원합니다.

```bat
setup.bat /no-local
setup.bat /local
```

`/local`은 M2M100 원본을 Hugging Face에서 한 번 다운로드해 CTranslate2 CPU int8 모델로 변환합니다. 변환 중에는 인터넷 연결과 약 6GiB의 여유 공간이 필요합니다. 완료 후에는 약 500MB의 실행 모델과 `.venv-translation`만 남고, 원본 모델·Torch 변환 환경·다운로드 캐시는 제거됩니다. 메인 `.venv`에는 Torch와 Transformers를 설치하지 않습니다.

`setup_desktop_overlay.bat`은 전역 Node.js를 요구하거나 설치하지 않습니다. 공식 Node.js
archive의 SHA-256을 확인한 뒤 portable Node.js와 고정된 Electron을 이 프로젝트의
`.runtime`과 `desktop\node_modules`에만 설치합니다. Lite ZIP에는 큰 runtime을 넣지
않으므로 받는 사람이 이 선택 설치를 실행할 때만 인터넷 연결이 필요합니다. 설치를
건너뛰면 `start_all.bat`이 일반 브라우저를 열며 자막·Radar 브라우저 분리 창은 계속
사용할 수 있습니다.

## API 키와 개인정보

- 배포자가 사용하던 `.env`는 ZIP에 없습니다.
- 받는 사람은 Deepgram, Gemini, OpenAI를 사용할 경우 각자 발급받은 키를 `.env`에 넣어야 합니다.
- 로컬 Whisper 전사와 로컬 M2M100 번역은 음성을 외부 STT·번역 API로 보내지 않습니다.
- Deepgram STT나 Gemini/OpenAI 번역·분석을 선택하면 해당 기능에 필요한 음성 또는 텍스트가 외부 서비스로 전송될 수 있습니다.
- 새 세션은 받는 사람 PC의 `data\sessions`에만 생성됩니다.

## 문제 해결

- `Python 3.11` 오류: 다른 Python 버전이 아니라 Python 3.11을 현재 사용자용으로 설치한 뒤 다시 실행합니다.
- 로컬 번역 설치 재시도: `setup_local_translation.bat`
- 로컬 번역 무다운로드 점검: `setup_local_translation.bat /check`
- 로컬 번역 없이 실행: 설정에서 `사용 안 함`, Gemini 또는 OpenAI를 선택합니다. Worker가 없어도 원문 전사는 계속 동작합니다.
- 포트 충돌: 먼저 `stop_all.bat`을 실행합니다. 이 스크립트는 프로젝트가 기록한 PID만 검증해 종료하며 모든 Python 프로세스를 종료하지 않습니다.
- 네이티브 투명 창 설치 실패: 일반 UI는 손상되지 않습니다. `set MLT_DESKTOP=0` 후
  `start_all.bat`을 실행해 브라우저로 사용하고, 네트워크 연결 뒤
  `setup_desktop_overlay.bat`을 다시 시도합니다.
- 투명 창 오류: `.run\desktop.stderr.log`를 확인합니다. `stop_all.bat`은 프로젝트가
  기록하고 명령행까지 검증한 Electron PID 트리만 종료하며 다른 Electron 앱을 종료하지
  않습니다.

설치 스크립트가 모델 원본을 받는 위치와 변환 도구의 근거는 `THIRD_PARTY_NOTICES.md`를 참고하세요.
