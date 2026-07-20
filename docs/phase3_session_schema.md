# Phase 3A 세션 저장 스키마

이 문서는 Phase 3A의 세션 lifecycle, append-only 이벤트, 완성 세션 및 내보내기
형식을 정의한다. 회의 분석 구조와 분석 생성 규칙은 Phase 3B의 별도 스키마 대상이며,
여기서는 `analysis: null`과 분석 저장 설정만 예약한다.

## 1. 기본 원칙

- 현재 스키마 버전은 정수 `1`이다.
- 회의 중에는 이벤트를 JSONL에 append만 한다.
- finalize는 이벤트 원본을 수정하지 않고 완성본을 새로 만든다.
- 원문과 번역은 `segment_id`로 결합한다.
- partial transcript, API 키, 인증 헤더, `.env`, raw Provider 요청·응답, traceback,
  내부 절대 경로와 오디오는 저장하지 않는다.
- 모든 저장 시각은 timezone을 포함한 ISO 8601 문자열이다.
- 알 수 없는 값을 추측하지 않는다. 특히 복구 세션의 `ended_at`은 추정하지 않고
  `null`로 유지할 수 있다.

## 2. `schema_version` 정책

`manifest.json`, `session.json`과 향후 `analysis.json`은 최상위
`schema_version`을 반드시 가진다. `events.jsonl`의 Phase 3 행도
`schema_version: 1`을 권장하지만, Phase 1·2 호환 행에는 없어도 된다.

읽기 정책은 다음과 같다.

1. 버전이 없고 기존 final/translation 모양과 일치하면 legacy version 0 입력으로
   정규화해 읽는다.
2. 버전 1은 현재 reader로 읽는다. 알 수 없는 추가 필드는 보존 가능한 범위에서
   무시한다.
3. 현재보다 큰 버전은 자동 변환하거나 덮어쓰지 않는다. 목록에는
   `unsupported_schema` 경고와 함께 표시할 수 있지만 finalize/recovery 쓰기는
   거부한다.
4. 스키마 변경 시 기존 파일을 제자리 수정하지 않는다. 필요한 migration은 원본을
   유지한 채 새 완성본으로 작성한다.

## 3. 세션 ID와 디렉터리

새 세션 ID 권장 형식은 다음과 같다.

```text
2026-07-11_14-30-15_ab12cd
```

기존 UUID도 유효한 legacy 세션 ID다.

```text
4322cb3e-66e7-4e36-ad1a-aa85da3feba6
```

허용 형식은 위 두 형식으로 제한하고 길이는 64자 이하로 한다. `/`, `\`, `..`,
제어 문자, 절대 경로, 드라이브 접두사와 Windows 예약 파일명은 거부한다. API는
사용자가 전달한 경로를 받지 않고 검증된 `session_id`만 받는다.

새 레이아웃:

```text
data/sessions/<session_id>/
  manifest.json
  events.jsonl
  session.json
  transcript_original.txt
  transcript_korean.txt
  meeting_report.md
```

`analysis.json`은 Phase 3B가 실제 분석을 저장할 때만 생성한다. 오디오 파일은
Phase 3에서 생성하지 않는다.

## 4. 세션 lifecycle

상태 값:

```text
created → running ↔ paused → stopping → finalizing → completed
                                      ↘ recovered
