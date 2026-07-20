# Phase 3 수동 테스트 체크리스트

자동 mock 테스트 결과를 수동 PASS로 대체하지 않는다. 실제로 수행한 항목만 `MANUAL PASS` 또는 `MANUAL FAIL`로 기록하고, 장치·API 키·회의 시간이 필요한 미수행 항목은 `SKIP`으로 남긴다.

테스트 환경: Windows 11, Python 3.11, localhost 웹 UI  
실행일: 2026-07-11

| # | 항목 | 상태 | 수동 확인 메모 |
|---:|---|---|---|
| 1 | 실제 시스템 음성으로 세션 시작 | SKIP | 실제 회의 오디오 수동 실행 필요 |
| 2 | 일본어 final 저장 | SKIP | 실제 일본어 오디오 수동 실행 필요 |
| 3 | 영어 final 저장 | SKIP | 실제 영어 오디오 수동 실행 필요 |
| 4 | 번역 성공·실패가 섞인 세션 | SKIP | 실제 Provider 연결 수동 실행 필요 |
| 5 | pause/resume 후 세션 연속성 | SKIP | 실제 캡처 중 수동 실행 필요 |
| 6 | stop 후 finalize | SKIP | 실제 캡처 중 수동 실행 필요 |
| 7 | 브라우저 새로고침 후 세션 복원 | MANUAL PASS | 합성 4-segment 세션과 저장 분석을 새로고침 후 복원 |
| 8 | 서버 재시작 후 세션 목록 | MANUAL PASS | Uvicorn PID를 교체한 뒤 같은 세션·분석을 다시 조회 |
| 9 | 전체 원문 복사 | MANUAL PASS | 4개 원문이 줄바꿈 포함 Clipboard에 일치; timeout fallback도 해제됨 |
| 10 | 전체 번역 복사 | SKIP | 브라우저 Clipboard 권한 수동 확인 필요 |
| 11 | JSON 다운로드 | SKIP | 브라우저 다운로드 수동 확인 필요 |
| 12 | 원문 TXT 다운로드 | SKIP | 브라우저 다운로드 수동 확인 필요 |
| 13 | 번역 TXT 다운로드 | SKIP | 브라우저 다운로드 수동 확인 필요 |
| 14 | Markdown 다운로드 | SKIP | 브라우저 다운로드 수동 확인 필요 |
| 15 | Markdown 내용과 UI 비교 | SKIP | 분석 결과 생성 후 수동 비교 필요 |
| 16 | 규칙 기반 분석 | MANUAL PASS | 합성 영문/일문 4개로 결정 1, Action 1, 질문 2 생성 |
| 17 | Action Item 담당자 미정 처리 | SKIP | 최종 브라우저 검증 후 갱신 |
| 18 | Action Item 기한 미정 처리 | SKIP | 최종 브라우저 검증 후 갱신 |
| 19 | 결정사항과 논의 구분 | SKIP | 최종 브라우저 검증 후 갱신 |
| 20 | 질문사항 추출 | MANUAL PASS | `Who owns the Operation Test report?`가 미해결 질문에 표시됨 |
| 21 | evidence 클릭 후 segment 이동 | MANUAL PASS | `seg-browser-002` 근거 클릭 후 정확한 카드로 focus 이동 |
| 22 | OpenAI 키 없이 분석 기능 | MANUAL PASS | OpenAI는 사용 불가로 표시되고 적용 버튼 비활성; 로컬 규칙 분석은 정상 |
| 23 | OpenAI 분석 선택 시 외부 전송 경고 | MANUAL PASS | 비용·외부 전송·회사 정책·회의 참가자 동의 문구 표시 확인 |
| 24 | 잘못된 OpenAI 키 | SKIP | 불필요한 외부 요청을 피하기 위해 미실행 |
| 25 | 네트워크 차단 중 분석 실패 | SKIP | 네트워크 상태 변경 없이 미실행 |
| 26 | 분석 실패 후 원문·번역 유지 | SKIP | 최종 브라우저 검증 후 갱신 |
| 27 | 분석 취소 | SKIP | 지연 공급자 수동 환경 필요 |
| 28 | 분석 재시도 | SKIP | 실패 공급자 수동 환경 필요 |
| 29 | 20개 이상 segment 세션 | SKIP | synthetic 자동 테스트와 별개로 수동 미실행 |
| 30 | 30~60분 비민감 장시간 세션 | SKIP | 장시간 실제 실행 미수행 |
| 31 | 비정상 종료 후 복구 | SKIP | 강제 종료 수동 실행 미수행 |
| 32 | 손상된 JSONL 한 줄 복구 | SKIP | 자동 테스트와 별개로 수동 미실행 |
| 33 | 모바일 크기 UI | MANUAL PASS | 390×844 override(실제 client 375px)에서 수평 overflow 없음 |
| 34 | `stop_all.bat` 후 PID 정리 | SKIP | 최종 프로세스 검증 후 갱신 |

## 안전 확인

- 실제 회사 회의 내용 대신 합성·비민감 데이터만 사용한다.
- 실제 OpenAI 분석은 `OPENAI_API_KEY`, `RUN_OPENAI_ANALYSIS_LIVE_TEST=1`, `OPENAI_ANALYSIS_MODEL` 세 조건이 모두 있을 때만 수행한다.
- 미수행 항목은 PASS로 기록하지 않는다.
