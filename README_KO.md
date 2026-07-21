# WhyKaigi — 실시간 다국어 회의 인텔리전스

Windows 11의 **시스템 출력(WASAPI Loopback) 또는 마이크 중 하나**를 선택해 일본어·영어·한국어 원문 자막을 브라우저에 전달하고, 확정 원문을 선택적으로 번역하는 로컬 앱입니다. UI에서 일본어→한국어 또는 영어→한국어를 선택할 수 있고, Deepgram과 외부 번역 Provider를 사용할 때는 한국어→일본어 또는 한국어→영어도 선택할 수 있습니다. 짧은 오디오 구간을 반복 처리하는 **near-real-time** 방식이며 완전한 스트리밍을 보장하지 않습니다. 목표 원문 표시 지연은 2~4초입니다.

Phase 3는 Phase 2의 bounded 비동기 번역 큐를 유지하면서, 복구 가능한 세션 lifecycle, JSON/TXT/Markdown 내보내기, 과거 세션 복원, `none`·`rule_based`·`openai`·`gemini` 회의 분석을 추가합니다. 번역 Provider는 `none`, `local`, `openai`, `gemini`를 지원합니다. 원문 final은 번역을 기다리지 않고 먼저 표시되며 partial 자막은 저장·번역·분석하지 않습니다. 화자 분리, 오디오 저장, 시스템 음성과 마이크의 동시 전사는 포함되지 않습니다.

## 준비 사항

- Windows 11
- Python 3.11(다른 버전의 전역 Python은 수정하지 않음)
- 실제 시스템 음성 캡처용 Windows 출력 장치 및 대응 Loopback
- 최초 Whisper 모델 다운로드 또는 OpenAI 번역을 사용하는 경우 인터넷 연결
- 관리자 권한 불필요

전역 Node.js와 npm은 필요하지 않습니다. 기본 브라우저 UI는 Python 설치만으로 동작하며,
선택 기능인 네이티브 투명 오버레이를 설치할 때만 `setup_desktop_overlay.bat`이 검증된
portable Node.js와 Electron을 프로젝트 내부에 내려받습니다. 기본 번역 방식은 `none`이므로
OpenAI API 키가 없어도 설치·실행·원문 전사가 가능합니다. NVIDIA/CUDA 초기화가 실제로
실패하면 서버가 종료되지 않고 CPU `int8`로 전환합니다.

## 설치와 실행

명령 프롬프트에서 프로젝트 루트로 이동한 뒤 다음을 실행합니다.

```bat
setup.bat
start_all.bat
```

`setup.bat`은 `py -3.11`과 일반적인 Python 3.11 설치 경로를 순서대로 확인하고, 이 프로젝트의 `.venv`만 생성·수정합니다. 패키지 설치 후 핵심 import, CTranslate2 CUDA 정보, ffmpeg, 오디오 장치를 점검합니다. ffmpeg나 NVIDIA가 없는 것은 CPU 기반 실시간 PCM 경로의 설치 실패가 아닙니다. Lite 배포본에서는 설치 마지막에 로컬 M2M100 번역을 추가할지 선택할 수 있습니다. 건너뛰어도 원문 전사와 외부 API Provider는 사용할 수 있습니다.

창 전체의 실제 투명화와 항상 위 자막·Radar 결과 창이 필요하면 최초 한 번 다음 선택
설치를 실행합니다. 설치하지 않아도 일반 브라우저 UI와 브라우저 분리 창은 유지됩니다.

```bat
setup_desktop_overlay.bat
```

`start_all.bat`은 메인 FastAPI 서버를 시작하고, FastAPI 수명주기에서 격리된
`.venv-translation` Worker를 함께 시작해 M2M100 모델을 선행 로드합니다. 선택 설치된
Electron이 있으면 네이티브 앱을 열고, 없거나 시작에 실패하면 기본 브라우저를 엽니다.
서버·Worker·데스크톱 PID와 로그는 `.run/` 아래에 각각 분리해 저장됩니다. Worker나
데스크톱 UI가 준비되지 않아도 서버와 원문 전사는 시작됩니다. 브라우저만 강제로 열려면
현재 명령 프롬프트에서 `set MLT_DESKTOP=0`을 지정한 뒤 실행합니다.

종료할 때는 다음을 사용합니다.

```bat
stop_all.bat
```

이 스크립트는 저장된 서버·Worker·Electron PID를 각각 명령행과 프로젝트 경로로
검증합니다. 캡처와 Worker의 정상 종료를 먼저 요청한 뒤 검증된 PID 트리만 종료하며,
다른 `python.exe`, `electron.exe`, 브라우저를 일괄 종료하지 않습니다.

### Lite 배포본 만들기

다른 사람에게 전달할 때는 프로젝트 폴더 전체를 직접 압축하지 말고 다음 명령을 실행합니다.

```bat
make_lite_release.bat
```

`dist\whykaigi-lite-YYYYMMDD.zip` 하나가 생성됩니다. 이 ZIP은 `.env`, API 키, 세션, 로그, PID, 가상환경, 모델, 테스트·PoC 자료를 제외하고 실행에 필요한 소스와 설치 스크립트만 포함합니다. 압축 내부의 SHA-256 manifest와 금지 경로·비밀 패턴 검사를 통과하지 못하면 ZIP 생성이 실패합니다. 받는 사람에게는 **이 ZIP 하나만** 전달하면 되며 설치 순서는 함께 포함된 `DISTRIBUTION_KO.md`에 설명되어 있습니다.

## 사용 순서

1. **장치 새로고침**을 누릅니다.
2. 시스템 음성이면 **시스템 음성**과 출력 장치에 대응하는 **WASAPI Loopback**을 선택합니다. 직접 말할 때는 **마이크**를 선택합니다.
3. Whisper 모델을 선택합니다. 기본값은 `small`입니다.
4. **시작** 후 입력 볼륨과 WebSocket 상태를 확인합니다.
5. 필요하면 **일시정지 → 재개**, 종료 시 **중지**를 누릅니다.
6. 장치나 모델은 캡처를 중지한 뒤 변경합니다.
7. 한국어 번역이 필요하면 **번역 방식**에서 Provider를 선택하고 **설정 적용**을 누릅니다. 가용하지 않은 Provider는 선택할 수 없습니다.
8. 번역 실패 카드는 원문을 유지하며, Provider가 사용 가능하면 **재번역**을 누를 수 있습니다.
9. 중지 후 현재 세션에서 전체 원문·번역 복사 또는 JSON/TXT/Markdown 다운로드를 사용할 수 있습니다.
10. 과거 세션을 선택하면 서버에 저장된 final 원문, 번역, 분석 결과를 다시 불러옵니다.
11. 회의 분석은 공급자를 고른 뒤 사용자가 **회의 분석 생성**을 명시적으로 눌러 실행합니다. 자동 분석 기본값은 OFF입니다.

페이지 길이를 줄이기 위해 **회의 용어와 사람 이름**, **현재 세션과 기록**,
**회의 분석**은 첫 화면에서 접혀 있습니다. 각 제목줄을 클릭하거나 키보드로
포커스한 뒤 Enter 또는 Space를 누르면 펼치고 다시 접을 수 있으며, 현재 프로필·세션·
분석 상태 배지는 접힌 상태에서도 확인할 수 있습니다. 새로고침하면 기본 접힘 상태로
돌아갑니다.

### UI 언어

상단의 **한국어 / English** 전환 버튼으로 메인 화면 전체를 한국어 또는 영어로
표시할 수 있습니다. 기본값은 한국어이며 선택은 같은 브라우저에 저장되어
새로고침 후에도 유지됩니다. 메인 화면, 자막 분리 창, Decision Radar 결과 창은 선택을
공유하므로 어느 창에서 바꾸어도 다른 창도 같은 언어로 다시 표시됩니다.

전환 대상은 버튼, 설정, Provider 상태, 진단, 오류, 확인 대화상자처럼 앱이 만든 UI
문구입니다. 실제 원문 자막, 번역 결과, 사용자 용어·사람 이름, 모델이 생성한 회의
분석 본문은 뜻이 달라지지 않도록 UI 전환으로 재번역하지 않습니다. 언어를 바꾸면
현재 페이지가 한 번 새로고침되어 모든 동적 상태 문구까지 일관되게 적용되며,
캡처 중지 API를 호출하지 않습니다.

### Worksite Context Engine

**회의 용어와 사람 이름**에서 회의/현장별 프로필을 만들고 다음 항목을 등록할 수
있습니다.

