# 참석자 초대 링크 공유 구현 보고서

## 목적과 경계

로컬 Windows 앱이 진행자 역할을 유지하면서, 참석자는 별도 설치 없이 브라우저에서
실시간 원문·번역·Decision Radar를 읽을 수 있게 한다. 기존 FastAPI는 인터넷에 직접
노출하지 않고 Sites 기반 중계 서비스에 허용된 텍스트 이벤트만 비동기로 전송한다.

중계 허용 목록은 임시·확정 원문, 번역 상태·결과, Radar 상태·항목·근거 ID, 캡처 상태다.
세션 ID, 과거 기록, JSONL, 오디오, 장치, API 키, Provider·모델 설정은 두 번의 독립된
sanitizer(로컬 호스트와 중계 서버)에서 제거한다. 공유 중계 실패는 WebSocket의 보조
event sink에서 격리되어 로컬 캡처·번역·세션 저장을 중단하지 않는다.

## 구성

- `backend/app/sharing/manager.py`: bounded queue, 120ms 소규모 batch, heartbeat,
  유한 재시도, 허용 목록 sanitizer, 안전한 상태 snapshot
- `GET/POST /api/share*`: 동의 필수 시작, 상태 조회, 명시적 종료
- `viewer-site/app/api/rooms`: 생성 비밀과 방별 호스트 토큰을 분리한 D1 relay API
- `viewer-site/app/room/[roomId]`: 읽기 전용 한·영 참석자 UI, 450ms 폴링,
  원문+번역/번역만, 최신 확정 자막을 목록 맨 위에 유지, Radar 근거 이동,
  핵심·결정·Action·미해결 탭
- `.share.env`: Sites secret과 같은 방 생성 비밀 및 relay URL. Git 무시

## 보관과 장애 정책

- 명시적 종료는 `state_json`과 호스트 토큰 해시를 즉시 비우고 410을 반환한다.
- heartbeat가 15분 끊기거나 생성 후 8시간이 지나면 조회·업데이트 전에 같은 정리를 한다.
- 최근 확정 자막 80개, Radar 100개, 대기 번역 20개로 상태 크기를 제한한다.
- Radar는 한 번에 선택한 범주만 보여주고 내부 영역에서 최신 항목을 따라간다. 사용자가
  과거 항목을 읽으면 자동 스크롤을 멈추고 새 항목 수와 최신 이동 버튼을 표시한다.
- 로컬 outbound queue는 256개이며 partial·상태 이벤트부터 버리고 final·번역·Radar를
  우선 보존한다. 전송은 최대 3회만 시도하며 실패한 batch 때문에 캡처를 기다리지 않는다.

## 검증 결과

- 로컬 앱: 전체 `293 passed, 3 skipped`; JS syntax PASS
- 참석자 사이트: production build, ESLint, 3개 사이트 계약 테스트 PASS
- 로컬 relay 실제 E2E: 방 생성, partial/final, 번역, Radar, 근거 이동, 한·영 전환,
  종료 후 410 및 텍스트 제거 PASS
- Sites 비공개 배포 E2E: D1 방 생성, 이벤트 3개 반영, 읽기, 명시적 삭제, 410 PASS
- 브라우저: 홈/회의방 렌더링, 콘솔 error·warning 0
- 기존 세션: 254개, 3,934,097 bytes, 작업 전후 집계 SHA-256
  `D6A748D68FA5481A360A1189E42BA1C4FFD7951B3963237DF409AC87D786E3EF`

## 남은 단계

현재 Sites 버전 2는 사용자 계정만 허용하는 비공개 배포로 검증했다. 참석자가 로그인 없이
초대 링크를 열려면 사용자의 명시적 승인 후 Sites 접근 정책과 배포를 공개로 전환하고,
그 최종 URL과 생성 secret을 로컬 `.share.env`에 연결한 뒤 공개 경로 E2E를 다시 수행한다.
