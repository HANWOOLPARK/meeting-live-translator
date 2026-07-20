# Decision Radar 결과 창·자막·네이티브 투명 오버레이 수동 체크리스트

실제로 수행한 항목만 `MANUAL PASS`로 기록한다. 소스 계약만 확인한 항목은
`AUTOMATED PASS`, 외부 API나 실제 회의가 필요한 미수행 항목은 `SKIP`이다.

테스트 환경: Windows 11, localhost, Electron 43.1.1  
실행일: 2026-07-15~16

| # | 항목 | 상태 | 확인 메모 |
|---:|---|---|---|
| 1 | 선택 설치가 관리자 권한·전역 Node 없이 완료 | MANUAL PASS | portable Node 24.18.0과 Electron 43.1.1 프로젝트 내부 설치 |
| 2 | `start_all.bat` 한 번으로 서버·Worker·Electron 실행 | MANUAL PASS | 세 PID, desktop ready, health `ok` 확인 |
| 3 | Electron 메인 화면 정상 표시 | MANUAL PASS | 기존 전체 설정·자막·번역·Radar UI 표시 |
| 4 | 자막 창이 별도 frameless 창으로 열림 | MANUAL PASS | 별도 Electron window와 독립 WS 연결 확인 |
| 5 | Radar **결과 창**이 별도 frameless 창으로 열림 | MANUAL PASS | Provider 입력 없이 상태·세션·queue·결과 영역만 표시 |
| 6 | Radar 결과 창에 Provider 설정 control 없음 | MANUAL PASS | 안내는 “Provider 설정은 메인 창에서 변경”으로 표시 |
| 7 | 결과 창 0~85% 배경 투명도 | MANUAL PASS | 85%에서 뒤 메인 화면이 비치고 글자 유지 |
| 8 | 자막 창 0~85% 배경 투명도 | MANUAL PASS | native transparent surface와 불투명 자막/toolbar 확인 |
| 9 | 두 overlay의 항상 위 Electron 설정 | AUTOMATED PASS | constructor, runtime `setAlwaysOnTop`, IPC 상태 계약 검사 |
| 10 | 한/영 UI가 메인·자막·결과 창에서 공유 | MANUAL PASS | 브라우저와 native 결과 창에서 언어 전환 확인 |
| 11 | Radar 결과 창 narrow layout에 수평 overflow 없음 | MANUAL PASS | 420px browser viewport와 native 고정 창 확인 |
| 12 | 결과 승인·수정·삭제 API 연결 | AUTOMATED PASS | REST mutation과 안전한 DOM 렌더링 테스트 |
| 13 | 근거 클릭이 메인 창 `segment_id`로 전달 | AUTOMATED PASS | BroadcastChannel + native focus IPC 계약 검사 |
| 14 | `stop_all.bat`이 세 PID·포트·PID 파일 정리 | MANUAL PASS | desktop/server/Worker 종료, port 8765 listener 0 |
| 15 | 다른 Python/Electron/Node 일괄 종료 없음 | MANUAL PASS | 별도 Codex Node PID가 stop 후에도 유지됨 |
| 16 | 종료 후 `start_all.bat` 재실행 | MANUAL PASS | 서버·Worker·Electron 새 PID와 health `ok` 확인 |
| 17 | 선택 설치가 없을 때 브라우저 fallback | AUTOMATED PASS | 파일 존재 검사와 `MLT_DESKTOP=0` 경로 테스트 |
| 18 | 기존 세션 JSONL 불변 | AUTOMATED PASS | 179개 파일 정렬 집계 SHA-256 동일 |
| 19 | 전체 회귀 테스트 | AUTOMATED PASS | 276 passed, 3 external live-test skipped |
| 20 | Lite ZIP에 overlay 설치 source 포함·runtime/세션 제외 | MANUAL PASS | 305,370 bytes, 105 entries, 필수 source 누락 0, 실제 세션 entry 0 |
| 21 | 실제 Radar 항목을 native 창에서 편집·근거 이동 | SKIP | 실제 OpenAI/Gemini Radar 호출 또는 비민감 fixture 회의 필요 |
| 22 | 메인 **미디어 자막** 버튼이 별도 native 창을 엶 | MANUAL PASS | 별도 Electron window 제목과 독립 창 생성 확인 |
| 23 | 미디어 자막 기본 하단 중앙 배치 | MANUAL PASS | 현재 모니터에서 94%, 1605 × 220px, 하단 중앙 배치 확인 |
| 24 | 미디어 너비 60%·80%·94% 제한과 display 재배치 | AUTOMATED PASS | 제한 IPC, 현재 display workArea, display 변경 event 계약과 브라우저 선택값 확인 |
| 25 | 최신 1개·자동 원문→번역·partial 우선 | AUTOMATED PASS | 격리 synthetic WebSocket으로 실제 세션을 읽지 않고 세 상태 확인 |
| 26 | 긴 문장 18px까지 자동 축소 후 ellipsis | AUTOMATED PASS | 1600px 36→26px, 960px 18px, nowrap·수평 overflow 없음 |
| 27 | 미디어 자막 한/영 UI | AUTOMATED PASS | 제목, 자동 모드, 창 너비 세 옵션, 닫기 접근성 이름 확인 |
| 28 | 실제 영상 음성·번역을 native 미디어 창에 장시간 표시 | SKIP | 비민감 음성과 외부 STT/번역 사용 조건이 필요한 실사용 항목 |

## 안전 확인

- API 키, 실제 회의 원문, 개인 로컬 경로를 스크린샷·배포 ZIP·공개 문서에 넣지 않는다.
- 네이티브 runtime 설치 실패는 서버·원문 전사 실패로 취급하지 않는다.
- 투명 창은 Windows/Electron 제약 때문에 자유 resize하지 않는다. 일반 overlay는 toolbar로
  이동하고 미디어 자막은 하단 중앙의 60%·80%·94% 너비 프리셋을 사용한다.
- 미실행 외부 API·실제 회의 항목은 PASS로 바꾸지 않는다.