- 일반 용어: 제품명, 회사명, 프로젝트 코드, 기술 약어
- 사람 이름: 참석자 이름과 올바른 표기
- 자주 틀리는 표기·별칭: STT가 실제로 출력하는 오인식 또는 다른 표기

원문 final은 그대로 보존하고, 등록한 별칭과 일치하는 부분만 정확한 표기로 바꾼
`normalized_text`를 별도 저장합니다. 화면에서는 원문 아래에 **Context 적용** 결과를
표시합니다. 번역에는 현재 문장과 제한된 최근 문맥에서 실제 발견된 용어만 최대
10개 전달하고, 관련 용어가 없으면 glossary 지시문 자체를 생략합니다. Radar도 현재
분석 묶음에서 실제 매칭된 정규 표기와 별칭만 전달합니다. Deepgram
Nova-3를 사용할 때는 현재 프로필의 정확한 표기와 별칭을 최대 100개의 `keyterm`
으로 연결 시점에 전달합니다. 캡처 중 프로필을 바꾸면 정규화는 즉시 적용되지만
Deepgram keyterm은 다음 캡처 시작부터 적용됩니다.

완료된 세션을 선택하고 **선택 세션에서 추천**을 누르면 사람 호칭, 영문 약어,
제품명 형태, 가타카나 고유어 후보를 찾아 승인 보관함에 표시합니다. 추천은 자동으로
프로필에 들어가지 않으며 사용자가 각 항목을 **추가**하거나 **무시**해야 합니다.
일반 단어와 일본어 이름을 완벽하게 판별하는 기능은 아니므로 후보를 확인한 뒤
승인하세요.

프로필은 `data/context_engine.json`에 저장됩니다. 사람 이름과 현장 용어가 포함될 수
있으므로 이 파일은 Git과 Lite 배포에서 제외됩니다. 새 설치에서는 기본 프로필을
자동 생성합니다. 등록 항목과 추천 후보는 항목이 많아져도 페이지 전체가 계속
늘어나지 않도록 각각 고정 높이 목록 안에서 마우스·터치·키보드로 스크롤합니다.

임시 자막은 현재 발화를 보여주며 세션 기록에 저장되지 않습니다. 새 세션은 `data/sessions/<session-id>/` 아래에 manifest, append-only events JSONL, 완성된 JSON/TXT/Markdown을 저장합니다. Phase 1·2의 루트 `<uuid>.jsonl`은 원본을 수정하지 않고 읽기·파생 내보내기만 수행합니다. 오디오 녹음 파일은 저장하지 않습니다. 자동 스크롤과 자막 글자 크기는 브라우저에서 조절할 수 있습니다.

### 자막 분리 창·미디어 자막과 표시 모드

자막 영역 오른쪽의 **자막 창** 버튼을 누르면 `/captions` 자막 전용 창이 열립니다. 이
창은 메인 화면과 별도로 WebSocket에 연결되므로 메인 창을 닫아도 서버가 실행 중이면
새 자막을 계속 받을 수 있습니다. 창을 늦게 열거나 새로고침한 경우 활성 세션의 저장된
확정 자막을 다시 불러온 뒤 실시간 이벤트와 합칩니다.

메인 자막 영역과 분리 창 모두 **원문 + 번역**, **원문만**, **번역만** 표시를 지원합니다. 번역만 모드에서는 번역되지 않는 임시 원문을 숨기며, 번역 대기·실패·사용 안 함 상태는 해당 문장 위치에 안전한 상태 문구로 표시합니다. 선택한 표시 모드와 글자 크기는 같은 브라우저의 두 창 사이에서 공유됩니다.

같은 영역의 **미디어 자막** 버튼은 Netflix·YouTube 자막처럼 모니터 아래쪽에 놓는 별도
한 줄 창을 엽니다. 일반 **자막 창**은 전체 기록을 스크롤해서 보는 용도이고, 미디어
자막은 가장 최근 문장 하나만 표시합니다. 기본 **자동 · 번역 우선** 모드에서는 final
원문을 즉시 보여 주고 같은 `segment_id`의 번역이 도착하면 그 자리를 번역으로 바꿉니다.
발화 중 partial도 final을 기다리지 않고 임시 한 줄로 표시합니다.

미디어 자막의 설정 막대는 평소 숨겨져 있고 창 위에 마우스를 올리거나 키보드 포커스가
들어오면 나타납니다. 화면 너비의 **60%·80%·94%**, 22~48px 기본 글자 크기,
**자동·원문만·번역만·원문 + 번역**, 한/영 UI와 0~85% 배경 투명도를 선택할 수
있습니다. 긴 문장은 한 줄을 유지하도록 18px까지 자동 축소하고, 그래도 넘을 때만
말줄임표로 처리합니다. 선택값은 새로고침 후에도 유지됩니다.

분리 창의 **배경 투명도**는 자막 패널 배경만 0~85% 범위에서 조절하고 글자는
불투명하게 유지합니다. 선택 설치된 네이티브 앱에서는 프레임 없는 Windows 투명 창과
항상 위 고정을 사용하므로 회의 앱·영상 위에 실제로 겹쳐 볼 수 있습니다. Electron의
Windows 투명 창 제약 때문에 마우스로 자유 크기 조절하지는 않습니다. 일반 자막·Radar
창은 고정 크기로 이동만 지원하고, 미디어 자막은 현재 모니터 작업 영역의 하단 중앙에
배치한 뒤 안전한 60%·80%·94% 너비 프리셋으로 프로그램이 창 크기를 바꿉니다.
일반 브라우저로 실행한 경우에는 페이지 배경만 조절되며 브라우저 제목 표시줄과 Windows
창 자체는 투명해지거나 항상 위로 고정되지 않습니다.

### Decision Radar 결과 분리 창

Decision Radar 제목 오른쪽의 **결과 창** 버튼은 Provider 설정이 아니라 실제 결과만
별도 창으로 엽니다. Provider 선택·모델·적용은 메인 화면에 남고, 분리 창에는 읽기 전용
Provider 상태, 현재 세션, queue 상태와 다음 네 결과 그룹이 표시됩니다.

- 결정 사항
- 해야 할 일·담당자·기한
- 미해결 질문
- 확인이 필요한 사람 이름·용어·번역

결과 창에서도 항목 승인·수정·삭제와 근거 이동을 사용할 수 있습니다. 근거를 누르면
메인 창을 앞으로 가져오고 연결된 원문 `segment_id`로 이동합니다. 자막 창과 동일하게
독립 WebSocket 재연결, 한/영 UI 공유, 0~85% 배경 투명도를 지원하며 네이티브 앱에서는
프레임 없는 항상 위 투명 창으로 동작합니다.

## Zoom·헤드폰·Bluetooth 주의사항

Zoom의 스피커 출력과 앱에서 선택한 Loopback이 서로 다르면 입력 볼륨이 0으로 보일 수 있습니다. 예를 들어 Zoom이 AirPods로 출력 중이면 AirPods 출력에 대응하는 Loopback을 선택해야 합니다. Windows 기본 출력을 바꾼 뒤에는 **장치 새로고침**을 누르세요.

Bluetooth 장치는 재생용 Stereo와 통화용 Hands-Free가 별도 endpoint로 나타날 수 있습니다. 현재 실제로 소리가 나는 출력 이름과 동일한 Loopback을 선택합니다. 드라이버가 비활성 endpoint의 Loopback을 노출하지 않으면 해당 장치는 앱에서 선택할 수 없습니다.

오디오 장치만 다시 점검하려면:

```bat
.venv\Scripts\python.exe scripts\check_audio_devices.py
.venv\Scripts\python.exe scripts\check_audio_devices.py --json
```

이 명령은 장치 목록을 읽기만 하며 Windows 설정이나 기본 장치를 변경하지 않습니다.

## 설정

