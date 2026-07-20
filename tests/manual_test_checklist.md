# Phase 1 수동 테스트 체크리스트

실제 Windows 오디오 장치, GPU 또는 비민감 음성 샘플이 필요한 검증용 문서다. 실행 전 `setup.bat`을 완료하고, 실제 회의 녹음이나 민감 정보가 든 파일을 사용하지 않는다.

## 결과 기록 규칙

- `PASS` / `FAIL`: 자동 테스트 결과에만 사용한다.
- `MANUAL PASS`: 아래 절차를 사람이 실행하고 기대 결과를 모두 직접 관찰했다.
- `MANUAL FAIL`: 실행했으나 하나 이상의 기대 결과가 충족되지 않았다.
- `SKIP`: 실행하지 않았거나 장치·샘플·CUDA 등 전제 조건이 없다. 반드시 사유를 쓴다.
- 미실행 항목을 PASS 또는 MANUAL PASS로 추정하지 않는다.
- 모든 항목에 실행 명령/절차, 결과, 오류 요약, FAIL 또는 SKIP 사유를 남긴다.

### 실행 정보

| 항목 | 기록 |
| --- | --- |
| 날짜/시간대 | 2026-07-10 / Asia/Seoul |
| 테스트 담당자 | Codex 로컬 실측 |
| Windows 버전 | Windows 11, NT 10.0.26200.0 |
| Python / 앱 버전 | Python 3.11.9 / 0.1.0-phase1 |
| 출력 장치 | pa:14 Speaker (Realtek Speaker) |
| Loopback 장치 | pa:19 Speaker (Realtek Speaker) [Loopback] |
| 마이크 | pa:1 마이크 배열(목록만 확인, 실제 캡처 미실행) |
| GPU / 드라이버 | Intel(R) Graphics / NVIDIA 없음 / CTranslate2 CUDA device 0 |
| 사용한 비민감 샘플 | Windows SAPI Haruka·Zira 합성 일본어/영어 WAV, 메모리 생성 440 Hz 톤 |

## M-01 장치 목록과 Loopback 식별

- 실행: `.venv\Scripts\python.exe scripts\check_audio_devices.py`
- 절차: 출력, WASAPI Loopback, 마이크 그룹과 기본 장치 표시를 확인한다.
- 기대: 각 장치에 ID, 이름, host API, 채널, 샘플레이트가 보이고 Loopback이 일반 입력과 구분된다.
- 결과 (`MANUAL PASS` / `MANUAL FAIL` / `SKIP`): `MANUAL PASS`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: 출력 11개, Loopback 3개, 마이크 8개 확인.

## M-02 기본 출력 ↔ Loopback 매칭

- 실행: 위 장치 점검 명령 및 `GET http://127.0.0.1:8765/api/audio/devices`
- 절차: Windows 기본 출력 이름과 `default_output_id`, `default_loopback_id`, `output_loopback_pairs`를 비교한다.
- 기대: 유일하게 확인 가능한 대응만 매칭되며 모호한 장치는 임의 매칭되지 않는다.
- 결과: `MANUAL PASS`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: pa:14↔pa:19, pa:15↔pa:20, pa:16↔pa:21의 유일 매칭 확인.

## M-03 시스템 음성 캡처 lifecycle과 입력 레벨

- 실행: `start_all.bat`
- 절차: 비민감 테스트 음원을 재생하고 대응 Loopback을 선택해 시작 → 일시정지 → 재개 → 중지를 수행한다.
- 기대: 상태가 순서대로 바뀌고 재생 중 레벨이 0보다 크며, 일시정지/중지 후 안정적으로 내려간다. 서버는 계속 응답한다.
- 결과: `MANUAL PASS`
- 오류 요약: 첫 무음 실행은 callback 0개였고, 테스트 톤 재생으로 재검증함.
- FAIL/SKIP 사유 및 메모: running→paused→running→stopped 확인. 테스트 톤에서 53 frame, 51 non-zero frame, 최대 RMS 0.17266, last_error 없음.

