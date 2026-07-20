# Meeting Live Translator 실제 번역 검증 및 Local Translation PoC 보고서

- 검증일: 2026-07-12 (Asia/Seoul)
- 범위: Phase 1·2·3 기반 실제 번역 검증과 M2M100 Local Translation PoC
- Phase 4: **시작하지 않음**
- PoC 실행 결과: **PASS** — 로컬 모델 설치·단독 번역·실제 Windows 시스템 음성 20문장·브라우저 표시까지 완료
- OpenAI 실제 호출: **SKIP** — 명시적 환경변수 3개가 모두 미설정
- 최종 채택 권고: **성능 조정 후 재검증 필요**

## 1. 기존 기준선

**PASS**

작업 전 요구 문서 `docs/phase2_report.md`, `docs/phase2_local_translation_evaluation.md`, `docs/phase3_report.md`, `README_KO.md`를 전부 읽었다. 프로젝트는 Git 저장소가 아니므로 기존 파일 SHA-256을 기준선으로 고정했다.

작업 전 필수 명령 결과:

```text
pytest: 187 passed, 3 skipped in 2.47s
compileall backend: PASS
pip check: No broken requirements found
```

작업 후 전체 회귀 결과:

```text
pytest: 190 passed, 3 skipped in 2.43s
compileall backend scripts: PASS
JavaScript syntax: PASS
main/build/runtime pip check: 모두 PASS
```

추가된 3개 PASS는 실제 M2M100 출력에서 발견한 glossary marker 변형 회귀 테스트다. 3개 SKIP은 OpenAI 분석, OpenAI 번역, 기존 메인 `.venv` 기반 로컬 번역 opt-in 테스트이며, 이번 PoC의 격리 worker 실사용 결과와는 별개다.

보호 대상은 최종 검증에서도 모두 동일했다.

| 보호 대상 | 최종 상태 |
|---|---|
| 기존 UUID JSONL 6개 | SHA-256 6/6 동일 |
| `docs/phase2_report.md` | `fb2556…768e` 동일 |
| `docs/phase2_local_translation_evaluation.md` | `175c61…ce8` 동일 |
| `docs/phase3_report.md` | `794644…9a06` 동일 |
| `README_KO.md` | `fefe28…96fb` 동일 |
| `.env.example`, glossary 예제 | SHA-256 동일 |
| 프로젝트 `.env` | 작업 전·후 모두 없음 |
| 메인 `.venv`의 Torch/Transformers | 작업 전·후 모두 미설치 |

기존 `data/sessions`에는 파일을 만들거나 수정하지 않았다. 실제 오디오 PoC 세션은 `work/translation-poc/live/sessions`에만 격리했다.

## 2. OpenAI 준비 상태

**PASS — 설정 여부 판정 완료**

키 값은 읽거나 출력하지 않고 존재 여부만 확인했다.

| 항목 | 프로세스 환경 | 프로젝트 `.env` | 유효 상태 |
|---|---:|---:|---:|
| `OPENAI_API_KEY` | 미설정 | 파일 없음 | 미설정 |
| `OPENAI_TRANSLATION_MODEL` | 미설정 | 파일 없음 | 미설정 |
| `RUN_OPENAI_LIVE_TEST` | 미설정 | 파일 없음 | 미설정 |