`.env.example`을 `.env`로 복사하면 서버가 프로젝트 루트의 `.env`를 자동으로 읽습니다. 이미 설정된 프로세스 환경변수는 `.env`보다 우선합니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `MLT_HOST` | `127.0.0.1` | 로컬 바인드 주소 |
| `MLT_PORT` | `8765` | 서버 포트 |
| `MLT_WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium` |
| `MLT_SAMPLE_RATE` | `16000` | 내부 전사 샘플레이트 |
| `MLT_PREFER_CUDA` | `true` | CUDA 실제 초기화를 먼저 시도할지 여부 |
| `MLT_FRAME_QUEUE_SIZE` | `256` | 캡처 프레임 큐 상한 |
| `DEEPGRAM_RECONNECT_MAX_ATTEMPTS` | `5` | Deepgram 연결 단절 후 자동 재연결 최대 횟수 |
| `DEEPGRAM_RECONNECT_BASE_DELAY_SECONDS` | `0.5` | 즉시 재연결 실패 후 다음 시도까지의 기본 대기 시간(초) |
| `DEEPGRAM_RECONNECT_MAX_DELAY_SECONDS` | `5` | 지수 백오프 재연결 대기 상한(초) |
| `DEEPGRAM_RECONNECT_BUFFER_SECONDS` | `3` | 재연결 중 보관할 최근 PCM 오디오 길이(초) |
| `DEEPGRAM_STT_ENDPOINTING_MS` | `500` | 일본어 endpointing. 영어·한국어 전용값을 생략했을 때 사용하는 기존 전역 fallback |
| `DEEPGRAM_STT_UTTERANCE_END_MS` | `1300` | 일본어 `UtteranceEnd` 대기값. 영어·한국어 전용값을 생략했을 때 사용하는 기존 전역 fallback |
| `DEEPGRAM_STT_MAX_SEGMENT_SECONDS` | `8` | 일본어에서 자연스러운 절 경계를 허용하기 시작하는 soft 목표 길이. 강제 final 상한이 아님 |
| `DEEPGRAM_STT_EN_ENDPOINTING_MS` | `400` | 영어 endpointing. 명시하면 기존 전역값보다 우선 |
| `DEEPGRAM_STT_EN_UTTERANCE_END_MS` | `1000` | 영어 `UtteranceEnd` 대기값. 명시하면 기존 전역값보다 우선 |
| `DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS` | `6` | 영어의 자연스러운 절 경계 soft 목표 길이 |
| `DEEPGRAM_STT_KO_ENDPOINTING_MS` | `650` | 한국어 endpointing. 89초 실제 TTS 회의에서 문장 내부 휴지를 오인 분절하지 않도록 실측 조정한 값 |
| `DEEPGRAM_STT_KO_UTTERANCE_END_MS` | `1500` | 한국어 `UtteranceEnd` 대기값. 명시하면 기존 전역값보다 우선 |
| `DEEPGRAM_STT_KO_MAX_SEGMENT_SECONDS` | `8` | 한국어의 자연스러운 절 경계 soft 목표 길이 |
| `DEEPGRAM_STT_CHECKPOINT_SECONDS` | `4` | 긴 발화를 안정된 partial로 갱신하는 간격. 번역·저장·Radar에는 전달하지 않음 |
| `DEEPGRAM_STT_HARD_LIMIT_SECONDS` | 기본 프로필에서 `10` | 자연 경계를 찾지 못한 연속 발화를 번역용 final로 마감하는 강제 상한. 생략하면 `max(10, 적용된 모든 MAX_SEGMENT)` |
| `DEEPGRAM_STT_JA_INCOMPLETE_FINAL_WAIT_SECONDS` | `0.9` | 일본어의 미완성 `speech_final`·`UtteranceEnd`를 다음 안정 조각과 결합하기 위한 짧은 grace |
| `DEEPGRAM_STT_EN_INCOMPLETE_FINAL_WAIT_SECONDS` | `0.7` | 영어 미완성 발화의 결합 grace |
| `DEEPGRAM_STT_KO_INCOMPLETE_FINAL_WAIT_SECONDS` | `1.5` | 한국어 미완성 발화의 결합 grace. 이어지는 interim이 있으면 10초 hard limit 안에서 갱신됨 |
| `DEEPGRAM_STT_INCOMPLETE_FINAL_WAIT_SECONDS` | 비어 있음 | 전용값이 없는 언어에 적용하는 기존 호환용 전역 fallback |
| `DEEPGRAM_RECHECK_ENABLED` | `true` | 위험도가 높은 Deepgram final만 로컬 Whisper로 선택 재검증 |
| `DEEPGRAM_RECHECK_MODEL` | 비어 있음 | 비어 있으면 `MLT_WHISPER_MODEL` 재사용. `tiny`, `base`, `small`, `medium` 허용 |
| `DEEPGRAM_RECHECK_BUFFER_SECONDS` | `14` | 재검증용 mono PCM 메모리 링 크기. 디스크·JSONL에는 오디오를 저장하지 않음 |
| `DEEPGRAM_RECHECK_TIMEOUT_SECONDS` | `4` | 재검증 대기 상한. 초과하면 Deepgram 원문으로 계속 진행 |
| `DEEPGRAM_RECHECK_QUEUE_MAX_SIZE` | `2` | 동시에 대기시킬 선택 재검증 수. 초과 final은 재검증을 건너뛰고 보존 |
| `DEEPGRAM_RECHECK_LOCAL_FILES_ONLY` | `true` | Whisper 모델 자동 다운로드 금지. 기존 로컬 캐시가 없으면 안전하게 fallback |
| `TRANSLATION_DIRECTION` | `ja_to_ko` | `ja_to_ko`, `ja_to_en`, `en_to_ko`, `en_to_ja`, `ko_to_ja`, `ko_to_en`. 한국어 원문 방향은 Deepgram 전용이며, 목표 언어가 한국어가 아닌 방향은 Gemini/OpenAI 번역 전용 |
| `TRANSLATION_PROVIDER` | `none` | `none`, `local`, `openai`, `gemini` |
| `OPENAI_API_KEY` | 비어 있음 | OpenAI API 키. 공개 API·브라우저·로그로 반환하지 않음 |
| `OPENAI_TRANSLATION_MODEL` | `gpt-5.4-mini` | Responses API 번역 모델 |
| `GEMINI_API_KEY` | 비어 있음 | Gemini API 키. 공개 API·브라우저·로그로 반환하지 않음 |
| `GEMINI_TRANSLATION_MODEL` | 비어 있음 | 사용할 Gemini 번역 모델. 명시하지 않으면 Gemini 사용 불가 |
| `GEMINI_TRANSLATION_TIMEOUT_SECONDS` | `20` | Gemini 요청 제한 시간(초) |
| `GEMINI_TRANSLATION_MAX_RETRIES` | `2` | Gemini 요청의 최초 시도 이후 최대 재시도 횟수 |
| `GEMINI_TRANSLATION_CONTEXT_SEGMENTS` | `3` | Gemini 번역에 참고할 직전 final 최대 개수 |
| `TRANSLATION_CONTEXT_SEGMENTS` | `3` | 현재 문장 번역에 참고할 직전 final 최대 개수 |
| `TRANSLATION_QUEUE_MAX_SIZE` | `100` | 번역 대기열 상한 |
| `TRANSLATION_MAX_CONCURRENCY` | `2` | 번역 큐 worker 수. 로컬 sidecar 내부 동시성은 별도로 `1` 고정 |
| `TRANSLATION_TIMEOUT_SECONDS` | `20` | 번역 한 번의 제한 시간 |
| `TRANSLATION_MAX_RETRIES` | `2` | 최초 시도 이후 최대 재시도 횟수 |
| `TRANSLATION_TRANSLATE_UNKNOWN` | `false` | `unknown` final도 번역할지 여부 |
| `LOCAL_TRANSLATION_RUNTIME_PYTHON` | `.venv-translation\Scripts\python.exe` | Transformers를 격리한 Worker Python |
| `LOCAL_TRANSLATION_MODEL` | `models\translation\m2m100_418m-int8` | 사전 변환·검증한 M2M100 CTranslate2 모델 경로 |
| `SESSION_SAVE_ORIGINAL` | `true` | 새 세션의 확정 원문 저장 여부 |
| `SESSION_SAVE_TRANSLATION` | `true` | 새 세션의 번역 저장 여부 |
| `SESSION_SAVE_ANALYSIS` | `true` | 새 세션의 성공 분석 저장 여부 |
| `SESSION_AUTO_RECOVER` | `true` | 서버 시작 시 미완료 Phase 3 세션 복구 여부 |
| `ANALYSIS_PROVIDER` | `none` | `none`, `rule_based`, `openai`, `gemini` |
| `OPENAI_ANALYSIS_MODEL` | 비어 있음 | OpenAI 분석 모델. 명시하지 않으면 OpenAI 분석 사용 불가 |
| `GEMINI_ANALYSIS_MODEL` | 비어 있음 | Gemini 분석 모델. 비어 있으면 `GEMINI_TRANSLATION_MODEL` 재사용 |
| `ANALYSIS_TIMEOUT_SECONDS` | `60` | 분석 chunk 한 번의 제한 시간 |
| `ANALYSIS_MAX_RETRIES` | `1` | 최초 시도 이후 최대 재시도 횟수 |
| `ANALYSIS_AUTO_RUN_ON_STOP` | `false` | 사용자가 명시적으로 켠 경우에만 종료 후 분석 |
| `ANALYSIS_MAX_SEGMENTS_PER_CHUNK` | `100` | 분석 chunk의 segment 상한 |
| `ANALYSIS_MAX_CHARS_PER_CHUNK` | `24000` | 분석 chunk의 문자 상한 |
| `ANALYSIS_MAX_CONCURRENCY` | `1` | 동시에 실행할 분석 작업 상한 |
| `MLT_SHARE_RELAY_URL` | 비어 있음 | 참석자 보기 사이트의 HTTPS 기준 URL. 미설정 시 공유 기능만 비활성화 |
| `MLT_SHARE_RELAY_SECRET` | 비어 있음 | 중계방 생성 전용 비밀값. 공개 API·진단·브라우저에 반환하지 않음 |
| `MLT_SHARE_RELAY_TIMEOUT_SECONDS` | `5` | 중계 서버 요청 제한 시간. 초과해도 로컬 원문·번역은 계속됨 |