## M-04 마이크 캡처와 장치 변경

- 실행: 브라우저 UI
- 절차: 마이크 소스를 선택해 비민감 문장을 말한다. 중지 후 다른 입력 장치로 변경해 다시 시작한다.
- 기대: 선택한 마이크에서만 레벨과 자막이 나타나며 장치 변경 뒤 서버 재시작이 필요 없다.
- 결과: `SKIP`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: 마이크 목록과 선택 UI는 확인했으나 실제 주변 음성 캡처는 수행하지 않음.

## M-05 Zoom·헤드폰·Bluetooth 출력 대응

- 실행: Zoom 테스트 통화 또는 비민감 로컬 재생
- 절차: Zoom/Windows 출력을 헤드폰 또는 Bluetooth로 선택하고 동일 이름의 Loopback을 앱에서 선택한다. 일부러 다른 Loopback도 비교한다.
- 기대: 동일 출력에서 레벨이 들어오고, 다른 출력에서는 입력되지 않을 수 있다는 UI 안내가 명확하다.
- 결과: `SKIP`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: AirPods endpoint는 Status=Unknown이었고 실제 Zoom 통화/Bluetooth 출력 전환을 수행하지 않음. UI 안내는 브라우저에서 확인.

## M-06 일본어 전사·언어 감지

- 실행: 비민감 일본어 샘플을 시스템 출력으로 재생하거나 직접 읽는다.
- 절차: 모델 `small`로 캡처하고 partial, final, 시간, 언어를 관찰한다.
- 기대: 발화별 final이 생성되고 일본어는 신뢰도 기준에 따라 `ja` 또는 낮은 신뢰도면 `unknown`이다.
- 결과: `MANUAL PASS`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: SAPI Haruka 합성 음성을 실제 pa:19 loopback으로 캡처. partial 1개와 final 2개, ja 확률 0.9641~0.9942, 브라우저·JSONL 표시 확인.

## M-07 영어 전사·언어 감지

- 실행: 비민감 영어 샘플을 시스템 출력으로 재생하거나 직접 읽는다.
- 절차/기대: M-06과 같으며 언어는 `en` 또는 낮은 신뢰도면 `unknown`이다.
- 결과: `MANUAL PASS`
- 오류 요약: 무음 callback이 짧아 두 번째 문장은 중지 flush로 확정됨.
- FAIL/SKIP 사유 및 메모: SAPI Zira 합성 음성을 실제 loopback으로 캡처. 브라우저에서 첫 final·두 번째 partial을 확인하고 stop 후 두 final이 JSONL에 저장됨. en 확률 0.9922~0.9947.

## M-08 mixed/unknown 및 중복 억제

- 실행: 일본어에 영어 기술 용어가 섞인 문장과 같은 짧은 샘플 1회를 사용한다.
- 절차: partial 갱신과 final 확정 후 목록 및 세션 JSONL을 확인한다.
- 기대: 지원 외/낮은 신뢰도 언어가 강제로 ja/en이 되지 않고, 동일 발화 재전사 조각이 중복 저장되지 않으며 서로 다른 정상 문장은 보존된다.
- 결과: `SKIP`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: 실제 mixed 발화는 미실행. unknown/mixed 휴리스틱과 공백·문장부호·부분 중복 억제는 자동 테스트 PASS.

## M-09 WebSocket 재연결과 UI 표시 기능

- 실행: 브라우저 개발자 도구 Network/WS 및 UI
- 절차: 캡처 중 페이지 네트워크를 잠시 오프라인으로 전환 후 복구한다. 자동 스크롤을 켜고 끄며 글자 크기를 변경하고 창 폭을 줄인다.
- 기대: WS 상태가 끊김/재연결됨으로 바뀌고 서버가 살아 있으면 자막 수신이 복구된다. 자막 설정과 반응형 레이아웃이 동작한다.
- 결과: `SKIP`
- 오류 요약: 모바일 full-page screenshot은 브라우저 CDP timeout 2회.
- FAIL/SKIP 사유 및 메모: WS 연결·서버 재시작 후 연결, 데스크톱 UI, 390×844에서 scrollWidth=clientWidth=375 및 핵심 컨트롤 가시성은 확인. 오프라인 토글과 자동 스크롤/글자 크기 실제 조작 전체 절차는 미실행.