메인 `.venv`에는 공식 OpenAI Python SDK가 있고, 기존 Provider는 Responses API를 사용한다. 공식 문서 기준으로 SDK는 환경변수의 API 키를 읽고 `responses.create`로 텍스트 응답을 생성할 수 있다: [OpenAI Developer quickstart](https://developers.openai.com/api/docs/quickstart), [Text generation](https://developers.openai.com/api/docs/guides/text).

실제 테스트를 명시적으로 허용하려면 사용자가 직접 다음 값을 설정해야 한다.

```text
OPENAI_API_KEY=<사용자 키>
OPENAI_TRANSLATION_MODEL=<사용할 모델>
RUN_OPENAI_LIVE_TEST=1
```

## 3. OpenAI 실제 테스트 여부

**SKIP**

세 조건이 모두 설정되지 않아 실제 API 요청을 보내지 않았다. 과금, 외부 원문 전송, API 응답 저장은 발생하지 않았다. API 키, Authorization 헤더, 전체 요청 객체도 어느 산출물에도 기록하지 않았다.

따라서 일본어 3문장·영어 3문장의 실제 OpenAI 번역, 요청 시작/완료 시각, 모델별 지연, 품질 비교는 모두 `SKIP`이다. 이 결과를 PASS로 대체하지 않는다.

## 4. 로컬 환경 구성

**PASS**

기존 faster-whisper `.venv`를 변경하지 않고 두 환경을 새로 만들었다.

| 환경 | Python | 용도 | Torch | 논리 크기 |
|---|---|---|---:|---:|
| `.venv-translation-build` | 3.11.9 | 고정 snapshot 다운로드와 CT2 변환 | CPU 전용 설치 | 0.847 GiB |
| `.venv-translation` | 3.11.9 | 격리된 tokenizer·CT2 worker 실행 | 미설치 | 0.266 GiB |
| 기존 `.venv` | 3.11.9 | FastAPI, 오디오, faster-whisper | 미설치 유지 | 변경 없음 |

`models/`와 `.venv-translation*/`는 기존 `.gitignore`에서 이미 제외되어 있다. 실제 앱 동시 테스트는 메인 `.venv`의 오디오·Whisper 프로세스가 `.venv-translation` JSONL worker를 호출하는 PoC 전용 subprocess Provider를 사용했다. 표준 `start_all.bat`의 제품 Provider를 sidecar 구조로 전환하지 않았고 새 UI 기능도 만들지 않았다.

## 5. 설치한 패키지

**PASS**

직접 고정한 핵심 버전:

| 패키지 | build | runtime | 기존 `.venv` |
|---|---:|---:|---:|
| torch | `2.13.0+cpu` | 미설치 | 미설치 |
| ctranslate2 | `4.8.1` | `4.8.1` | 기존 `4.8.1` |
| transformers | `4.57.6` | `4.57.6` | 미설치 |
| sentencepiece | `0.2.1` | `0.2.1` | 미설치 |
| huggingface-hub | `0.36.2` | `0.36.2` | 미설치 |
| tokenizers | `0.22.2` | `0.22.2` | 미설치 |
| sacremoses | `0.1.1` | `0.1.1` | 미설치 |
| psutil | `7.0.0` | `7.0.0` | 미설치 |

빌드 환경 전체 freeze:

```text
certifi==2026.6.17, charset-normalizer==3.4.9, click==8.4.2,
colorama==0.4.6, ctranslate2==4.8.1, filelock==3.29.0,
fsspec==2026.4.0, huggingface_hub==0.36.2, idna==3.18,
Jinja2==3.1.6, joblib==1.5.3, MarkupSafe==3.0.3, mpmath==1.3.0,
networkx==3.6.1, numpy==2.4.6, packaging==26.2, psutil==7.0.0,
PyYAML==6.0.3, regex==2026.7.10, requests==2.34.2,
sacremoses==0.1.1, safetensors==0.8.0, sentencepiece==0.2.1,
sympy==1.14.0, tokenizers==0.22.2, torch==2.13.0+cpu,
tqdm==4.68.4, transformers==4.57.6, typing_extensions==4.15.0,
urllib3==2.7.0
```

runtime은 위 목록에서 Torch/Jinja2/MarkupSafe/mpmath/networkx/sympy를 제외하며, `filelock==3.29.7`, `fsspec==2026.6.0`, `typing_extensions==4.16.0`이다. 세 환경 모두 `pip check`를 통과했다.

## 6. 다운로드한 모델과 revision

**PASS**

- 모델: `facebook/m2m100_418M`
- 고정 commit: `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636`
- 원본 위치: `models/translation/source/m2m100_418M-55c2e61`
- 공식 전체 저장소: 3,877,717,593 bytes (3.611 GiB)
- 실제 다운로드: 8개, 1,941,935,615 bytes (1.809 GiB)
- 제외: `rust_model.ot` 1,935,781,288 bytes, 다른 후보 모델, NLLB 전부

| 파일 | bytes | 확인 |
|---|---:|---|
| `pytorch_model.bin` | 1,935,796,948 | SHA-256 `d907ea45…e87ed1` 공식 LFS 값 일치 |
| `sentencepiece.bpe.model` | 2,423,393 | SHA-256 `d8f7c76e…4d380a` 공식 LFS 값 일치 |
| `vocab.json` | 3,708,092 | tokenizer 필수 |
| `config.json` | 908 | 변환 필수 |
| `tokenizer_config.json` | 298 | runtime |
| `special_tokens_map.json` | 1,140 | runtime |
| `generation_config.json` | 233 | 메타데이터 |
| `README.md` | 4,603 | 모델 카드·출처 보존 |

고정 revision의 [공식 파일 트리](https://huggingface.co/facebook/m2m100_418M/tree/55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636)만 사용했다. 다운로드·변환 provenance JSON도 원본과 변환 폴더에 남겼다.

## 7. 모델 라이선스

**PASS — 내부 PoC 사용**, **MANUAL REVIEW REQUIRED — 재배포**

Hugging Face 모델 카드 metadata의 라이선스는 `MIT`다: [고정 revision 모델 카드](https://huggingface.co/facebook/m2m100_418M/blob/55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636/README.md). 저장소에는 독립 `LICENSE` 파일이 없어 모델 카드와 원 Fairseq의 [MIT 라이선스](https://github.com/facebookresearch/fairseq/blob/main/LICENSE)를 provenance에서 함께 참조했다.

사내 배포나 변환본 재배포 전에는 법무·오픈소스 정책 담당자가 고지문과 배포 방식에 필요한 조건을 직접 확인해야 한다.

## 8. CT2 변환 결과

**PASS**

- 출력: `models/translation/m2m100_418m-int8`
- 변환: CTranslate2 4.8.1, `int8`, CPU
- 변환 산출물: 499,725,763 bytes (0.465 GiB, provenance 제외)
- `model.bin`: 490,667,752 bytes
- `model.bin` SHA-256: `590e9c7e229e84de8affe7b15487660a286d3d76e44a4ca10e33099b198d9a76`
- 필수 파일: `model.bin`, CT2 `config.json`, `shared_vocabulary.json`, `sentencepiece.bpe.model`, `vocab.json` 모두 확인
- `tokenizer_config.json`, `special_tokens_map.json`, `generation_config.json` 포함

적용한 보수적 runtime:

```text
device=cpu
compute_type=int8
inter_threads=1
intra_threads=2
translation concurrency=1
beam_size=1
worker process priority=BelowNormal
```

공식 M2M100 변환/target prefix 방식과 CT2 API를 따랐다: [M2M-100 guide](https://opennmt.net/CTranslate2/guides/transformers.html#m2m-100), [Translator API](https://opennmt.net/CTranslate2/python/ctranslate2.Translator.html), [INT8 quantization](https://opennmt.net/CTranslate2/quantization.html).

기존 Provider의 `beam_size=4`, thread 미지정, 불완전 모델 가용 판정도 이번 범위에서 `beam=1`, `inter=1`, `intra=2`, 실제 필수 파일 확인으로 좁게 수정했다.

## 9. 일본어 단독 번역 결과

**PASS — 실행·용어/날짜/부정 보존**, **MANUAL REVIEW REQUIRED — 자연스러움**

- worker cold start: 2,137.385ms
- warm 지연: min 125.035ms, median 248.028ms, p95/max 340.162ms
- worker 시작 RSS: 605.43 MiB

| 원문 | 한국어 번역 | ms | 용어 | 평가 |
|---|---|---:|---|---|
| 次のSystem Testは来週実施する予定です。 | 다음 System Test은 다음 주에 실행될 예정입니다. | 248.028 | 보존 | 수정 필요 — `System Test은` 조사 부자연스러움 |
| SoftBankにFit & Gapの結果を共有してください。 | SoftBank에 Fit & Gap의 결과를 공유하십시오. | 340.162 | 보존 | 좋음 |
| BMSとRMSのインターフェースを確認します。 | BMS 및 RMS의 인터페이스를 확인합니다. | 327.045 | 보존 | 좋음 |
| 担当者はまだ決まっていません。 | 책임자는 아직 결정되지 않았다. | 125.035 | 해당 없음 | 사용 가능 — 미정·부정 보존 |
| 詳細設計書を金曜日までに送ってください。 | 금요일까지 자세한 내용을 보내 주시기 바랍니다. | 153.705 | 해당 없음 | 수정 필요 — `상세설계서`가 `자세한 내용`으로 약화 |

첫 실행에서 SentencePiece가 일본어 문맥의 `__MLT_TERM_0__`를 `_MLT_TERM_0__`로 바꿔 glossary 복원이 실패했다. 주입한 marker에 한해서 밑줄 축약·공백을 허용하도록 복원 규칙을 고쳤고 동일 문장을 다시 실행해 5/5 용어 검사를 통과했다.

## 10. 영어 단독 번역 결과

**PASS — 실행·용어/날짜/부정 보존**, **MANUAL REVIEW REQUIRED — 자연스러움**

- warm 지연: min 171.564ms, median 274.811ms, p95/max 298.749ms

| 원문 | 한국어 번역 | ms | 용어 | 평가 |
|---|---|---:|---|---|
| Please confirm the BMS interface requirements by Friday. | 금요일까지 BMS 인터페이스 요구 사항을 확인하시기 바랍니다. | 263.997 | 보존 | 좋음 |
| The Detailed Design document will be shared with Fuji IT. | Detailed Design 문서는 Fuji IT와 공유됩니다. | 274.811 | 보존 | 좋음 |
| We need to review the MK119 System Test results. | 우리는 MK119 System Test 결과를 검토해야합니다. | 298.749 | 보존 | 사용 가능 — 띄어쓰기 수정 권장 |
| The person in charge has not been decided yet. | 책임자에 대한 결정은 아직 이루어지지 않았다. | 171.564 | 해당 없음 | 사용 가능 — 미정·부정 보존 |
| ONION Technology will check the DC OS configuration. | ONION Technology는 DC OS 구성을 확인합니다. | 297.406 | 보존 | 좋음 |

숫자 `MK119`, 회사명, IT 용어, Friday 의미와 부정 표현은 보존됐다. 모델이 새 정보를 추가한 사례는 찾지 못했다.

## 11. Whisper 동시 실행 결과

**PASS — 20/20 end-to-end 실행**, **FAIL — 목표 2~4초를 일관되게 충족**

실제 Windows 기본 출력 `Speaker(Realtek Speaker) [Loopback]`을 열고 설치된 SAPI 음성 `Microsoft Haruka Desktop`(ja-JP), `Microsoft Zira Desktop`(en-US)으로 일본어 10개와 영어 10개를 번갈아 재생했다. `small` faster-whisper CPU `int8` → bounded queue → 격리 M2M100 worker → WebSocket → 실제 브라우저 DOM 순서로 측정했다.

```text
발화 20/20 재생
Whisper final 20/20
로컬 번역 20/20
브라우저 번역 표시 20/20
오디오 frame drop 0
브라우저 console error 0
error overlay 없음
```

| 구간 | min | median | p95 | max |
|---|---:|---:|---:|---:|
| 음성 종료→final | 3.205s | 4.497s | 5.697s | 6.296s |
| final→queue 등록 | 0.000s | 0.001s | 0.001s | 0.001s |
| queue→번역 완료 | 0.110s | 0.579s | 1.682s | 4.761s |
| 음성 종료→번역 이벤트 | 3.719s | 5.196s | 7.093s | 9.679s |
| 음성 종료→브라우저 표시 | 3.719s | 5.196s | 7.093s | 9.678s |

첫 번역의 4.761초에는 worker·tokenizer·model cold start가 들어간다. 이후 19개 warm queue→번역은 median 579.337ms, p95 1,641.510ms, max 1,681.831ms였다.

실제 오디오에서는 Whisper가 용어를 바꾸면 번역기가 원래 spelling을 복원할 수 없었다. 대표 사례는 `Fit & Gap`→`fit end gap`, `DC OS`→`DCOS`, `ONION Technology`→`Onion Technology`, 일본어 음성 속 영문 회사명·설계명이 가타카나 또는 유사음으로 바뀐 경우다.

## 12. OpenAI와 로컬 품질 비교

**OpenAI: SKIP**, **Local: MANUAL REVIEW REQUIRED**

| 평가 항목 | OpenAI | Local 단독 | Local 실제 오디오 pipeline |
|---|---|---|---|
| 의미 보존 | SKIP | 대부분 보존, 일본어 상세설계서 1건 약화 | Whisper 오인식이 있는 문장은 함께 저하 |
| 한국어 자연스러움 | SKIP | 대체로 사용 가능, 조사·띄어쓰기 일부 수정 | 짧은 `Confirmed` 계열과 일본어 장문 일부 부자연스러움 |
| 부정 표현 | SKIP | ja/en 모두 보존 | ja/en 모두 보존 |
| 담당자 미정 | SKIP | ja/en 모두 보존 | ja/en 모두 보존 |
| 날짜·시간 | SKIP | 다음 주·금요일 보존 | 오후 3시 보존 |
| 회사명 | SKIP | exact glossary 보존 | ASR이 변경하면 보존 불가 |
| IT 용어 | SKIP | 10문장 exact 검사 PASS | `Fit & Gap`, `DC OS` 등 ASR 변경 사례 존재 |
| 불필요한 정보 추가 | SKIP | 뚜렷한 사례 없음 | 뚜렷한 사례 없음 |

OpenAI 행은 실제 결과가 없으므로 품질 우열을 추정하지 않는다.

## 13. 지연 비교

**PASS — A/B 측정**, **OpenAI SKIP**

동일 SAPI 20문장, 같은 `small` Whisper, 같은 Loopback으로 별도 fresh server run을 사용했다.

| 모드 | 원문 final median / p95 | 번역 지연 median / p95 | 음성 종료→표시 median / p95 | 품질 |
|---|---:|---:|---:|---|
| OFF | 4.108s / 5.762s | 해당 없음 | 해당 없음 | 원문만 |
| OpenAI | SKIP | SKIP | SKIP | SKIP |
| Local | 4.497s / 5.697s | 0.579s / 1.682s | 5.196s / 7.093s | 수동 검토 필요 |

Local에서 원문 final median은 OFF보다 389.077ms 길었다. run 간 변동 때문에 p95는 Local이 64.696ms 짧았으므로 그 차이를 개선으로 해석하지 않는다. Local browser 표시 median은 final median보다 698.410ms 길었다.

OFF 자체도 2~4초 목표를 median에서 약 0.108초 초과했다. 따라서 전체 지연의 주원인은 CPU `small` Whisper이며, M2M100 warm 번역은 그 뒤 약 0.58초를 추가했다.

## 14. CPU·RAM 사용량

**PASS — 측정 완료**, **MANUAL REVIEW REQUIRED — 다른 부하 환경 일반화**

장비: Intel Core Ultra 7 355, 8 cores/logical processors, RAM 31.54 GiB.

| 항목 | OFF | Local |
|---|---:|---:|
| 서버 normalized CPU median | 41.603% | 40.409% |
| 서버 working set 시작 | 411.80 MiB | 412.89 MiB |
| 서버 working set peak | 566.26 MiB | 549.48 MiB |
| 번역 worker RSS 시작 | 해당 없음 | 608.93 MiB |
| 번역 worker RSS peak | 해당 없음 | 610.18 MiB |
| 서버+worker peak working set 합 | 해당 없음 | 약 1,159.66 MiB |

Local worker의 번역 구간 process CPU는 psutil 기준 median 105.55%, peak 182.8%였다. 이는 `intra_threads=2` 범위와 맞는다. 같은 구간 system CPU 표본은 median/peak 100%였고, system memory 사용률 median 74.45%, peak 75.0%, 최소 available 7.89 GiB였다.

OFF와 Local 서버 CPU 차이는 단일 run 표본 변동 범위로 보인다. 별도 worker가 BelowNormal 우선순위여서 Whisper가 우선됐고 frame drop은 없었지만, 번역 순간 전체 CPU 포화는 실제 업무 부하와 함께 재검증해야 한다.

## 15. 연속 처리와 queue

**PASS**

단독 burst는 20문장을 50ms 간격으로 넣어 실시간 음성보다 가혹하게 시험했다.

```text
20/20 완료
queue max 16 → end 0
전체 drain 4,990.779ms
번역 median 283.658ms, p95 313.682ms
worker RSS 606.13 → 607.11 MiB, peak 609.80 MiB
RSS end-start +0.98 MiB
```

실제 오디오 Local run에서는 250ms 표본의 queue max/end가 모두 0이었다. Whisper final 간격보다 worker 번역이 빨라 대기가 누적되지 않았다. `final→queue`도 p95 약 1ms였다.

stop 뒤 Local worker는 shutdown 응답, exit code 0, `alive_after_shutdown=false`를 확인했다. 마지막 OFF server에서는 worker를 시작하지 않았다. 테스트 종료 후 localhost:8765 listener도 없다.

## 16. 발견한 오류

1. **Glossary marker 변형** — 일본어 M2M100 출력이 marker의 선행 `_` 하나를 제거해 용어가 복원되지 않았다. 실제 출력으로 재현한 뒤, 주입 marker에 한해 안전하게 축약·공백을 허용하고 회귀 테스트 3개를 추가했다.
2. **불완전 모델 오판 가능성** — 기존 health check가 `model.bin`과 SentencePiece만 봤다. CT2 config/shared vocabulary와 `vocab.json`도 필수로 확인하게 수정했다.
3. **요구 runtime 불일치** — 기존 local adapter의 `beam_size=4`, CT2 thread 미지정을 `beam=1`, `inter=1`, `intra=2`로 맞췄다.
4. **첫 오디오 계측 association 오류** — 늦게 도착한 serial final을 다음 발화에 연결해 음수 지연을 만든 첫 계측 결과는 폐기했다. 재생 순서와 final 순서를 매핑하도록 고쳤다.
5. **마지막 VAD flush 순서** — 마지막 final이 stop에서 생성되는데 drain을 먼저 기다리던 PoC 스크립트 교착을 수정했다. 최종 채택 수치는 수정 후 20/20 PASS run만 사용한다.
6. **브라우저 cache** — 표시 시각 계측 JS의 이전 cache가 남은 첫 run을 폐기하고 asset version을 바꿔 20/20 DOM 시각 수집을 확인했다.
7. **품질 결함** — 일본어 `詳細設計書`가 `자세한 내용`으로 약화되고, 짧은 `Confirmed`가 `확인된`, `確認しました`가 `확인한 것 입니다.`가 됐다. 자동 PASS로 처리하지 않았다.

실패·무효 계측은 기존 앱과 사용자 데이터를 수정하지 않았고, 완전 변환되기 전 모델을 사용 가능으로 표시하지 않았다.

## 17. 알려진 제한사항

- 실제 시스템 음성은 Windows SAPI 합성 음성이며 사람의 발음, Zoom codec, Bluetooth, 잡음, 겹침 발화는 미검증이다.
- OpenAI 실호출이 없어 OpenAI 품질·비용·지연 비교는 불가능하다.
- 자연스러움 등급은 1차 수동 검토이며 사용자의 업무 문체 기준 확인이 필요하다.
- 한 번의 장비·부하 조건 결과다. system CPU가 번역 구간에 100%에 도달했으므로 회의 앱과 다른 업무 프로그램을 함께 켠 조건은 별도 검증해야 한다.
- 표준 `start_all.bat`은 여전히 메인 인터프리터에서 기존 `LocalTranslationProvider`를 만든다. 이번 작업은 Transformers를 메인 `.venv`에 설치하지 않았으므로, 설치된 별도 runtime을 제품 기본 경로로 연결하려면 별도 sidecar 통합 승인이 필요하다. 이번 PoC script는 그 경계를 검증했지만 제품 기능으로 전환하지 않았다.
- Whisper가 용어 spelling을 잃으면 downstream glossary만으로 복원할 수 없다. 전사 후 정규화 또는 ASR biasing은 별도 설계가 필요하다.
- 모델 카드에는 MIT metadata가 있지만 독립 LICENSE 파일이 없어 재배포 전 라이선스 검토가 필요하다.
- 모델 원본·변환본·두 환경·work 산출물은 합계 약 3.387 GiB를 사용한다.

## 18. 최종 채택 권고

**성능 조정 후 재검증 필요**

| 채택 기준 | 판정 | 근거 |
|---|---|---|
| 일본어·영어 의미 전달 | 부분 PASS | 대부분 전달되나 상세설계서·짧은 확인 표현 문제 |
| IT 용어 유지 | 단독 PASS / 오디오 부분 FAIL | exact text는 보호, ASR 오인식은 복원 불가 |
| 부정문 보존 | PASS | ja/en 미정·부정 문장 유지 |
| 숫자·날짜 유지 | PASS | MK119, 다음 주, 금요일, 오후 3시 유지 |
| 원문 final 지연 증가 억제 | 부분 FAIL | OFF 4.108s → Local 4.497s median, 목표 2~4초 초과 |
| 번역 지연 허용 가능 | 부분 PASS | warm median 0.579s, cold 4.761s |
| 20문장 queue 비증가 | PASS | 실제 max/end 0, burst 16→0 drain |
| 메모리 비증가 | PASS | burst +0.98 MiB, live worker start보다 end가 낮음 |
| stop 후 worker 정리 | PASS | exit 0, alive false, listener 없음 |

기본 로컬 번역으로 바로 채택하기에는 실제 브라우저 p95 7.09초와 최대 9.68초, ASR 이후 IT 용어 손실, 짧은 문장 품질이 부족하다. 다음 재검증 전 권장 조정은 worker prewarm, Whisper partial/final scheduling 또는 모델 크기 비교, 전사 용어 정규화, 별도 runtime sidecar의 제품 통합이다. 이 작업에서는 그 후속 기능을 구현하지 않았다.

## 19. 사용자가 직접 확인할 번역문

**MANUAL REVIEW REQUIRED**

단독 10문장은 9·10절의 원문/번역 표를 직접 확인해야 한다. 특히 다음을 중점 검토한다.

- `다음 System Test은…`의 조사 허용 여부
- `詳細設計書`가 `자세한 내용`으로 약화된 것이 업무상 허용 가능한지
- `책임자는 아직 결정되지 않았다.`의 문체
- `검토해야합니다` 띄어쓰기와 회의 자막 문체

실제 오디오 pipeline 대표 샘플:

| 계획 문장 | Whisper final | 브라우저 번역 | 검토 |
|---|---|---|---|
| 次のSystem Testは来週実施する予定です。 | 次のシステムテストは来週実施する予定です。 | 다음 시스템 테스트는 다음 주에 진행될 예정입니다. | 좋음, 영문 표기는 ASR에서 일본어화 |
| SoftBankにFit & Gapの結果を共有してください。 | ソフトバンクにフィット&ギアップの結果を共有してください | 소프트뱅크에 해당하는 핀 & 지프 결과를 공유하세요. | 사용 곤란 — 용어 오인식 영향 |
| BMSとRMSのインターフェースを確認します。 | BMSとRMSのインターフェースを確認します | BMS 및 RMS 인터페이스를 확인합니다. | 좋음 |
| 担当者はまだ決まっていません。 | 担当者はまだ決まっていません | 책임자는 아직 결정되지 않았다. | 사용 가능 |
| 詳細設計書を金曜日までに送ってください。 | 詳細設計書を金曜日までに送ってください | 금요일까지 자세한 내용을 보내 주시기 바랍니다. | 수정 필요 |
| Please confirm the BMS interface requirements by Friday. | 동일 | 금요일까지 BMS 인터페이스 요구 사항을 확인하시기 바랍니다. | 좋음 |
| We need to review the MK119 System Test results. | `System Test`가 소문자화 | 우리는 MK119 system test 결과를 검토해야합니다. | 사용 가능 |
| The person in charge has not been decided yet. | 동일 | 책임자에 대한 결정은 아직 이루어지지 않았다. | 사용 가능 |
| Please send the Fit & Gap summary to SoftBank tomorrow. | Please send the fit end gap summary to Softbank tomorrow. | 적합한 끝 간격 요약을 내일 Softbank로 보내 주시기 바랍니다. | 사용 곤란 — ASR가 용어 의미 변경 |
| Confirmed. | Confirmed | 확인된 | 수정 필요 |
| 日本語 장문 Detailed Design/Fuji IT 문장 | 회사·설계명이 일본어 유사음으로 변형 | `FujitIT`, `데이터일드 디자인` 포함 | 사용 곤란 |
| Data CenterのOperation Testは午後三時に開始します。 | データセンターのオペレーションテストは午後3時に開始します | 데이터 센터의 운영 테스트는 오후 3시에 시작됩니다. | 좋음 |

원본 전체 결과는 `work/translation-poc/standalone_results.json`과 `work/translation-poc/live/live_audio_local_results.json`에 남겼다. 두 파일은 비민감 합성 문장만 포함한다.

## 20. 정리 및 제거 방법

현재 성공 산출물은 보존했다. 사용자 세션이나 기존 `data/sessions`는 삭제하지 않았다.

| 경로 | 크기 | 용도 |
|---|---:|---|
| `.venv-translation-build` | 0.847 GiB | 재변환 전용 |
| `.venv-translation` | 0.266 GiB | 격리 runtime |
| `models/translation/source/m2m100_418M-55c2e61` | 1.809 GiB | 고정 원본 snapshot |
| `models/translation/m2m100_418m-int8` | 0.465 GiB | 실제 CT2 모델 |
| `work/translation-poc` | 약 0.001 GiB | 합성 테스트 결과·격리 세션 |

변환본을 유지하면서 공간을 줄이려면 모델 hash와 provenance를 백업·확인한 뒤 build env와 source snapshot만 제거하면 약 2.656 GiB를 회수할 수 있다. 완전 제거는 서버와 worker가 없는 것을 확인한 뒤 프로젝트 루트에서 다음 경로만 대상으로 한다.

```powershell
Remove-Item -LiteralPath '.venv-translation-build' -Recurse -Force
Remove-Item -LiteralPath '.venv-translation' -Recurse -Force
Remove-Item -LiteralPath 'models\translation\source\m2m100_418M-55c2e61' -Recurse -Force
Remove-Item -LiteralPath 'models\translation\m2m100_418m-int8' -Recurse -Force
Remove-Item -LiteralPath 'work\translation-poc' -Recurse -Force
```

`data/sessions`, 기존 `.venv`, `.env`/설정, Phase 보고서는 위 정리 대상이 아니다. 이번 작업에서는 어느 정리 명령도 실행하지 않았다.