`start_all.bat`의 브라우저·준비 확인 주소는 로컬 보안을 위해 `127.0.0.1`을 사용합니다. 포트를 바꾸면 앱과 준비 확인에 같은 `MLT_PORT`가 적용됩니다.

프로세스 환경변수가 프로젝트 `.env`보다 우선합니다. `.env`를 만들려면 프로젝트 루트에서 다음을 실행한 뒤 실제 값을 직접 편집합니다.

```bat
copy .env.example .env
```

### Deepgram 실시간 음성 인식

로컬 Whisper 대신 Deepgram Nova-3 스트리밍 STT를 선택할 수 있습니다. `일본어 → 한국어` 방향에서는 일본어(`ja`), `영어 → 한국어` 방향에서는 영어(`en`), `한국어 → 일본어`와 `한국어 → 영어` 방향에서는 한국어(`ko`)를 인식하며, 시스템 음성 또는 마이크 음성을 mono 16 kHz PCM으로 Deepgram 서버에 실시간 전송합니다. 중간 결과는 화면에만 표시하고, 확정 결과만 기존 세션 JSONL에 저장하고 선택된 번역 Provider로 전달합니다.

프로젝트 `.env`에 다음 값을 추가한 뒤 `stop_all.bat`, `start_all.bat` 순서로 서버를 다시 시작하세요.

```dotenv
STT_PROVIDER=local
TRANSLATION_DIRECTION=ja_to_ko
DEEPGRAM_API_KEY=your_deepgram_api_key_here
DEEPGRAM_STT_MODEL=nova-3
DEEPGRAM_STT_LANGUAGE=ja
DEEPGRAM_STT_ENDPOINTING_MS=500
DEEPGRAM_STT_UTTERANCE_END_MS=1300
DEEPGRAM_STT_MAX_SEGMENT_SECONDS=8
DEEPGRAM_STT_EN_ENDPOINTING_MS=400
DEEPGRAM_STT_EN_UTTERANCE_END_MS=1000
DEEPGRAM_STT_EN_MAX_SEGMENT_SECONDS=6
DEEPGRAM_STT_KO_ENDPOINTING_MS=650
DEEPGRAM_STT_KO_UTTERANCE_END_MS=1500
DEEPGRAM_STT_KO_MAX_SEGMENT_SECONDS=8
DEEPGRAM_STT_CHECKPOINT_SECONDS=4
DEEPGRAM_STT_HARD_LIMIT_SECONDS=10
DEEPGRAM_RECONNECT_MAX_ATTEMPTS=5
DEEPGRAM_RECONNECT_BASE_DELAY_SECONDS=0.5
DEEPGRAM_RECONNECT_MAX_DELAY_SECONDS=5
DEEPGRAM_RECONNECT_BUFFER_SECONDS=3
```

실행 후 입력 설정의 **음성 인식 방식**에서 **Deepgram · nova-3**를 선택합니다. `STT_PROVIDER=deepgram`이면 기본 선택도 Deepgram이 됩니다. API 키가 없으면 해당 옵션은 비활성화됩니다. 실제 Deepgram 인식 언어와 조립 프로필은 UI의 번역 방향에 따라 일본어·영어·한국어로 자동 선택됩니다. `DEEPGRAM_STT_LANGUAGE`는 이전 설정 파일 호환을 위해 남아 있지만 실행 중 번역 방향보다 우선하지 않습니다. **영어 → 한국어**는 로컬 Whisper 또는 Deepgram에서 모두 사용할 수 있고 local·Gemini·OpenAI 번역 Provider를 지원합니다. **한국어 → 일본어**와 **한국어 → 영어**는 Deepgram을 선택한 경우에만 UI에서 선택할 수 있고, 실제 번역을 위해 Gemini 또는 OpenAI Provider를 적용해야 합니다. 로컬 번역 모델은 일본어/영어→한국어 전용입니다. 키 값은 공개 API, WebSocket 이벤트 및 로그에 반환하지 않습니다.

언어별 timing 우선순위는 **영어·한국어 전용 변수 → 기존 전역 변수 → 언어별 내장 기본값**입니다. 기존 전역 `DEEPGRAM_STT_ENDPOINTING_MS`, `DEEPGRAM_STT_UTTERANCE_END_MS`, `DEEPGRAM_STT_MAX_SEGMENT_SECONDS`는 일본어 프로필이면서, 대응하는 `DEEPGRAM_STT_EN_*` 또는 `DEEPGRAM_STT_KO_*`를 생략한 기존 설정의 fallback입니다. `.env.example`처럼 전용 변수가 이미 있으면 전역값만 바꿔도 영어·한국어에는 적용되지 않으므로 해당 언어의 전용값을 함께 조정해야 합니다.

`/api/settings`의 `deepgram.language`, `endpointing_ms`, `utterance_end_ms`, `max_segment_seconds`는 하위 호환을 위해 유지되는 `DEEPGRAM_STT_LANGUAGE`와 일본어/기존 전역 설정값입니다. 현재 번역 방향에 실제로 적용된 언어와 timing은 같은 응답의 `stt_runtime`, 캡처 상태의 `stt_runtime`, 또는 `/api/diagnostics`의 `server.stt`를 확인합니다.

Deepgram WebSocket이 끊기면 최대 5회까지 지수 백오프로 자동 재연결합니다. 최초 연결 핸드셰이크가 일시적으로 실패한 경우에도 한 번 더 자동 시도합니다. 재연결 중에는 기본적으로 가장 최근 3초 분량의 오디오만 메모리에 보관하며, 상한을 넘으면 오래된 오디오부터 버립니다. 재연결에 성공하면 보관된 최근 오디오를 순서대로 전송하고, 재연결 시도가 모두 실패해도 캡처 UI와 기존 원문·세션은 유지됩니다. 화면의 실행 상태 영역과 `/api/diagnostics`에서 재연결 횟수, 버퍼 오디오, 버린 오디오, 캡처 드롭 프레임 및 번역 대기열의 가장 오래된 대기 시간을 확인할 수 있습니다. 같은 확정 문장은 짧은 재전송 구간에서만 중복으로 제거하므로, 몇 초 뒤 실제로 반복한 문장은 새 발화로 유지됩니다.

YouTube·강연처럼 무음 없이 발화가 길게 이어질 때는 `speech_final`만 기다리지 않습니다. 활성 발화의 interim과 안정된 `is_final` 조각은 계속 같은 `utterance_id`의 partial로 화면에 갱신하며, 4초 checkpoint는 번역 확정 기준으로 사용하지 않습니다. 이 partial은 JSONL·번역·Radar에는 보내지 않습니다. 일본어는 8초, 영어는 6초, 한국어는 7초부터 쉼표 등 자연스러운 절 경계를 우선 사용하며, 마침표·물음표·느낌표 또는 `speech_final`·`UtteranceEnd`가 오면 더 일찍 final로 마감합니다. 어떤 경계도 찾지 못하면 기본 10초 안전 상한에서 Deepgram `Finalize`로 안정화한 뒤 한 번만 final로 마감합니다. 따라서 날짜나 서술어가 4초 경계에서 잘리는 현상과 중복 번역 호출을 줄이면서도 긴 무정지 발화의 지연을 제한합니다.

