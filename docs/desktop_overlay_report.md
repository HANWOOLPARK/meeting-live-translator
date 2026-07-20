# Decision Radar 결과 창·네이티브 투명 오버레이 보고서

- 완료일: 2026-07-15~16 (Asia/Seoul)
- 구현 범위: Decision Radar 결과 전용 분리 창, 전체 기록 자막 창, 하단 한 줄 미디어
  자막, Electron 투명/항상 위 창, 선택 설치와 안전한 실행·종료·Lite 배포 연결
- 최종 판정: **자동 회귀·실제 설치·Windows 네이티브 UI·실행/종료 검증 PASS**

## 1. 결과 패널의 위치와 분리 기준

메인 화면의 Decision Radar 카드에는 Provider 선택·가용성·모델·적용 설정과 실제 결과가
함께 있다. 실제 결과는 다음 네 그룹이다.

- 결정 사항
- 해야 할 일·담당자·기한
- 미해결 질문
- 확인이 필요한 사람 이름·용어·번역

이번 작업은 Provider 설정을 떼어 내지 않았다. Radar 제목의 **결과 창** 버튼은 읽기 전용
Provider 상태, 세션, queue와 위 네 결과 그룹만 `/decision-radar` 창으로 연다. 결과 창에서
승인·수정·삭제와 근거 이동을 실행할 수 있고, 근거 이동은 메인 창의 같은
`evidence_segment_id` 자막으로 연결된다.

## 2. 브라우저와 네이티브 동작

- 선택 설치 전: `/captions`, `/captions?layout=media`, `/decision-radar` 일반 브라우저 pop-up
- 선택 설치 후: `start_all.bat`이 Electron 메인 앱을 열고 세 버튼이 네이티브 overlay 생성
- `MLT_DESKTOP=0`: 설치 여부와 관계없이 브라우저 UI 강제 사용
- Electron 시작 실패: 서버와 원문 전사를 유지하고 기본 브라우저로 fallback

세 overlay는 별도 WebSocket으로 live 상태를 받으며, 메인 창과 한/영 UI 선택을 공유한다.
배경 투명도는 0~85%로 제한해 배경만 투명하게 만들고 글자·버튼은 불투명하게 유지한다.

**미디어 자막**은 전체 기록 창과 분리된 시청용 모드다. 가장 최근 한 문장만 표시하고,
기본 `자동 · 번역 우선`에서는 번역 전 원문을 즉시 보인 뒤 같은 `segment_id`의 번역으로
교체한다. partial도 final 전 임시 한 줄로 표시한다. 모니터 너비 60%·80%·94%,
22~48px 기본 글자 크기, 자동·원문·번역·둘 다 보기와 투명도 설정을 제공한다. 긴 문장은
18px까지 자동 축소한 뒤에만 말줄임표를 사용한다.

## 3. Windows 오버레이 구현

Electron overlay는 다음 경계로 만들었다.

- frameless, transparent, `#00000000`, 그림자 없음
- 앱 수준 `alwaysOnTop`과 `floating` level
- 상단 toolbar drag, 버튼·입력·scroll 영역은 no-drag
- preload의 제한된 IPC만 노출하고 Node integration 비활성화
- context isolation과 renderer sandbox 활성화
- localhost origin 밖 navigation과 새 창 차단
- 모든 renderer permission 요청 거부

Electron 공식 문서가 Windows 투명 창의 사용자 resize를 지원하지 않는다고 명시하므로
자유로운 모서리 drag resize는 제공하지 않는다. 전체 기록 자막과 Radar는 고정 크기로
toolbar 이동을 지원한다. 미디어 자막은 현재 메인 창이 있는 display의 작업 영역을 찾아
하단 12px 여백에 가운데 배치하고, 제한된 IPC가 60%·80%·94% 중 하나로만 프로그램 방식
크기를 바꾼다. 모니터 작업 영역 변경·제거 시에도 안전하게 다시 배치한다.

## 4. 선택 설치와 Lite 배포

`setup_desktop_overlay.bat`은 전역 Node.js를 변경하지 않는다. 프로젝트 내부
`.runtime/node`에 Node.js `v24.18.0` portable archive를 설치하기 전에 공식
`SHASUMS256.txt`와 SHA-256을 대조하고, `desktop/node_modules`에 정확히 고정한 Electron
`43.1.1`을 설치한다. npm 환경이 Electron binary hook을 생략할 때는 package가 제공한
`electron/install.js`를 명시적으로 실행한 뒤 `electron.exe` 존재를 다시 검증한다.

Lite ZIP은 setup source, Electron main/preload, exact package lock을 포함하지만 `.runtime`과
`node_modules`는 제외한다. 받는 사람은 실제 네이티브 overlay가 필요할 때만 선택 설치한다.

## 5. 안전한 실행과 종료

`start_all.bat`은 서버·로컬 번역 Worker·Electron PID와 ready/log 파일을 `.run` 아래에
분리한다. `stop_all.bat`은 Electron PID의 명령행에 정확한 프로젝트 경로와
`desktop/main.cjs`가 모두 있는지 확인한 뒤 그 PID tree만 종료한다. 모든
`electron.exe`나 `python.exe`를 이름으로 일괄 종료하는 경로는 없다.

