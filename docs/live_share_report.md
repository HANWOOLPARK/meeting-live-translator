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
- `viewer-site/app/api/rooms/[roomId]/auth`: Supabase Google identity 검증·방별 세션·로그아웃.
  access token은 서버가 Supabase Auth에 직접 확인하며 클라이언트 이메일 문자열은 신뢰하지 않음
- `viewer-site/supabase/whykaigi_attendee_auth.sql`: 확인된 참석자 profile과 방 입장 로그,
  사용자별 RLS, 30일 만료 정리 trigger
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
- Supabase Auth가 Google 계정과 확인된 이메일을 검증한다. Viewer는 검증된 user ID·이메일로만
  방 세션을 만들고, 운영 D1 로그와 Supabase 입장 로그를 함께 남긴다.
- 인증 이메일·접속 시각·입장 이벤트는 30일 후 지연 정리한다.
- 인증 세션은 방별 Secure·HttpOnly·SameSite=Strict 쿠키이며 방 종료·8시간 상한을 넘지 않는다.
- 원본 IP는 저장하지 않고 secret-keyed HMAC만 rate limit과 감사 이벤트에 사용한다.
- Supabase URL·publishable key 또는 signing secret이 없으면 새 공유방 생성을 거부하고 인증 우회 경로는 없다.

## Google/Supabase 운영 설정

Sites production runtime에 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, 별도 난수
`MLT_ACCESS_SIGNING_SECRET`을 설정한다. Supabase의 Google Provider와 Sites 도메인
redirect URL을 허용해야 한다. 입장 전에 Google/Supabase 외부 인증과 30일 감사 로그 보관을
고지한다. Supabase 공개 테이블은 `anon` 접근을 폐쇄하고 `authenticated` 사용자에게도
본인 row만 허용하는 RLS를 적용한다.

## 검증 결과

- 로컬 앱 전체 회귀: `369 passed, 3 skipped`
- 참석자 사이트: production build, ESLint 경고 0, Node 테스트 `13 passed`
- 로컬 fail-closed 검증: 인증 설정 조회 정상, 익명 방 조회 401, bearer token 없는
  exchange 401, Supabase 또는 signing secret 누락 시 설정 조회·새 방 생성 503 PASS
- Supabase migration 적용: `whykaigi_attendee_profiles`,
  `whykaigi_room_access_logs` 생성, RLS 활성화, `anon` table grant 없음,
  인증 사용자도 본인 row만 접근 가능
- Supabase Security Advisor에서 WhyKaigi 보안 경고 0건. 비어 있는 신규 테이블의
  unused-index INFO만 남아 있음
- Sites production version 11, environment revision 8에서 Google 로그인→Viewer 복귀,
  검증된 이메일 표시, 새로고침 후 세션 유지, D1의 `access_granted`,
  `viewer_entered`, `signed_out` 감사 이벤트와 Supabase 중앙 입장 기록을 확인
- 로그아웃 후 Google 로그인 화면 복귀, 공유 종료 후 시험방 조회 410 확인
- 검증용 Supabase 인증 세션과 시험방은 검증 직후 폐기
- 기존 JSONL 137개는 작업 전후 경로·길이·파일별 SHA-256이 동일하며, 기준 집계
  SHA-256은 `22EC8102AD0CEA1BBADD229C59CE8FF6B11BEB3F7601ABEE3B8C00BE1F35545F`

## 운영 상태와 후속 경계

운영 Viewer는 Resend OTP 대신 Supabase Google 인증을 사용한다. Sites runtime에서
Resend·OTP 환경변수는 제거했고 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
`MLT_ACCESS_SIGNING_SECRET`을 사용한다. Viewer 방 redirect wildcard도 기존 Why BJT와
localhost 항목을 보존한 채 Supabase 허용 목록에 등록했다.

현재는 기존 Why BJT Supabase 프로젝트를 재사용하지만 WhyKaigi 테이블은 별도 prefix와
RLS로 격리했다. Auth 사용자 풀은 공유된다. 현재 개인 운영에는 충분하지만, WhyKaigi를
독립 유료 서비스로 출시하기 전에는 장애·quota·운영 권한을 분리하기 위해 전용 Supabase
프로젝트로 이전하는 것을 권장한다.