기존 `DEEPGRAM_STT_MAX_SEGMENT_SECONDS`는 이제 4초마다 강제 번역하는 상한이 아니라 자연스러운 절 경계를 사용할 수 있는 soft 기준입니다. 실제 강제 final 상한은 `DEEPGRAM_STT_HARD_LIMIT_SECONDS`입니다. HARD_LIMIT을 생략하면 `10`초와 적용된 일본어·영어·한국어 MAX_SEGMENT 중 가장 큰 값을 사용하며 최대 허용값은 `30`초입니다. HARD_LIMIT을 직접 명시한 경우에는 모든 언어 프로필의 MAX_SEGMENT 이상이어야 하며, 더 작으면 설정 오류로 서버 시작을 중단합니다. 따라서 기존에 MAX_SEGMENT를 `10`초보다 크게 사용하던 `.env`도 새 HARD_LIMIT을 추가하지 않았다면 같은 최대값으로 자동 확장됩니다.

Deepgram의 `speech_final` 또는 `UtteranceEnd`가 조사·접속사·연결 어미나 한두 글자 조각에서 끝나면 곧바로 번역하지 않고 언어별 짧은 grace 동안 다음 안정 조각을 기다립니다. 기본값은 일본어 0.9초, 영어 0.7초, 한국어 1.5초입니다. 보류 중 새 interim이 도착하면 grace를 갱신하되 10초 hard limit은 넘지 않습니다. 한국어는 종결부호가 없는 명사구도 보류하고 `합니다`·`습니다` 같은 정상 종결형은 즉시 확정합니다. 겹쳐 도착한 안정 token은 한 번만 남기며, 다음 stable final이 온 경우 낮은 신뢰도의 한두 글자 후보는 중복 접두부로 확정하지 않습니다. `先日`·`本日`처럼 뒤 내용이 필요한 시간 표현과 `けれども`·`ですが`처럼 종결부호가 붙어도 의미가 이어지는 일본어 표현도 후보로 유지합니다. 완성 문장과 `はい`, `Yes`, `네` 같은 짧은 응답은 추가 지연 없이 final로 확정합니다. final에는 chunk confidence뿐 아니라 단어별 confidence와 경계 사유를 함께 평가해 `short_fragment`, `incomplete_ending`, `low_transcript_confidence`, `low_word_confidence`, `forced_boundary` 위험 사유를 계산합니다. hard `Finalize` 응답은 Deepgram의 `speech_final` 표시보다 우선해 `hard_limit` 사유를 보존합니다.

위험 final만 기존 `MLT_WHISPER_MODEL`을 CPU `int8`, `beam_size=1`, 동시 실행 1개로 선택 재검증합니다. 재검증 중에는 Deepgram 원문 후보를 저장되지 않는 `partial_transcript`로 즉시 표시하고, 검증이 끝난 canonical final만 저장·번역·Radar에 전달합니다. 최근 약 14초 PCM은 메모리에만 보관하고 세션·JSONL·내보내기에는 오디오를 기록하지 않습니다. 기본 `DEEPGRAM_RECHECK_LOCAL_FILES_ONLY=true`이므로 새 Whisper 모델을 자동 다운로드하지 않으며 기존 캐시가 없거나 로딩·추론·4초 timeout이 발생하면 Deepgram 원문을 그대로 확정합니다. 두 결과가 충돌하면 전체 문장을 느슨하게 교체하지 않습니다. Deepgram의 저신뢰 단어 위치와 Whisper 차이를 정렬해 짧은 삽입·교체만 국소 반영하며, 의미 삭제·절 수 감소·근거 없는 한자 교체는 거부합니다. 승인된 Context Engine 용어 또는 명확한 문장 완성 근거가 있을 때만 더 넓은 교체를 허용합니다. 번역과 Decision Radar에는 최종 선택 문장이 동일한 `segment_id`로 정확히 한 번만 전달됩니다.

새 Phase 3 세션에는 `transcription_quality` 파생 이벤트가 append-only로 추가됩니다. 기존 `FinalTranscript` 스키마와 과거 세션은 수정하지 않으며, 원문 저장을 끈 세션에는 Deepgram·Whisper 텍스트도 품질 이벤트에 기록하지 않습니다. `/api/diagnostics`의 `server.stt.selective_recheck`에서 메모리 버퍼, queue, 요청·채택·실패·timeout·skip 누계를 확인할 수 있습니다. 같은 `server.stt.latency`에는 오디오 끝→Deepgram 수신과 canonical 처리의 최근·평균·최대 지연이, `server.translation_queue.latency`에는 번역 queue·Provider·전체 지연이 각각 분리되어 다음 실측의 병목을 바로 비교할 수 있습니다.

## 번역 방식

### 번역 사용 안 함 (`none`)

기본값입니다. 확정 원문을 어떤 번역 Provider에도 보내지 않습니다. 첫 로컬 번역 지연을 줄이기 위해 설치된 sidecar 모델은 앱 시작 때 선행 로드될 수 있지만, `local`을 선택하기 전에는 번역 요청을 처리하지 않습니다. 원문 전사, WebSocket, final 저장은 그대로 작동합니다.

### OpenAI API 번역 (`openai`)

공식 Python SDK의 비동기 클라이언트와 Responses API를 사용합니다. 확정된 현재 원문과 설정된 개수만큼의 직전 문맥이 외부 서버로 전송될 수 있습니다. API 키는 브라우저에서 입력하거나 조회할 수 없으며, 환경변수 또는 프로젝트 `.env`에만 둡니다.

```dotenv
TRANSLATION_PROVIDER=openai
OPENAI_API_KEY=your_api_key_here
OPENAI_TRANSLATION_MODEL=gpt-5.4-mini
```

모델 값이 비어 있으면 코드 한 곳에 정의된 `gpt-5.4-mini`를 사용합니다. 회사 회의에서 사용하기 전에 외부 전송 허용 여부, 참가자 동의, 회사 보안정책을 확인하세요. API 키 누락, 인증 실패, rate limit, timeout, 네트워크 오류 또는 빈 응답은 해당 segment의 번역 오류로만 표시되며 오디오 캡처와 다음 원문 전사는 계속됩니다. 자동 재시도는 bounded queue의 설정 횟수로 제한됩니다.

### Gemini API 번역 (`gemini`)

공식 `google-genai` SDK를 사용하며, 다음 값을 실제 키와 사용할 모델로 바꿔 프로젝트 `.env`에 저장한 뒤 서버를 다시 시작합니다.
실행 후 UI의 **번역 방식**에서 **Gemini API**를 선택하고 **설정 적용**을 누릅니다.

```dotenv
TRANSLATION_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_TRANSLATION_MODEL=your_gemini_model_here
```

Gemini는 선택된 상태에서 확정 원문이 들어올 때만 요청합니다. Provider 조회와 상태 확인은 실제 생성 API를 호출하지 않습니다. 확정 원문과 제한된 직전 문맥은 Google 서버로 전송되며, 무료 사용량과 한도는 계정·프로젝트 설정에 따라 달라질 수 있습니다. 키는 UI·로그·세션 파일에 표시하지 않습니다. Gemini 요청이 실패해도 원문 전사와 다음 문장은 계속 처리됩니다.

### 로컬 번역 (`local`)

`models\translation\m2m100_418m-int8` 모델을 `.venv-translation`의 별도 프로세스에서 실행합니다. 고정 실행값은 CPU `int8`, `inter_threads=1`, `intra_threads=2`, `beam_size=1`, 번역 동시성 `1`, Windows 우선순위 `BelowNormal`입니다. 메인 `.venv`에는 Torch, Transformers, SentencePiece를 설치하지 않습니다.

로컬 번역을 설치하거나 복구하려면:

```bat
setup_local_translation.bat
```

모델이 없다면 고정한 M2M100 원본 revision을 Hugging Face에서 받아 임시 `.venv-translation-build`에서 CTranslate2 int8로 변환합니다. 성공 후 원본 다운로드 캐시, Torch가 설치된 변환 환경, 임시 파일은 제거합니다. 설치된 환경과 모델을 다운로드 없이 다시 확인하려면 `setup_local_translation.bat /check`를 사용합니다. `start_all.bat` 실행 후 UI의 **Local Worker** 행과 `GET /api/diagnostics`에서 `ready`, 실제 PID, 모델명, cold start, 재시작 횟수를 확인할 수 있습니다. Worker가 강제 종료되거나 파이프 오류가 나면 번역만 안전하게 실패하고 원문 전사는 계속되며, Worker는 bounded backoff로 자동 재시작합니다. `POST /api/translation/worker/restart`로 명시적 재시작도 가능합니다.

NLLB-200 distilled 600M은 모델 카드의 비상업·비프로덕션 제한 때문에 기본 후보로 채택하지 않았습니다. 대형 모델을 자동 설치하거나 자동 다운로드하지 마세요.