## M-10 잘못된 장치 오류 격리

- 실행 예: 존재하지 않는 ID로 `POST /api/capture/start`, 이후 `GET /api/health`
- 절차: 비정상 요청 뒤 정상 장치로 다시 시작한다.
- 기대: 안전한 recoverable 오류가 반환되고 민감 정보가 없으며 health는 계속 `ok`이고 정상 재시도가 가능하다.
- 결과: `SKIP`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: 실제 서버 수동 요청 대신 자동 API 테스트로 존재하지 않는 장치 404, 잘못된 source 400, 후속 health 200 및 오류 문자열 sanitization을 PASS함.

## M-11 CUDA 실제 초기화 또는 CPU fallback

- 실행: `start_all.bat` 후 최초 캡처 시작, 서버 상태/로그 확인
- 절차: CUDA 가능 장치에서는 실제 모델 초기화 결과를 확인한다. GPU가 없거나 초기화 실패하면 CPU 경로를 확인한다.
- 기대: GPU 성공은 실제 초기화 성공 때만 보고된다. 실패 시 서버가 종료되지 않고 CPU `int8` 및 fallback 상태가 표시된다.
- 결과: `MANUAL PASS`
- 오류 요약: CUDA driver version insufficient로 실제 CUDA 모델 생성 실패.
- FAIL/SKIP 사유 및 메모: 서버 종료 없이 small 모델이 CPU/int8로 로드됨. model_runtime.cuda_fallback=true 확인.

## M-12 실제 표시 지연 측정

- 실행: 시간 기준이 보이는 비민감 샘플 또는 스톱워치
- 절차: 발화 종료 시각부터 partial 최초 표시와 final 표시까지 최소 5회 측정한다. 최초 모델 로드 시간은 별도로 적는다.
- 기대: 측정값을 그대로 기록하며 목표 2~4초를 벗어나도 임의로 PASS 처리하지 않는다.
- 결과: `SKIP`
- 측정값 partial(초): 최초 partial은 재생 시작 후 3.770초에 표시. 발화 종료 기준 5회 측정은 미실행.
- 측정값 final(초): 발화 종료→이벤트 2.863, 2.820, 3.153, 2.875, 2.940.
- 최초 모델 로드(초): 2.238.
- 오류 요약 / FAIL·SKIP 사유: final 5회는 목표 2~4초 범위. partial의 동일 기준 5회가 없어 전체 절차는 SKIP.

## M-13 저장·Phase 2 제한 확인

- 실행: 한 세션 전사 후 `data\sessions` 확인
- 절차: JSONL에 final만 있는지, 오디오 파일이 생기지 않는지, 번역 패널이 비활성 안내만 표시하는지 확인한다.
- 기대: partial/PCM/녹음 파일과 가짜 한국어 번역이 없고 API 키 없이 서버가 실행된다.
- 결과: `MANUAL PASS`
- 오류 요약: 없음
- FAIL/SKIP 사유 및 메모: JSONL에는 final만 존재하고 PCM/WAV는 프로젝트에 저장되지 않음. 번역 패널은 Phase 2 안내만 표시하며 API 키 없이 실행됨.

## 최종 수동 판정

| 구분 | 개수 |
| --- | ---: |
| MANUAL PASS | 7 |
| MANUAL FAIL | 0 |
| SKIP | 6 |

- 남은 blocker: 없음.
- 재현 절차: 해당 없음.
- 사용자 확인 필요 항목: 실제 마이크, Zoom/Bluetooth, mixed 발화, 장시간 실제 회의에서의 지연과 안정성.