어느 상태에서든 복구 불가능한 저장 오류 → error
```

- `created`: 디렉터리와 초기 manifest가 준비됨.
- `running`: 캡처와 전사가 진행 중.
- `paused`: 캡처가 일시정지되었으나 같은 세션을 유지.
- `stopping`: 마지막 final/translation 작업을 정리 중.
- `finalizing`: append-only 로그를 완성 세션으로 조립 중.
- `completed`: 정상 finalize 완료.
- `recovered`: 비정상 종료 로그로 완성본을 재구성함.
- `error`: 해당 세션 저장 또는 복구를 안전하게 완료하지 못함.

캡처 상태와 세션 상태는 별개다. 캡처가 중지되어도 finalize가 끝나기 전에는 세션을
`completed`로 표시하지 않는다. 동일 이벤트로 finalize를 반복해도 같은 segment
구조가 생성되어야 하며 JSONL 행을 다시 추가하지 않는다.

## 5. `manifest.json`

필수 및 표준 필드:

| 필드 | 형식 | 규칙 |
|---|---|---|
| `schema_version` | integer | 현재 `1` |
| `session_id` | string | 검증된 세션 ID |
| `status` | string | 위 lifecycle 값 중 하나 |
| `created_at` | ISO 8601 | 세션 생성 시각 |
| `started_at` | ISO 8601/null | 실제 캡처 시작 시각 |
| `ended_at` | ISO 8601/null | 확인된 종료 시각만 기록 |
| `finalized_at` | ISO 8601/null | 마지막 성공 finalize 시각 |
| `source` | string/null | `system` 또는 `microphone` |
| `audio_device_name` | string/null | 공개 가능한 장치 표시명, 내부 경로 금지 |
| `whisper_model` | string/null | 전사 모델 |
| `translation_provider` | string | `none`, `local`, `openai` 등 |
| `analysis_provider` | string | Phase 3A 기본 `none` |
| `save_original` | boolean | 세션 생성 시 확정한 원문 저장 정책 |
| `save_translation` | boolean | 번역 저장 정책 |
| `save_analysis` | boolean | 향후 분석 저장 정책 |
| `save_audio` | boolean | 항상 `false` |
| `segment_count` | integer | 완성본 segment 수 |
| `translated_segment_count` | integer | 성공 번역 수 |
| `analysis_status` | string | Phase 3A에서는 `not_started` |
| `warnings` | array[string] | 복구·손상 행 등 안전한 경고 코드/요약 |

예시:

```json
{
  "schema_version": 1,
  "session_id": "2026-07-11_14-30-15_ab12cd",
  "status": "completed",
  "created_at": "2026-07-11T14:30:15+09:00",
  "started_at": "2026-07-11T14:30:20+09:00",
  "ended_at": "2026-07-11T15:25:12+09:00",
  "finalized_at": "2026-07-11T15:25:14+09:00",
  "source": "system",
  "audio_device_name": "Speakers",
  "whisper_model": "small",
  "translation_provider": "openai",
  "analysis_provider": "none",
  "save_original": true,
  "save_translation": true,
  "save_analysis": true,
  "save_audio": false,
  "segment_count": 42,
  "translated_segment_count": 39,
  "analysis_status": "not_started",
  "warnings": []
}
```

비밀 값, 내부 절대 경로, raw 오류와 원문 전체는 manifest에 넣지 않는다.

## 6. `events.jsonl`

UTF-8이며 한 행이 독립 JSON 객체다. 행 순서는 원본 event 순서다. 새 이벤트는
append만 하고 기존 행을 수정하거나 재정렬하지 않는다.

### 6.1 Final transcript

Phase 3 표준 행:

```json
{
  "schema_version": 1,
  "type": "final_transcript",
  "event_index": 12,
  "session_id": "2026-07-11_14-30-15_ab12cd",
  "segment_id": "seg-001",
  "utterance_id": "utterance-001",
  "source": "system",
  "text": "次のSystem Testは来週実施します。",
  "language": "ja",
  "language_probability": 0.96,
  "started_at": "2026-07-11T14:31:01+09:00",
  "ended_at": "2026-07-11T14:31:04+09:00",
  "inference_seconds": 0.72
}
```

`event_index`는 새 로그에서 단조 증가하는 선택 필드다. legacy 로그는 실제 파일의
행 순서를 event 순서로 사용한다.

### 6.2 Translation

```json
{
  "schema_version": 1,
  "type": "translation",
  "event_index": 13,
  "session_id": "2026-07-11_14-30-15_ab12cd",
  "segment_id": "seg-001",
  "source_language": "ja",
  "target_language": "ko",
  "translated_text": "다음 System Test는 다음 주에 실시합니다.",
  "provider": "openai",
  "model": "configured-model",
  "latency_ms": 780,
  "timestamp": "2026-07-11T14:31:05+09:00"
}
```

번역 오류를 디스크에 남기는 구현은 `type: translation_error`, `segment_id`, 안전한
오류 코드, recoverable 여부와 timestamp만 저장한다. raw exception, 원문 사본,
API 요청/응답은 저장하지 않는다.

동일 segment에 여러 번역 이벤트가 있으면 event 순서상 가장 최신 성공을 사용한다.
성공이 하나도 없고 오류만 있으면 최신 안전한 오류를 `failed` 상태로 유지한다.
이전 성공 뒤 재번역 오류가 있으면 이전 성공 번역을 유지하고 경고/마지막 시도 상태만
별도로 표시한다.

### 6.3 저장 OFF용 marker

원문 저장이 OFF일 때 구현상 순서와 segment 연결 정보가 필요하면 다음처럼 텍스트가
없는 marker만 기록할 수 있다.

```json
{
  "schema_version": 1,
  "type": "segment_marker",
  "segment_id": "seg-001",
  "source": "system",
  "started_at": "2026-07-11T14:31:01+09:00",
  "ended_at": "2026-07-11T14:31:04+09:00",
  "original_saved": false
}
```

marker에 `text` 또는 그 변형을 넣으면 안 된다. marker를 사용하지 않는 구현에서는
번역 이벤트가 복구 시 orphan이 될 수 있으며 이를 경고로 기록하고 원문을 만들어내지
않는다.

## 7. 기존 Phase 1·2 `<UUID>.jsonl` 호환

현재 프로젝트의 기존 파일은 다음처럼 루트에 있다.

```text
data/sessions/4322cb3e-66e7-4e36-ad1a-aa85da3feba6.jsonl
```

호환 규칙:

1. 파일명 UUID를 `session_id`로 사용한다.
2. `type`이 없고 `segment_id`, `text`, `started_at`, `ended_at`이 있으면
   `final_transcript`로 정규화한다.
3. `type: translation` 행은 Phase 2 whitelist 필드를 그대로 읽는다.
4. 원본 `<UUID>.jsonl`을 이동, 개명, 삭제, truncate 또는 제자리 변환하지 않는다.
5. finalize 산출물이 필요하면 `data/sessions/<UUID>/`에 새 manifest와 완성본을
   atomic하게 만들되, 원본 JSONL은 authoritative append log로 보존한다.
6. legacy에 없는 manifest 값은 `null`, 기본 저장 정책 또는 `legacy_import` 경고로
   표현하고 추측하지 않는다.
7. 기존 파일 일부가 손상되어도 다른 세션 목록 조회를 계속한다.

복사 migration을 제공하더라도 명시적 사용자 작업이어야 하며 원본은 보존한다.

## 8. `session.json`

완성 세션은 다음 구조다.

```json
{
  "schema_version": 1,
  "session_id": "2026-07-11_14-30-15_ab12cd",
  "metadata": {
    "status": "completed",
    "started_at": "2026-07-11T14:30:20+09:00",
    "ended_at": "2026-07-11T15:25:12+09:00",
    "source": "system",
    "whisper_model": "small",
    "translation_provider": "openai",
    "save_original": true,
    "save_translation": true
  },
  "segments": [
    {
      "segment_id": "seg-001",
      "source": "system",
      "language": "ja",
      "language_probability": 0.96,
      "original_text": "次のSystem Testは来週実施します。",
      "original_saved": true,
      "korean_translation": "다음 System Test는 다음 주에 실시합니다.",
      "translation_status": "success",
      "translation_provider": "openai",
      "translation_model": "configured-model",
      "translation_latency_ms": 780,
      "translation_error_code": null,
      "started_at": "2026-07-11T14:31:01+09:00",
      "ended_at": "2026-07-11T14:31:04+09:00",
      "event_index": 12
    }
  ],
  "analysis": null,
  "warnings": []
}
```

`translation_status` 표준 값은 `success`, `failed`, `not_requested`, `missing`이다.
번역이 없거나 실패해도 원문 segment는 제거하지 않는다. 분석을 실행하지 않았으므로
Phase 3A에서는 임의 분석을 만들지 않고 `analysis: null`로 둔다.

segment 정렬 키:

1. 유효한 `started_at`
2. 유효한 `ended_at`
3. 원본 event 순서(`event_index` 또는 JSONL 행 번호)
4. `segment_id`

번역 완료 시각으로 segment를 재정렬하지 않는다.

## 9. 내보내기 규칙

- JSON 다운로드는 위 `session.json`의 공개 구조를 사용한다.
- 원문 TXT는 저장된 원문 segment만 시간 순서로 기록한다.
- 한국어 TXT는 성공 번역만 기록하고 상단에 전체/성공/미번역·실패 수를 표시한다.
  번역이 없을 때 원문을 가짜 번역으로 대신 넣지 않는다.
- Markdown은 기본 정보와 전체 회의 기록을 포함한다. 분석이 없으면 모든 분석 절에
  `분석이 아직 생성되지 않았습니다.`라고 명시하고 분석을 추측하지 않는다.
- Markdown에 내부 절대 경로, traceback 또는 비밀 값을 넣지 않는다.
- 다운로드 파일명은 검증된 session ID와 고정 ASCII suffix로 서버가 생성한다.

## 10. 저장 설정 OFF 정책

설정은 세션 생성 시 snapshot해 manifest에 고정한다. 실행 중 설정 변경은 다음
세션부터 적용하는 것을 기본으로 한다.

| 설정 | OFF일 때 디스크 정책 |
|---|---|
| `save_original` | final 원문 `text`를 JSONL, session JSON, TXT, Markdown 어디에도 쓰지 않음 |
| `save_translation` | 번역문을 JSONL, session JSON, TXT, Markdown 어디에도 쓰지 않음 |
| `save_analysis` | 향후 분석 결과를 저장·내보내지 않음 |
| `save_audio` | 항상 OFF이며 오디오 파일을 생성하지 않음 |

OFF여도 실시간 UI를 위한 메모리 데이터는 세션 실행 중 사용할 수 있다. 그러나
finalize 산출물에도 해당 내용을 기록하지 않으며 앱 종료 후 복구할 수 없음을 UI에서
안내한다. 최소 manifest에는 lifecycle, 비내용 메타데이터와 OFF flags를 남길 수 있다.
모든 내용 저장이 OFF여도 API 키나 원문 hash/preview처럼 내용을 유추할 값을 대신
저장하지 않는다.

`save_original=false, save_translation=true` 조합은 허용한다. marker가 있으면
`original_text: null`, `original_saved: false`인 segment에 번역을 연결할 수 있다.
marker가 없는 비정상 종료 복구에서는 orphan translation을 경고로 남기되 원문이나
시간을 추측하지 않는다. `save_translation=false`이면 메모리에 번역이 있더라도 완성
파일이나 Markdown에 포함하지 않는다.

## 11. 손상 행과 복구

JSONL reader는 행 단위로 독립 처리한다.

- 빈 행은 무시한다.
- JSON 문법 오류, 객체가 아닌 JSON, 필수 ID 누락 행은 건너뛴다.
- 경고에는 논리적 세션 ID, 파일 종류, 1-based 행 번호와 안전한 오류 종류만 기록한다.
  원문 전체, raw exception, 내부 절대 경로는 API 경고에 넣지 않는다.
- 한 행의 손상 때문에 나머지 행이나 다른 세션을 포기하지 않는다.

서버 시작 시 `running`, `stopping`, `finalizing`, manifest만 있고 `session.json`이 없는
세션, 또는 legacy JSONL만 있는 세션을 검사할 수 있다. 복구 절차:

1. 원본 이벤트를 읽기 전용으로 스캔한다.
2. 확인된 final과 translation만 `segment_id`로 결합한다.
3. 새 원문, 번역, 종료 시각 또는 분석을 생성하지 않는다.
4. 안전한 새 완성본을 atomic write한다.
5. manifest 상태를 `recovered`로 쓰고 recovery 시각과 경고를 남긴다.
6. 원본 JSONL을 그대로 보존한다.

현재보다 새로운 스키마, 안전하지 않은 ID 또는 읽을 수 없는 manifest는 자동 복구하지
않고 해당 세션만 `error`/경고로 격리한다.

## 12. Atomic write와 장애 정책

`events.jsonl`은 append-only이므로 atomic replace 대상이 아니다. 한 이벤트는 한 번의
UTF-8 행 append로 기록하고 flush/close 후 성공으로 간주한다.

`manifest.json`, `session.json`, TXT와 Markdown 완성본은 다음 절차를 사용한다.

1. 대상과 같은 디렉터리에 충돌하지 않는 임시 파일을 만든다.
2. UTF-8 전체 내용을 쓰고 flush한다. 가능한 환경에서는 `fsync`한다.
3. JSON은 다시 parse 가능함을 확인할 수 있다.
4. `os.replace(temp, target)`로 원자 교체한다.
5. 실패 시 임시 파일만 정리하고 이전 정상 target과 JSONL을 유지한다.

manifest 상태 변경도 동일한 atomic write를 사용한다. finalize 중 한 exporter가
실패하면 JSONL을 변경하지 않고 manifest에 안전한 경고 또는 `error` 상태를 기록한다.
서버 프로세스 전체와 실시간 전사·번역은 계속 동작해야 한다.

## 13. 개인정보 및 공개 응답

세션 목록과 API 응답에는 session ID, 공개 metadata, counts, 상태와 안전한 warnings만
포함한다. 다음 값은 모든 세션 파일·다운로드·API·WebSocket에서 금지한다.

```text
API key / Authorization header / .env 전체 / raw Provider exception
Python traceback / 내부 절대 경로 / OpenAI 전체 요청·응답 / 오디오 원본
```

세션 데이터 삭제는 별도 명시적 사용자 작업이며 repository가 과거 세션을 자동 삭제,
rename 또는 migration하지 않는다.