### Provider 변경과 재번역

Provider 변경은 서버를 재시작하지 않으며 기존 원문과 완료된 번역을 유지합니다. 변경 시 이전 Provider의 대기·진행 작업은 취소하는 정책을 사용하고 이후 final부터 새 Provider를 적용합니다. 같은 `segment_id`는 자동 중복 등록하지 않지만 사용자가 카드의 **재번역**을 누르면 명시적으로 새 시도를 허용합니다. 이전 성공 번역은 새 시도가 성공하기 전까지 즉시 삭제하지 않습니다.

OpenAI 또는 Gemini Provider를 적용하면 SDK client를 생성 요청 없이 백그라운드에서 미리 구성합니다. 상태 확인과 설정 적용은 그 준비 완료나 외부 생성 API를 기다리지 않으며, 실제 번역 요청 전에는 비용과 외부 전송이 발생하지 않습니다.

동일 원문으로 OpenAI, Gemini, NVIDIA Riva Translate 4B를 비교할 때는 한 줄에 한 문장인 UTF-8 파일을 준비한 뒤 아래 명령을 명시적으로 실행할 수 있습니다. `.env`에 `NVIDIA_API_KEY`를 설정하며 모델 기본값은 `nvidia/riva-translate-4b-instruct-v1.1`입니다. 이 도구는 세 Provider에 똑같은 context-free 요청을 동시에 보내며 세션에는 저장하지 않고 자동 재시도도 하지 않습니다. 세 외부 API의 비용과 데이터 전송이 발생하므로 환경변수와 확인 플래그가 모두 없으면 실행을 거부합니다. NVIDIA Riva는 이 A/B 도구에서만 사용하며 제품 UI Provider에는 등록하지 않습니다.

```powershell
$env:RUN_TRANSLATION_AB_TEST='1'
.venv\Scripts\python.exe scripts\compare_translation_providers.py .\comparison.txt --source-language ja --target-language ko --confirm-external-calls
```

특정 Provider만 비교하려면 예를 들어 `--providers openai gemini`를 추가합니다.

### 용어집

공통 기본 용어집은 `backend/app/translation/glossary.py` 한 곳에서 관리합니다. `MK119`, `DC OS`, `Fit & Gap`, `BMS`, `RMS`, `Data Center`, 설계·테스트 단계명과 회사명을 포함합니다. 사용자 용어는 `config/translation_glossary.example.json`을 `config/translation_glossary.json`으로 복사해 문자열 목록을 편집하고 `.env`에 `TRANSLATION_GLOSSARY_FILE=config/translation_glossary.json`을 지정하면 기본 목록에 병합됩니다. 사용자 파일은 Git 무시 대상이며 같은 목록을 Provider별로 복제하지 않습니다. 외부 번역 Provider에는 전체 목록이 아니라 현재 문장과 최근 문맥에서 실제 발견된 항목만 최대 10개 전달합니다.

## 세션 저장·복구·내보내기

세션 상태는 캡처 상태와 별도로 `created`, `running`, `paused`, `stopping`, `finalizing`, `completed`, `recovered`, `error`를 사용합니다. 이벤트 JSONL은 append-only 원본이고 `session.json`, `transcript_original.txt`, `transcript_korean.txt`, `meeting_report.md`는 원자적으로 교체 가능한 파생 파일입니다. 서버가 비정상 종료된 뒤 다시 시작하면 manifest와 events가 있는 미완료 세션을 복구하며, 손상된 JSONL 한 줄은 안전한 경고를 남기고 나머지 정상 행으로 복구합니다.

저장 설정은 새 세션이 시작될 때 고정됩니다. 저장을 끈 데이터는 이벤트·내보내기 파일에 원문 내용 대신 저장하지 않았다는 marker만 남깁니다. 앱은 과거 세션을 임의로 삭제하지 않습니다. `data/sessions`는 Git 무시 대상이므로 필요한 자료는 사용자가 안전한 위치에 직접 백업하거나 삭제하세요.

## 회의 분석

### 분석 사용 안 함 (`none`)

기본값입니다. 외부 요청과 추출을 하지 않으며 세션 저장·내보내기는 계속 작동합니다.

### 규칙 기반 (`rule_based`)

생성형 모델 없이 일본어·영어·한국어의 명시적인 결정, Action Item, 질문 표현만 보수적으로 추출합니다. 회의 목적은 확실하지 않으면 `미정`, 담당자·기한도 명확하지 않으면 `미정`입니다. 생성형 요약을 흉내 내거나 키워드만으로 결정을 만들어내지 않습니다.

### OpenAI (`openai`)

공식 Python SDK의 비동기 Responses API Structured Outputs를 사용합니다. `OPENAI_API_KEY`와 `OPENAI_ANALYSIS_MODEL`을 모두 설정해야 공급자를 선택할 수 있습니다. 분석 버튼을 누르기 전에는 요청하지 않으며 페이지·목록 조회만으로 외부 호출하지 않습니다. 저장된 확정 원문과 번역이 분석을 위해 외부 서버로 전송될 수 있으므로 회사 보안정책과 회의 참가자의 동의 여부를 먼저 확인하세요.

### Gemini (`gemini`)

번역과 같은 공식 `google-genai` SDK와 `GEMINI_API_KEY`를 사용합니다. 분석 모델은
`GEMINI_ANALYSIS_MODEL`로 따로 지정할 수 있고, 비어 있으면 기존
`GEMINI_TRANSLATION_MODEL`을 재사용하므로 같은 `.env` 설정으로 바로 선택할 수
있습니다.

```dotenv
ANALYSIS_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_TRANSLATION_MODEL=your_gemini_model_here
GEMINI_ANALYSIS_MODEL=
```

Gemini Structured Output은 공식 `response_json_schema`에 Pydantic JSON Schema를
전달하고 응답을 기존 분석 스키마로 다시 검증한 뒤 모든 근거 ID를 실제 final
`segment_id`와 대조합니다. Provider 조회·설정 화면을 여는 것만으로는 생성
요청을 보내지 않으며, 사용자가 **분석 생성**을 누르거나 명시적으로 자동 분석을
켠 경우에만 저장된 회의 내용을 Google 서버로 전송합니다. 실패·시간 초과·요청
한도 초과는 분석 작업에만 영향을 주고 원문 세션은 유지됩니다.

긴 회의는 segment 경계를 유지한 bounded chunk로 나눈 뒤 결과를 병합합니다. 모든 분석 항목의 evidence segment ID를 실제 final segment와 대조하며 하나라도 존재하지 않으면 결과 전체를 거부합니다. 재분석 중에는 이전 성공 결과를 유지하고 새 결과가 성공한 뒤에만 교체합니다.

## 근거 연결형 Decision Radar

Decision Radar는 회의가 진행되는 동안 **결정 사항, Action Items, 미해결 질문, 확인이 필요한 인명·용어·번역**을 계속 갱신합니다. 각 항목에는 실제 확정 자막의 `evidence_segment_ids`가 반드시 포함되며, UI에서 근거 버튼을 누르면 해당 원문 카드로 이동합니다. 사용자는 제안 항목을 승인·수정·삭제할 수 있습니다.

회의 중에는 기본 **핵심** 탭에서 결정과 Action만 함께 보고, 필요할 때 **결정**, **Action**,
**미해결** 탭으로 좁힐 수 있습니다. 미해결 탭에는 질문과 인명·용어·번역 확인 항목을 함께
표시합니다. Radar 결과 영역만 고정 높이로 스크롤되며 최신 위치에 있을 때는 새 항목으로
자동 이동합니다. 사용자가 과거 항목을 읽으려고 위로 스크롤하면 자동 이동을 멈추고
`새 항목 · 최신으로` 버튼을 표시합니다. 다른 탭의 새 항목은 점으로 알리되 탭을 강제로
전환하지 않습니다. 번역 Provider 설정은 작업 화면 상단의 접이식 상태 바로 축소되어 기본
화면에는 번역 방향, Provider, 상태만 남습니다.

데스크톱 작업 화면에서는 자막과 Radar 패널이 같은 화면 기준 높이를 사용합니다. 자막
기록과 Radar 결과는 각 패널 내부에서 독립적으로 스크롤되므로 한쪽을 읽는 동안 다른 쪽
위치와 페이지 전체 위치가 움직이지 않습니다.

