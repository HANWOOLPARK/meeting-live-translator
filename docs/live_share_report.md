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
- `GET/POST /api/share*`: 동의 필수 시작, 상태·링크별 접속 기록 조회, 명시적 종료
- `viewer-site/app/api/rooms`: 생성 비밀과 방별 호스트 토큰을 분리한 D1 relay API
- `viewer-site/app/room/[roomId]`: 읽기 전용 한·영 참석자 UI, 450ms 폴링,
  원문+번역/번역만, 최신 확정 자막을 목록 맨 위에 유지, Radar 근거 이동,
  핵심·결정·Action·미해결 탭
- `viewer-site/app/api/rooms/[roomId]/auth`: 이메일 OTP 발급·확인·방별 세션·로그아웃.
  Resend 메일 전송, 10분 만료, 5회 시도 제한, 45초 재발송 제한과 이메일/IP rate limit
- `viewer-site/app/api/rooms/[roomId]/access-log`: 방별 host token으로만 조회하는 인증·입장 감사 기록
- `data/share-access`: 공유 종료 시 진행자 로컬에 저장하는 링크별 감사 사본. 세션 JSONL과 분리
- `.share.env`: Sites secret과 같은 방 생성 비밀 및 relay URL. Git 무시

## 보관과 장애 정책

- 명시적 종료는 `state_json`과 호스트 토큰 해시를 즉시 비우고 410을 반환한다.
- heartbeat가 15분 끊기거나 생성 후 8시간이 지나면 조회·업데이트 전에 같은 정리를 한다.
- 최근 확정 자막 80개, Radar 100개, 대기 번역 20개로 상태 크기를 제한한다.
- Radar는 한 번에 선택한 범주만 보여주고 내부 영역에서 최신 항목을 따라간다. 사용자가
  과거 항목을 읽으면 자동 스크롤을 멈추고 새 항목 수와 최신 이동 버튼을 표시한다.
- 로컬 outbound queue는 256개이며 partial·상태 이벤트부터 버리고 final·번역·Radar를
  우선 보존한다. 전송은 최대 3회만 시도하며 실패한 batch 때문에 캡처를 기다리지 않는다.
- 인증 전 방 상태 API는 401을 반환하므로 URL만으로 자막·번역·Radar를 읽을 수 없다.
- OTP 원문은 저장하지 않고 방·challenge·이메일에 묶인 HMAC만 저장한다. OTP 도전 데이터는
  최대 24시간, 인증 이메일·접속 시각·입장/거절 이벤트는 30일 후 지연 정리한다.
- 인증 세션은 방별 Secure·HttpOnly·SameSite=Strict 쿠키이며 방 종료·8시간 상한을 넘지 않는다.
- 원본 IP는 저장하지 않고 secret-keyed HMAC만 rate limit과 감사 이벤트에 사용한다.
- 메일 Provider 또는 signing secret이 없으면 새 공유방 생성을 거부하고 인증 우회 경로는 없다.

## 인증 메일 운영 설정

Sites production runtime에 `RESEND_API_KEY`(sending-only secret), 검증된 도메인의
`MLT_OTP_FROM_EMAIL`, 별도 난수 `MLT_OTP_SIGNING_SECRET`을 설정한다. Resend 기본
`resend.dev` 발신자는 계정 소유자 대상 시험용이므로 실제 참석자 공유에는 검증된 발신
도메인이 필요하다. 메일 전송을 위해 이메일이 Resend로 전달된다는 사실과 앱의 30일
감사 로그 보관을 입장 전에 고지한다.

## 검증 결과

- 로컬 앱 전체 회귀: `359 passed, 3 skipped`; Python compile 및 frontend JS syntax PASS
- 공유·UI·다국어 대상 테스트: `24 passed`
- 참석자 사이트: production build, ESLint 경고 0, OTP 암호·쿠키 및 route 계약을 포함한
  Node 테스트 `12 passed`
- 로컬 Vinext+D1 인증 E2E: 익명 방 조회 401, 인증 상태 false, 잘못된 challenge 400,
  host 조회 200, host 감사 로그 200, 삭제 200, 종료된 방 410 PASS
- 실제 메일 발송과 운영 Sites 배포는 실행하지 않았다. 검증된 발신 도메인과
  sending-only key가 없는 상태에서 fail-closed 빌드를 배포하면 새 공유방 생성이 막히기 때문이다.
- 기존 세션: 456개(이 중 JSONL 107개), 5,600,489 bytes, 작업 전후 집계 SHA-256
  `9263139A75FE0108382864618ED3D9A489C7BD280120D636EBE188AA46456DE8`

## 남은 단계

현재 Sites 프로젝트의 접근 정책은 공개이지만, 운영 중인 기존 버전에는 이번 이메일 OTP
변경을 아직 배포하지 않았다. 따라서 새 버전 배포 전까지 현재 링크를 외부에 공유하지 않는다.
검증된 발신 도메인과 Resend sending-only key를 Sites runtime에 설정한 뒤 새 버전을
배포하고, 서로 다른 외부 이메일 2개로 코드 수신→입장→새로고침→로그 표시→공유 종료 후
410/세션 폐기를 확인하는 것이 마지막 운영 단계다.

2026-07-21 시험 발신자 설정으로 version 7 배포와 운영 API 검증을 진행했으나 Resend가
설정된 키를 `401 API key is invalid`로 거부했다. 참석자 입장이 막힌 상태를 남기지 않기
위해 OTP 환경 변수를 제거하고 직전 정상 version 6으로 롤백했다. 새 Resend 키를 발급해
로컬 비밀 파일의 `RESEND_API_KEY`만 교체한 뒤 version 7을 다시 배포해야 한다.

같은 날 유효한 새 키로 교체한 뒤 version 7을 운영에 재배포했다. 운영 시험방에서 생성
201, 인증 전 상태 조회 401, 인증 설정 조회 200, 실제 OTP 메일 요청 202, host 감사 로그
200과 `verification_code_sent`를 확인했다. 남은 검증은 수신한 코드 입력, 새로고침 후
세션 유지, 참석자 이메일 표시, 방 종료 후 410과 세션 폐기다.