실제 검증에서는 다음 순서를 수행했다.

1. 기존 서버가 실행된 상태에서 `start_all.bat` 한 번으로 Electron 시작
2. server, Worker, desktop PID·ready와 health 확인
3. 자막 창, 미디어 자막, Radar 결과 창을 각각 네이티브로 열어 화면 확인
4. Radar 배경 투명도 85%에서 메인 앱이 비치고 글자는 유지되는지 확인
5. `stop_all.bat`으로 세 프로세스와 8765 listener, 네 PID/ready 파일 정리
6. Codex가 사용하는 별도 Node 프로세스가 살아 있음을 확인
7. `start_all.bat`으로 앱을 다시 정상 실행 상태로 복구

## 6. 검증 결과

```text
node --check desktop/main.cjs
node --check desktop/preload.cjs
node --check frontend/static/app.js
node --check frontend/static/captions.js
node --check frontend/static/decision-radar-window.js
PASS

PowerShell parser:
scripts/setup_desktop_overlay.ps1
scripts/start_desktop.ps1
scripts/stop_project.ps1
scripts/build_lite_release.ps1
PASS

.venv\Scripts\python.exe -m pytest -q \
  tests\test_desktop_overlay.py tests\test_caption_window.py \
  tests\test_decision_radar_window.py tests\test_ui_i18n.py
21 passed in 3.33s

.venv\Scripts\python.exe -m pytest -q
276 passed, 3 skipped in 12.38s

cmd /c setup_desktop_overlay.bat
Node.js v24.18.0 / Electron 43.1.1 ready

cmd /c start_all.bat
server + local Worker + Electron ready

cmd /c stop_all.bat
validated desktop/server/Worker stopped; port and PID files clean

cmd /c make_lite_release.bat
meeting-live-translator-lite-20260716.zip created; 305,370 bytes; 105 entries
SHA-256 8B5D431059E0B23847680A8A9B600D8BD3F2F8B33086811F4BA3E0E454EC0F5A
required desktop sources present; sensitive/runtime/session entries 0
```

미디어 자막 추가 검증에서는 Windows 네이티브 버튼으로 별도 창을 열어 현재 모니터 하단
중앙의 `1605 × 220px`(기본 94%) 배치를 확인했다. 설치된 Edge와 Playwright에서는 실제
세션을 읽지 않는 synthetic WebSocket으로 최신 문장 1개, 원문→번역 자동 전환, partial
우선 표시, 1600px에서 36→26px 자동 축소, 960px에서 최저 18px 후 ellipsis, 수평 overflow
없음, 너비 세 프리셋과 한/영 UI를 확인했다. JavaScript page/runtime 오류는 0건이었다.

3개 SKIP은 명시적 환경·비용 승인이 필요한 기존 OpenAI 분석, OpenAI 번역, 로컬 번역
실사용 테스트다. 이번 UI/overlay 회귀 실패가 아니다.

기존 세션 179개 파일의 정렬 집계 SHA-256은 작업 전 기준과 작업 후에 동일했다.

```text
FD0D03ED08680FD5D1F4C138627997DE65C6EE2FC1265A9E7BAC368812948AB9
```

## 7. 실패·절충·남은 확인

- 첫 npm 설치는 dependency 설치 후 Electron binary hook을 실행하지 않아 `electron.exe`가
  없었다. package-owned install hook 실행과 후검증을 setup script에 추가했고 재실행은
  성공했다.
- 첫 네이티브 실행은 PowerShell의 hidden window option 때문에 UI가 보이지 않았다.
  Electron main window까지 숨기는 option을 제거하고 재실행해 해결했다.
- 미디어 자막 자동화의 첫 `agent-browser` 실행은 CLI가 PATH에 없어 실패했고, bundled
  Playwright와 설치된 Edge로 교체했다.
- 첫 긴 미디어 문장 검증은 CSS grid의 intrinsic track이 콘텐츠 폭으로 늘어나 자동 축소가
  시작되지 않았다. 자막 scroll/list/item을 bounded flex 폭으로 바꾼 뒤 26px/18px 축소와
  overflow 없는 한 줄 표시를 다시 확인했다.
- 작은 결과 창에서 언어 전환이 숨는 문제가 있어 toolbar 반응형 CSS를 수정했다.
- favicon 404는 data favicon으로 제거했고 최종 browser console/HTTP 오류는 0건이었다.
- Windows transparent window는 자유 resize를 제공하지 않는다. 미디어 자막은 안전한
  60%·80%·94% 프리셋만 제공하며 임의 비율이 필요하면 불투명 창 모드가 별도로 필요하다.
- 실제 Radar 항목이 생성된 상태에서 장시간 overlay 편집·근거 이동을 반복하는 검증은
  외부 API 또는 fixture 주입을 사용한 별도 수동 확인이 남았다.
- 실제 비민감 영상 음성과 번역을 네이티브 미디어 창에 장시간 흘려 보내는 검증은 이번
  synthetic UI 검증 범위에 포함하지 않았다.