- `partial` 자막은 화면 표시 전용이며 Radar나 외부 API로 보내지 않습니다.
- `final` 자막을 비용 절약 기본값인 10개 또는 최대 20초 단위로 묶어 분석합니다.
- 각 분석에는 새 묶음뿐 아니라 직전 최대 16개 `final`을 rolling context로 함께
  전달합니다. 새 항목은 이번 묶음의 `focus_segment_ids`를 하나 이상 근거로 가져야
  하므로 과거 항목을 반복 생성하지 않습니다.
- 인용·전언·시청자 요청·예시·일반 조언·의견·가정·조건·가능성·기간 예상은 회의
  참석자가 명시적으로 채택하지 않는 한 결정이나 Action으로 만들지 않습니다.
- 뒤 문맥에서 오탐·중복·해결된 질문으로 판명된 **미검토 제안**은 철회할 수 있지만,
  사용자가 승인하거나 수정한 항목은 자동 철회하지 않습니다.
- Context Engine 전체 목록을 반복 전송하지 않고 현재 rolling context에서 실제 매칭된
  사람 이름과 용어만 최대 10개 분석 문맥으로 사용합니다.
- OpenAI와 Gemini 중 하나를 UI에서 명시적으로 선택해야 외부 요청이 발생합니다.
- OpenAI 기본 모델은 반복 시험 비용을 낮춘 `gpt-5.4-mini`입니다. 최종 품질 시험은
  `.env`에서 더 큰 모델로 명시적으로 바꿀 수 있습니다.
- Gemini는 엄격한 Radar Pydantic 모델의 JSON Schema를 `response_json_schema`로 전달해
  `additionalProperties: false`를 포함한 구조화 출력을 안전하게 요청합니다.
- 모든 근거 ID를 현재 분석 묶음의 실제 `segment_id`와 대조합니다. 잘못된 참조만
  제거한 뒤에도 현재 focus의 실제 근거가 남는 항목은 보존하고, 실제 근거가 없는
  항목만 폐기합니다.
- diagnostics에는 Provider 시도 횟수, 분석한 focus 수, 누적·평균 요청 입력 문자 수를
  공개해 호출량과 반복 입력 증가를 확인할 수 있습니다.
- Provider 오류·429·timeout·대기열 초과가 발생해도 원문 전사와 번역은 계속 동작합니다.
- 사용자 검토 결과는 `data/decision_radar.json`에 별도로 원자적 저장하며 기존 세션 JSONL은 수정하지 않습니다.

`.env` 기본 설정은 다음과 같습니다. `GEMINI_DECISION_RADAR_MODEL`이 비어 있으면 `GEMINI_ANALYSIS_MODEL`, 이어서 `GEMINI_TRANSLATION_MODEL`을 재사용합니다.

```dotenv
DECISION_RADAR_PROVIDER=none
OPENAI_DECISION_RADAR_MODEL=gpt-5.4-mini
GEMINI_DECISION_RADAR_MODEL=
DECISION_RADAR_BATCH_SIZE=10
DECISION_RADAR_BATCH_WAIT_SECONDS=20
DECISION_RADAR_CONTEXT_SEGMENTS=16
DECISION_RADAR_QUEUE_MAX_SIZE=100
DECISION_RADAR_TIMEOUT_SECONDS=30
DECISION_RADAR_MAX_RETRIES=1
```

Provider 조회나 화면 새로고침만으로 모델을 호출하지 않습니다. 외부 Provider를 적용하면 확정 원문 묶음과 그 문맥에서 실제 매칭된 제한된 Context Engine 항목이 해당 API 서버로 전송될 수 있으며 사용량 기반 비용이 발생할 수 있습니다. API 키는 서버 환경에서만 읽고 UI·공개 API·진단 응답에는 값을 노출하지 않습니다.

## 참석자 초대 링크 공유

메인 화면의 **참석자 실시간 공유**에서 전송 범위와 보관 기간을 확인하고 동의 체크 후
공유를 시작하면, 설치가 필요 없는 읽기 전용 참석자 URL이 생성됩니다. 참석자는 브라우저에서
임시·확정 원문, 번역문, 근거 연결형 Decision Radar만 볼 수 있습니다. 자막은 약 450ms
간격으로 갱신되며 원문은 번역이나 Radar보다 먼저 표시될 수 있습니다.
링크만으로는 회의 내용을 읽을 수 없습니다. 참석자는 자신의 Google 계정으로 로그인해야
하며, Viewer 서버가 Supabase access token과 확인된 이메일을 직접 검증한 뒤에만 방별
HttpOnly·Secure·SameSite 쿠키를 발급합니다. 이 쿠키는 새로고침 후에도 방이 끝나기
전까지 유지됩니다. 한 번 로그인한 브라우저는 다음 초대 링크에서 같은 계정을 재사용할 수
있지만, 각 방의 유효기간과 접근 권한은 서버에서 다시 확인합니다.
실시간 공유 영역은 기본적으로 접혀 있으며 제목 줄을 눌러 펼칠 수 있습니다. 접힌 상태에서도
공유 상태 배지는 계속 표시되므로 활성·연결 지연·미설정 상태를 확인할 수 있습니다.

참석자 화면의 확정 자막은 **최신 자막이 목록 맨 위**에 표시됩니다. 새 확정 자막이
들어오면 자막 목록 내부만 맨 위로 유지하므로, 페이지를 아래로 내리지 않고 오른쪽
Radar를 함께 볼 수 있습니다. 임시 자막은 확정 목록 위에서 현재 발화로 계속 표시됩니다.

참석자 화면의 Radar도 진행자 화면과 같은 **핵심·결정·Action·미해결** 탭을 사용합니다.
현재 탭은 최신 항목을 자동으로 따라가지만 참석자가 위로 스크롤하면 멈추며, 숨겨진 탭은
새 항목 표시만 갱신합니다. 좁은 화면에서는 자막 아래에 Radar가 배치됩니다.

- 전송: 공유 시작 이후의 임시·확정 원문, 번역문, Radar 항목과 근거 `segment_id`
- 전송 안 함: 오디오, API 키, Provider·장치 설정, 과거 세션과 JSONL
- 명시적 **공유 종료**: 중계 상태의 텍스트와 호스트 토큰을 즉시 제거
- 비정상 호스트 종료: 마지막 heartbeat 이후 15분이 지나면 다음 접근 전에 만료·제거
- 모든 방: 생성 후 최대 8시간, 최근 자막 80개만 중계 상태에 유지
- 중계·네트워크 장애: 공유 상태만 `연결 지연`으로 표시하고 로컬 원문·번역·저장은 계속
- 인증 신원: Supabase Auth의 Google identity와 확인된 이메일만 사용하고 브라우저가 보낸
  이메일 문자열을 권한 판단에 직접 사용하지 않음
- 링크별 접속 기록: 인증 이메일, 최초 인증·마지막 확인 시각과 입장 이벤트는 해당 방의
  공유 종료·만료까지만 D1에 보관한 뒤 중계 텍스트·신원·세션과 함께 삭제. 진행자가 종료 시
  받은 정제된 최종 감사 사본만 로컬에 최대 30일 보관하며 원본 IP는 저장하지 않고 해시만 사용

중계 설정은 일반 Provider 키와 분리된 `.share.env`에 둡니다. 이 파일은 Git과 Lite
배포에서 제외됩니다. `MLT_SHARE_RELAY_SECRET`은 참석자 URL에 들어가는 방 ID나 방별
호스트 토큰과 별개의 **방 생성용 비밀값**이며 Sites의 secret 환경변수와 정확히 같아야
합니다. 실제 회의에서는 회사 보안정책과 참가자 동의를 먼저 확인하세요.

참석자 신원은 기존 Why 서비스의 Supabase Auth Google Provider를 재사용합니다. Sites
production runtime에는 다음 값만 설정합니다. Publishable key는 공개 클라이언트용이지만
설정값은 한곳에서 관리하며, 서명용 secret은 Git·문서·공유 URL에 넣지 않습니다.

```text
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
MLT_ACCESS_SIGNING_SECRET=<별도의 32-byte 이상 무작위 secret>
```

Supabase 설정이 없으면 새 공유방 생성은 `viewer_supabase_auth_not_configured`로 안전하게
거부되며 기존 로컬 전사·번역·Radar는 계속 동작합니다. Google과 Supabase는 계정 소유 여부만
확인하며 Supabase에는 WhyKaigi 전용 profile·방 접속 감사 table을 두지 않습니다. 입장 화면에는
외부 인증, 공유 종료 시 중계 데이터 삭제, 진행자 로컬 감사 사본의 최대 30일 보관을 표시합니다.

참석자 사이트 소스는 `viewer-site/`에 있습니다. D1에는 오디오나 로컬 세션 JSONL을 저장하지
않고 현재 보기 상태와 최소 인증·접속 감사 데이터만 분리 보관합니다. 진행자 앱의
`data/share-access`에는 링크별 최종 접속 기록이 별도로 저장되며 기존 세션 JSONL은 수정하지
않습니다. 방 URL은 충분히 긴 무작위 ID이고 Google 계정 확인도 필요하지만 공개 채널에
재전송하지 않아야 합니다.

## API

- `GET /api/health`
- `GET /api/audio/devices`
- `POST /api/audio/refresh`
- `GET /api/settings`
- `GET /api/capture/state`
- `POST /api/capture/start`
- `POST /api/capture/pause`
- `POST /api/capture/resume`
- `POST /api/capture/stop`
- `GET /api/translation/providers`
- `GET /api/translation/settings`
- `POST /api/translation/settings`
- `POST /api/translation/test`
- `POST /api/translation/retry/{segment_id}`
- `GET /api/session/settings`
- `POST /api/session/settings`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/segments`
- `POST /api/sessions/{session_id}/finalize`
- `POST /api/sessions/{session_id}/recover`
- `GET /api/sessions/{session_id}/analysis`
- `POST /api/sessions/{session_id}/analysis`
- `POST /api/sessions/{session_id}/analysis/cancel`
- `POST /api/sessions/{session_id}/analysis/retry`
- `GET /api/sessions/{session_id}/download/{json|original-txt|translation-txt|markdown}`
- `GET /api/analysis/providers`
- `GET /api/analysis/settings`
- `POST /api/analysis/settings`
- `GET /api/decision-radar/providers`
- `GET /api/decision-radar/settings`
- `POST /api/decision-radar/settings`
- `GET /api/decision-radar?session_id={session_id}`
- `PATCH /api/decision-radar/items/{item_id}`
- `DELETE /api/decision-radar/items/{item_id}`
- `GET /api/share`
- `POST /api/share/start`
- `POST /api/share/stop`
- `GET /api/share/access-log`
- `WS /ws/live`

브라우저는 WebSocket이 끊기면 지수 백오프로 자동 재연결합니다. 분석 WebSocket 이벤트는 상태와 session ID만 전달하고 큰 분석 본문은 REST로 다시 조회합니다. 서버 오류는 API 키, Authorization 헤더, 전체 요청·응답, traceback, 내부 절대 경로나 민감한 환경변수 내용을 포함하지 않도록 제한되어 있습니다.

## 테스트

자동 테스트:

```bat
.venv\Scripts\python.exe -m pytest -q
```

참석자 사이트는 `viewer-site`에서 `pnpm test`와 `pnpm run lint`로 별도 검증합니다.

Phase 1 실제 하드웨어 체크는 `tests/manual_test_checklist.md`, Phase 2 Provider 체크는 `tests/phase2_manual_test_checklist.md`, Phase 3 세션·분석 체크는 `tests/phase3_manual_test_checklist.md`를 사용합니다. 실행하지 않은 항목을 PASS로 기록하지 말고 전제 조건이 없으면 사유와 함께 `SKIP`으로 남기세요. 실제 OpenAI 분석은 `OPENAI_API_KEY`, `RUN_OPENAI_ANALYSIS_LIVE_TEST=1`, `OPENAI_ANALYSIS_MODEL` 세 조건이 모두 있을 때만 실행합니다. 번역 실사용 플래그와 분석 실사용 플래그는 서로 독립적입니다.

## 문제 해결

- **Python 3.11을 찾지 못함**: 현재 사용자용 Python 3.11을 설치한 뒤 다시 실행합니다. 기존 `.venv`가 다른 버전이면 내용을 검토한 후 이 프로젝트의 `.venv`만 이름 변경 또는 제거합니다.
- **Loopback 없음**: 실제 출력 장치가 활성 상태인지 확인하고 장치를 새로고침합니다. `check_audio_devices.py`의 warnings를 확인합니다.
- **입력 볼륨 0%**: 앱의 Loopback과 Zoom/Windows 출력이 같은지, 재생 중인지 확인합니다.
- **첫 시작이 오래 걸림**: 모델 캐시가 없으면 최초 다운로드·로드 시간이 추가됩니다. 이는 정상 발화 표시 지연과 별도입니다.
- **CUDA 오류**: 오류 안내 후 CPU `int8` fallback 정보가 서버 상태에 나타나는지 확인합니다. GPU가 없다고 임의로 실패로 기록하지 마세요.
- **서버 준비 실패**: `.run/server.stderr.log`를 확인합니다. 포트 8765를 다른 프로그램이 사용하는지도 확인합니다.
- **네이티브 창이 열리지 않음**: `setup_desktop_overlay.bat`을 다시 실행해 프로젝트 내부 Electron 설치를 확인합니다. 실패해도 `set MLT_DESKTOP=0` 후 `start_all.bat`을 실행하면 일반 브라우저 UI를 사용할 수 있습니다. 데스크톱 오류는 `.run/desktop.stderr.log`에만 기록됩니다.
- **투명도는 바뀌지만 Windows 바탕화면이 비치지 않음**: 브라우저 탭이나 일반 팝업인지 확인합니다. 실제 창 투명화와 항상 위 고정은 선택 설치한 Electron 네이티브 앱에서만 지원합니다.
- **브라우저 연결 끊김**: 앱 상태와 WS 상태는 별도입니다. WS가 자동 재연결되지 않으면 서버 상태와 로그를 확인하고 페이지를 새로 고칩니다.
- **OpenAI/Gemini 사용 불가**: `.env`의 해당 API 키와 모델 설정 여부만 UI에서 확인할 수 있습니다. 키 값은 표시되지 않습니다. 설정 후 서버를 다시 시작하세요.
- **OpenAI 인증 실패**: 키를 로그나 화면에 붙여넣지 말고 `.env`를 직접 확인합니다. 원문 전사는 계속 사용할 수 있습니다.
- **rate limit/timeout/네트워크 오류**: 번역 카드의 안전한 오류 코드와 재번역 버튼을 확인합니다. 무한 재시도하지 않습니다.
- **로컬 모델 미설치**: `setup_local_translation.bat`을 실행해 격리 런타임과 M2M100 CT2 모델을 설치합니다. 설치하지 않은 Lite 환경에서 `local`이 사용 불가로 표시되는 것은 정상이며 원문 전사에는 영향을 주지 않습니다.
- **번역이 다른 카드에 보임**: 브라우저를 새로고침하고 `segment_id`가 final 및 translation 이벤트에 모두 있는지 확인합니다. 완료 순서로 카드를 재정렬하지 않습니다.
- **OpenAI 분석을 선택할 수 없음**: API 키와 분석 모델이 모두 명시됐는지 확인합니다. 값 자체는 UI나 공개 API에 나타나지 않습니다.
- **분석 실패**: 원문·번역·기존 내보내기는 유지됩니다. 안전한 오류 상태를 확인하고 설정을 고친 뒤 재시도하세요.
- **세션이 복구됨으로 표시됨**: 이전 실행이 finalize 전에 끝난 세션입니다. 원본 events는 수정하지 않으며 파생 파일을 다시 만들었습니다.

Phase 1 장치·전사 결과는 `docs/phase1_report.md`, Phase 2 구현·보안·번역 결과는
`docs/phase2_report.md`, Phase 3 세션·분석·benchmark 결과는 `docs/phase3_report.md`에
실제 결과 또는 `SKIP`으로 구분해 기록합니다. Decision Radar의 구현·검증 결과는
`docs/decision_radar_report.md`, 실제 API·회의 수동 확인 절차는
`tests/decision_radar_manual_test_checklist.md`에서 확인할 수 있습니다. 결과 전용 창과
네이티브 투명 오버레이의 설치·실행·종료 검증은 `docs/desktop_overlay_report.md`와
`tests/desktop_overlay_manual_test_checklist.md`에 기록합니다.

## OpenAI Build Week 개발 기록

Submission Period 전 프로젝트 기준선, 이후 Codex와 함께 해결한 문제·제품 결정·구현·실측 결과, 제출 체크리스트의 한국어 원본은 [`docs/BUILD_WEEK_LOG_KO.md`](docs/BUILD_WEEK_LOG_KO.md)에 보존합니다. 심사용 영문 기준 문서는 [`docs/BUILD_WEEK_LOG.md`](docs/BUILD_WEEK_LOG.md)입니다. 비밀키와 실제 회의 원문은 기록하지 않습니다.
