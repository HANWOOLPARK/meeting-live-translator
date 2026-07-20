# Phase 2 로컬 한국어 번역 환경 및 후보 평가

- 작성일: 2026-07-10 (Asia/Seoul)
- 대상: `meeting-live-translator`의 확정 일본어/영어 원문을 한국어로 번역하는 선택적 로컬 모델
- 조사 원칙: 현재 환경은 읽기 전용으로 확인했고, 패키지 설치·모델 다운로드·모델 변환·실제 번역은 수행하지 않았다.
- 상태 표기: 실제 실행 성공은 `PASS`, 실행하지 않은 항목은 `SKIP`, 공식 자료로도 확정할 수 없는 항목은 `미확인`으로 기록한다.

## 1. 결론

### 조건부 추천

`facebook/m2m100_418M`을 별도 번역 가상환경에서 CTranslate2 4.8.1 형식의 CPU `int8` 모델로 변환해 사용하는 방안을 1순위로 추천한다.

추천 이유는 다음과 같다.

1. 하나의 모델이 일본어(`ja`)→한국어(`ko`)와 영어(`en`)→한국어(`ko`)를 모두 직접 지원한다.
2. 모델 카드에 MIT 라이선스가 명시되어 있어 조사한 직접 번역 후보 중 배포 제약이 가장 적다.
3. CTranslate2 공식 문서가 M2M-100 변환과 `target_prefix` 사용 예제를 직접 제공한다.
4. 현재 머신은 Windows x86-64, Python 3.11.9이며 이미 CTranslate2 4.8.1 CPU `int8` 실행을 지원한다.
5. 31.54 GiB RAM과 623.42 GiB 디스크 여유가 있어 모델 보관과 CPU 추론의 메모리 용량 자체는 가능성이 높다.

다만 이 추천은 **설치 추천이 아니라 PoC 후보 추천**이다. 현재 모델은 캐시에 없고 실제 번역 품질, 번역 지연, peak RAM, faster-whisper와 동시 실행했을 때의 전사 지연을 측정하지 않았다. 따라서 Phase 2에서 별도 승인과 검증을 통과하기 전까지 번역 기능의 기본값은 `disabled`여야 한다.

### 추천하지 않는 기본 후보

- `facebook/nllb-200-distilled-600M`: 기술적으로 두 방향을 직접 지원하고 CTranslate2도 지원하지만, CC-BY-NC-4.0이며 모델 카드가 연구용이고 프로덕션 배포용이 아니라고 명시한다. 일반 배포 기본값으로 사용하지 않는다.
- `facebook/mbart-large-50-many-to-many-mmt`: 두 방향을 직접 지원하지만 더 크고, 해당 체크포인트 모델 페이지에서 라이선스 메타데이터를 확인하지 못했다. 라이선스를 별도로 확정하기 전에는 사용하지 않는다.
- Helsinki-NLP OPUS-MT 2단계 구성: 영어→한국어는 직접 지원하지만 공식 일본어→한국어 단일 모델을 확인하지 못해 일본어→영어→한국어 pivot이 필요하다. 모델은 가볍지만 지연과 오류가 두 번 누적되므로 기본 후보로 추천하지 않는다.

## 2. 현재 환경 실측

### 2.1 하드웨어 및 운영체제

| 항목 | 실제 결과 | 판정 |
|---|---:|---|
| OS | Microsoft Windows 11 Pro, 10.0.26200, 64-bit | PASS |
| 장치 | LG Electronics 17Z90U-GU88J | PASS |
| CPU | Intel Core Ultra 7 355, 8 cores / 8 logical processors | PASS |
| 물리 RAM | 31.54 GiB | PASS |
| 조사 시점 가용 RAM | 15.22 GiB | PASS, 시점에 따라 변동 |
| 그래픽 | Intel(R) Graphics, 드라이버 32.0.101.8356 | PASS |
| Windows 보고 Adapter RAM | 2 GiB | PASS, 통합 그래픽의 공유 메모리 보고값이며 전용 CUDA VRAM으로 간주하지 않음 |
| NVIDIA GPU | 없음 | PASS |
| `nvidia-smi` | PATH에서 찾지 못함 | PASS(부재 확인) |
| CTranslate2 CUDA 장치 수 | 0 | PASS |
| C: 사용량 | 294.05 GiB | PASS |
| C: 여유 | 623.42 GiB | PASS |
| 프로젝트 `.venv` 크기 | 0.32 GiB | PASS |

실행 명령:

```powershell
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption, Version, OSArchitecture,
    @{N='TotalRAM_GiB';E={[math]::Round($_.TotalVisibleMemorySize/1MB,2)}},
    @{N='FreeRAM_GiB';E={[math]::Round($_.FreePhysicalMemory/1MB,2)}}

Get-CimInstance Win32_ComputerSystem |
  Select-Object Manufacturer, Model,
    @{N='TotalPhysicalMemory_GiB';E={[math]::Round($_.TotalPhysicalMemory/1GB,2)}}

Get-CimInstance Win32_Processor |
  Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed

Get-CimInstance Win32_VideoController |
  Select-Object Name, DriverVersion,
    @{N='AdapterRAM_GiB_reported';E={[math]::Round($_.AdapterRAM/1GB,2)}}

where.exe nvidia-smi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

Get-PSDrive -Name C |
  Select-Object Name,
    @{N='Used_GiB';E={[math]::Round($_.Used/1GB,2)}},
    @{N='Free_GiB';E={[math]::Round($_.Free/1GB,2)}}
```

핵심 출력:

```text
OS: Microsoft Windows 11 Pro 10.0.26200, 64-bit
RAM: total 31.54 GiB, free 15.22 GiB
CPU: Intel(R) Core(TM) Ultra 7 355, 8 cores / 8 logical processors
GPU: Intel(R) Graphics, AdapterRAM_GiB_reported=2
where nvidia-smi: not found
C: used 294.05 GiB, free 623.42 GiB
```

### 2.2 Python 및 런타임 호환성

| 항목 | 실제 결과 | 판정 |
|---|---:|---|
| Python | 3.11.9, 64-bit AMD64 | PASS |
| pip | 26.1.2 | PASS |
| faster-whisper | 1.2.0 | PASS |
| CTranslate2 | 4.8.1 | PASS |
| faster-whisper의 CT2 요구 범위 | `ctranslate2>=4.0,<5` | PASS, 현재 4.8.1과 일치 |
| CT2 CPU compute types | `float32`, `int16`, `int8`, `int8_float32` | PASS |
| CT2 CUDA probe | `RuntimeError`, CUDA device count 0 | PASS(사용 불가 확인) |
| PyTorch | 미설치 | PASS(부재 확인), 변환/직접 Transformers 추론은 현재 불가 |
| Transformers | 미설치 | PASS(부재 확인), 변환/토크나이저 사용은 현재 불가 |
| SentencePiece | 미설치 | PASS(부재 확인), M2M100 토크나이저 사용은 현재 불가 |
| sacremoses | 미설치 | PASS(부재 확인) |
| tokenizers | 0.23.1 | PASS, faster-whisper 의존성으로 설치됨 |
| onnxruntime | 1.27.0 | PASS, 이번 추천 경로에는 직접 사용하지 않음 |

실행 명령:

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -m pip --version
.venv\Scripts\python.exe -m pip show `
  torch ctranslate2 faster-whisper transformers sentencepiece `
  sacremoses tokenizers onnxruntime

.venv\Scripts\python.exe -c "import importlib.metadata as m; print(m.requires('faster-whisper'))"
```

런타임 probe:

```python
import importlib.util
import ctranslate2

for name in (
    "torch", "ctranslate2", "faster_whisper", "transformers",
    "sentencepiece", "sacremoses", "tokenizers", "onnxruntime",
):
    print(name, importlib.util.find_spec(name))

print(ctranslate2.__version__)
print(sorted(ctranslate2.get_supported_compute_types("cpu")))
print(ctranslate2.get_cuda_device_count())
```

핵심 출력:

```text
Python 3.11.9
CTranslate2 4.8.1
CPU compute types: ['float32', 'int16', 'int8', 'int8_float32']
CUDA device count: 0
torch: NOT_INSTALLED
transformers: NOT_INSTALLED
sentencepiece: NOT_INSTALLED
tokenizers: 0.23.1
onnxruntime: 1.27.0
faster-whisper requires ctranslate2<5,>=4.0
```

CTranslate2 4.8.1 공식 설치 문서는 Windows x86-64 wheel과 Python 3.9 이상을 지원한다고 명시한다. 현재 Windows/Python 3.11 환경은 이 범위에 포함된다. PyTorch 최신 안정판도 Python 3.10 이상 및 Windows CPU 설치 경로를 제공하므로 Python 3.11 자체는 장애물이 아니다. 다만 현재 프로젝트 `.venv`에서는 PyTorch/Transformers/SentencePiece 조합을 설치·import해 보지 않았으므로 실제 dependency resolution은 `SKIP`이다.

### 2.3 모델 캐시

실행 명령:

```powershell
.venv\Scripts\python.exe -c `
  "from huggingface_hub import scan_cache_dir; i=scan_cache_dir(); print(i.size_on_disk); print([(r.repo_id,r.size_on_disk) for r in i.repos])"
```

실제 결과:

```text
Hugging Face cache: 약 0.45 GiB
cached model: Systran/faster-whisper-small (약 463.7 MiB)
facebook/m2m100_418M: NOT_CACHED
facebook/nllb-200-distilled-600M: NOT_CACHED
facebook/mbart-large-50-many-to-many-mmt: NOT_CACHED
Helsinki-NLP/opus-mt-ja-en: NOT_CACHED
Helsinki-NLP/opus-mt-tc-big-en-ko: NOT_CACHED
```

어떤 번역 후보도 현재 로컬에 없으므로 다운로드 없는 실제 번역 테스트는 불가능하다.

## 3. 후보 비교

크기와 RAM 표의 `예상` 값은 모델 파일 크기, 파라미터 수, CTranslate2의 공식 int8 약 4배 디스크 축소 설명을 이용한 설계용 보수 추정이다. 이 머신에서 측정한 값이 아니며 실제 peak RAM은 입력 길이, beam size, thread 수, 변환 결과에 따라 달라진다.

| 후보 | ja→ko / en→ko | 라이선스 | 공식 원본 크기 | CT2/Windows CPU | CT2 int8 예상 디스크 / 추가 RAM | 판정 |
|---|---|---|---:|---|---|---|
| `facebook/m2m100_418M` | 둘 다 직접 지원 (`ja`,`en`→`ko`) | MIT | 418M params, PyTorch weight 1.94 GB | CTranslate2 공식 M2M100 변환 지원; 현재 CPU int8 가능 | 약 0.5~0.8 GiB / 약 1~3 GiB | **1순위 조건부 추천** |
| `facebook/nllb-200-distilled-600M` | 둘 다 직접 지원 (`jpn_Jpan`,`eng_Latn`→`kor_Hang`) | CC-BY-NC-4.0 | 600M params, repo 2.48 GB, PyTorch weight 2.46 GB | CTranslate2 공식 NLLB 변환 지원; `transformers>=4.21` 필요 | 약 0.7~1.1 GiB / 약 1.5~4 GiB | 연구 비교만, 기본 배포 비추천 |
| `facebook/mbart-large-50-many-to-many-mmt` | 둘 다 직접 지원 (`ja_XX`,`en_XX`→`ko_KR`) | 해당 체크포인트 페이지에서 미표기 | 0.6B params, safetensors 2.44 GB | CTranslate2 MBART 지원 | 약 0.7~1.1 GiB / 약 1.5~4 GiB | 라이선스 확정 전 사용 금지 |
| OPUS-MT pivot: `opus-mt-ja-en` + `opus-mt-tc-big-en-ko` | en→ko 직접, ja→en→ko 2단계 | Apache-2.0 + CC-BY-4.0 | PyTorch weights 303 MB + 418 MB | CTranslate2 MarianMT 지원 | 합계 약 0.2~0.4 GiB / 약 0.7~2 GiB | 경량 대안이나 지연·오류 누적으로 비추천 |

### 3.1 M2M100 418M

공식 모델 카드는 M2M100이 100개 언어 사이 9,900개 방향을 직접 번역하며, 지원 목록에 English, Japanese, Korean을 포함한다고 설명한다. 모델 페이지는 MIT 라이선스를 표시한다. Hugging Face 저장소 전체 표시는 3.88 GB지만 PyTorch와 Rust 가중치가 각각 1.94 GB로 중복되어 있으므로, 변환 승인 시 전체 Git clone이 아니라 필요한 revision과 파일만 받아야 한다.

CTranslate2 공식 예제는 다음 흐름을 제공한다.

```text
ct2-transformers-converter --model facebook/m2m100_418M --output_dir m2m100_418
tokenizer.src_lang = "en"
target_prefix = [tokenizer.lang_code_to_token["de"]]
translator.translate_batch(..., target_prefix=[target_prefix])
```

본 프로젝트에서는 source를 `ja` 또는 `en`, target을 `ko`로 설정한다. M2M100 tokenizer는 SentencePiece에 의존한다.

장점:

- 한 모델만 메모리에 올려 두 방향을 처리한다.
- 일본어→한국어가 영어 pivot 없이 직접 처리된다.
- MIT 라이선스와 공식 CT2 변환 경로가 확인된다.
- NLLB/mBART보다 작다.

제약:

- 회의체 일본어·영어, 고유명사, 기술 용어, 숫자, 부정 표현의 한국어 품질은 이 환경에서 미검증이다.
- source weight가 pickle 기반 `pytorch_model.bin`이므로 변환은 격리된 도구 환경에서, 공식 저장소의 고정 commit과 해시를 확인한 뒤 수행해야 한다.
- CT2 int8 변환 크기·RAM·지연은 아직 `SKIP`이다.

### 3.2 NLLB-200 distilled 600M

모델 카드의 언어 코드에는 `jpn_Jpan`, `eng_Latn`, `kor_Hang`이 모두 포함된다. CTranslate2도 NLLB 변환 예제와 target prefix 방식을 제공한다.

그러나 모델 카드는 다음 제한을 명시한다.

- CC-BY-NC-4.0 / CC-BY-NC
- 연구 커뮤니티를 주 사용자로 함
- 프로덕션 배포용으로 출시되지 않음
- 일반 도메인 단문 번역용이며 의료·법률 같은 도메인 또는 문서 번역용이 아님
- 학습 입력은 512 tokens 이하

따라서 개인 비상업 연구 비교에는 후보가 될 수 있지만, 앱의 기본 로컬 번역 모델로 채택하지 않는다. 상업적 사용 가능성이 조금이라도 있으면 법률 검토 없이 설치하지 않는다.

### 3.3 mBART-50 many-to-many

모델 카드는 English(`en_XX`), Japanese(`ja_XX`), Korean(`ko_KR`)을 포함한 50개 언어 사이 직접 번역을 설명한다. 0.6B 파라미터이고 safetensors 한 벌은 2.44 GB이다. CTranslate2는 MBART 구조를 지원한다.

하지만 해당 fine-tuned 체크포인트 페이지에는 조사 시점 라이선스가 표시되지 않았다. 기반 `facebook/mbart-large-50` 페이지의 MIT 표기를 fine-tuned weight에 자동으로 확장해 해석하지 않는다. 별도 LICENSE 또는 배포자의 명시적 확인이 있기 전에는 후보를 보류한다. 크기도 M2M100보다 커 현재 환경에서 우선할 이유가 없다.

### 3.4 OPUS-MT pivot 구성

Helsinki-NLP 공식 모델 중 다음은 확인되었다.

- `Helsinki-NLP/opus-mt-ja-en`: Japanese→English, Apache-2.0, PyTorch weight 303 MB
- `Helsinki-NLP/opus-mt-tc-big-en-ko`: English→Korean, CC-BY-4.0, 0.2B params, F16 weight 418 MB

두 모델을 연결하면 영어는 한 번, 일본어는 두 번 번역해 한국어를 만들 수 있다. CTranslate2는 MarianMT를 공식 지원하므로 CPU 실행 가능성은 높고 총 모델 크기도 작다. 그러나 일본어 문장은 두 모델을 거치며 고유명사·수치·부정·문맥 오류와 지연이 누적된다. 요구 방향을 모두 **직접** 처리하는 단일 모델 후보가 존재하므로 기본안으로 선택하지 않는다.

## 4. faster-whisper 동시 사용 위험

### 4.1 GPU가 아니라 CPU가 병목

현재 NVIDIA/CUDA 장치가 없어 faster-whisper `small`과 번역 모델이 모두 CPU CTranslate2를 사용한다. 31.54 GiB RAM은 용량 면에서 여유가 있지만 조사 시점 가용 RAM은 15.22 GiB이고, 메모리 여유와 실시간 지연은 별개다. 두 CT2 모델이 동시에 MKL/OpenMP thread를 사용하면 8개 논리 CPU를 초과하는 thread oversubscription이 생겨 Phase 1의 전사 표시 목표 2~4초를 악화시킬 수 있다.

### 4.2 주요 위험

1. 전사와 번역의 CPU peak가 겹쳐 partial/final 전사 지연이 증가한다.
2. 첫 번역 시 모델 cold load가 RAM과 디스크 I/O를 순간적으로 사용한다.
3. 무제한 번역 queue는 회의가 길어질수록 지연과 메모리를 누적한다.
4. 같은 `.venv`에 Transformers/PyTorch를 추가하면 현재 tokenizers/CTranslate2 의존성에 불필요한 변화를 줄 수 있다.
5. `mixed`/`unknown` 발화는 M2M100 source language를 안전하게 하나로 정할 수 없다.
6. 번역 오류가 전사 worker를 막으면 원문 자막까지 지연될 수 있다.

### 4.3 완화 설계

- 번역은 **확정 자막만** 대상으로 하고 partial은 번역하지 않는다.
- 전사 pipeline과 번역 pipeline을 분리하며 번역 실패가 원문 전사/저장을 롤백하지 않게 한다.
- 번역 queue는 bounded queue로 하고 worker는 1개로 시작한다.
- 번역 CTranslate2 초기값은 `device="cpu"`, `compute_type="int8"`, `inter_threads=1`, `intra_threads=2`, `max_queued_batches=2`로 제한한다.
- 8 logical CPU 중 전사에 우선권을 주고, PoC에서 faster-whisper CPU thread 수도 명시적으로 제한해 총 thread 수가 8을 넘지 않도록 조정한다.
- 초기 성능 실험은 `beam_size=1`과 `beam_size=2`를 비교한다. CTranslate2 공식 성능 문서도 CPU int8과 낮은 beam size를 latency 절감 방법으로 권장한다.
- `ja`는 source `ja`, `en`은 source `en`으로 보낸다. `mixed`와 `unknown`은 임의 추측하지 않고 `translation_skipped`로 표시한다.
- 번역 모델은 설정을 켰을 때만 lazy load하고, 끄면 `unload_model()` 또는 process 종료로 자원을 회수한다.
- 번역 이벤트는 `segment_id`에 연결하고, 전사 완료 시각과 번역 완료 시각을 별도로 기록한다.
- queue 초과·timeout·모델 부재는 recoverable error로 처리하고 원문 자막은 그대로 유지한다.

## 5. 선택적 설치 및 격리 설계

현재 작업에서는 아래 명령을 실행하지 않았다. Phase 2 구현 승인 후 별도 단계에서만 수행한다.

### 5.1 기본 원칙

1. 번역 기능 기본값은 `disabled`.
2. 현재 `.venv`를 직접 확장하지 않고 프로젝트 내부 별도 `.venv-translation` 또는 `.venv-translation-build`를 사용한다.
3. 모델 변환용 PyTorch는 메인 FastAPI/faster-whisper process에 import하지 않는다.
4. CTranslate2는 현재 faster-whisper와 검증된 `4.8.1`로 고정한다.
5. Transformers와 PyTorch 버전은 PoC에서 실제 설치 테스트 후 lock 파일로 고정한다. 현재 문서에서는 움직이는 최신 버전을 설치하라고 확정하지 않는다.
6. Hugging Face `main` 대신 승인 시점의 full commit SHA를 고정하고, 다운로드 파일 해시와 라이선스를 보관한다.
7. `trust_remote_code`는 사용하지 않는다.
8. 모델은 Git에 넣지 않고 `models/translation/<model>-<revision>-int8/` 같은 프로젝트 로컬 ignored 경로에 둔다.
9. runtime은 네트워크 자동 다운로드를 금지하고 local path와 `local_files_only=True`만 사용한다.

### 5.2 승인 후 예상 절차

다음은 설계 예시이며 **미실행**이다.

```bat
py -3.11 -m venv .venv-translation-build
call .venv-translation-build\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
python -m pip install "ctranslate2==4.8.1" "transformers<5" sentencepiece
```

그다음 공식 저장소의 full commit SHA를 고정한 로컬 snapshot을 만든 후 변환한다.

```bat
ct2-transformers-converter ^
  --model models\source\m2m100_418M-<full-commit-sha> ^
  --output_dir models\translation\m2m100_418M-<full-commit-sha>-int8 ^
  --quantization int8 ^
  --copy_files sentencepiece.bpe.model tokenizer_config.json special_tokens_map.json
```

`LocalTranslationProvider`는 같은 실행 폴더에서 CTranslate2 `model.bin`과
M2M100 SentencePiece 파일을 확인한 후에만 사용 가능으로 판정한다. 변환 후에는
`M2M100Tokenizer.from_pretrained(..., local_files_only=True)`와 실제 비민감 샘플로
로컬 로드 검증을 통과해야 한다.

변환 환경과 runtime 환경을 더 엄격히 분리한다면 runtime `.venv-translation`에는 CTranslate2, Transformers tokenizer, SentencePiece만 설치하고 PyTorch는 두지 않는다. 이 구성이 tokenizer를 PyTorch 없이 로드하는지는 실제 설치 단계에서 import test를 통과해야 하며 현재는 `SKIP`이다.

### 5.3 서비스 경계

의존성 충돌과 장애 격리를 위해 번역은 별도 local worker process로 두는 방안을 권장한다.

```text
final_transcript
      |
      v
bounded translation queue  -- full/timeout --> translation_skipped/error
      |
      v
local translation worker (.venv-translation, CT2 CPU int8)
      |
      v
translation_result(segment_id, source_language, text, latency)
```

메인 서버는 worker가 없거나 모델이 설치되지 않아도 정상 실행되어야 한다. 설치 상태, 모델 revision, license ID, device, compute type은 `/api/settings` 또는 별도 provider 상태 응답에 민감정보 없이 표시한다.

## 6. Phase 2 PoC 검증 계획

| 검증 항목 | 현재 상태 | 승인 후 방법 |
|---|---|---|
| 번역 패키지 설치/import | SKIP | 별도 venv에서 Python 3.11 import test |
| M2M100 원본 다운로드/해시 | SKIP | full revision 고정, 필요한 파일만 다운로드, SHA256 기록 |
| CT2 int8 변환 | SKIP | `ct2-transformers-converter --quantization int8` |
| 변환 모델 구조 | SKIP | `ctranslate2.contains_model()` 및 tokenizer local load |
| ja→ko 실제 번역 | SKIP | 비민감 일본어 회의체 샘플 |
| en→ko 실제 번역 | SKIP | 비민감 영어 회의체 샘플 |
| cold load 시간/peak RAM | SKIP | process별 wall time와 working set 측정 |
| 번역 p50/p95 지연 | SKIP | 짧은/중간/긴 확정 발화 corpus |
| faster-whisper 단독 기준 | Phase 1 결과 사용 | 동일 WAV/실시간 조건으로 재측정 |
| 전사+번역 동시 지연 | SKIP | 번역 on/off A/B, 전사 2~4초 목표 유지 확인 |
| queue/backpressure | SKIP | 빠른 final burst, queue full, timeout, worker crash |
| 품질 평가 | SKIP | 고유명사, 숫자, 부정, 기술 용어, 경어, 혼합 문장 수동 평가 |
| 장시간 회의 안정성 | SKIP | 30~60분 비민감 입력, RAM 증가와 누락 확인 |
| NLLB 비교 | SKIP | 비상업 연구 범위와 라이선스 승인 시에만 동일 corpus 비교 |

PoC 채택 조건은 다음과 같다.

1. ja→ko와 en→ko 모두 의미 보존 수동 검토를 통과할 것.
2. 번역을 켜도 기존 원문 partial/final, 오디오 레벨, stop 시 final 저장이 누락되지 않을 것.
3. faster-whisper의 기존 2~4초 목표를 지속적으로 깨면 thread 수를 더 줄이거나 번역을 직렬화하고, 해결되지 않으면 로컬 번역을 기본 비활성으로 유지할 것.
4. 실제 peak RAM과 디스크 사용량을 보고서에 기록할 것.
5. 모델 부재, 잘못된 모델, worker 종료, timeout이 서버 전체 종료로 이어지지 않을 것.
6. 번역 결과가 의료·법률·공식 번역이 아님을 UI에서 알릴 것.

## 7. 최종 판정

| 항목 | 판정 |
|---|---|
| 현재 머신에서 CPU 로컬 번역 가능성 | **가능성이 높음** |
| 현재 상태에서 즉시 실행 가능 | **아니오** — tokenizer/변환 dependency와 모델이 없음 |
| GPU 가속 | **불가** — NVIDIA/CUDA 장치 없음 |
| 1순위 PoC 모델 | **M2M100 418M → CTranslate2 int8** |
| 지금 자동 설치/다운로드 | **하지 않음** |
| 프로덕션 채택 | **보류** — 품질·지연·RAM 동시 실행 검증 필요 |
| NLLB 기본 채택 | **거부** — 비상업/연구·비프로덕션 제한 |
| mBART 기본 채택 | **보류** — 해당 checkpoint 라이선스 미확인, 더 큼 |
| OPUS pivot 기본 채택 | **거부** — 일본어 2단계 번역 |

## 8. 출처

모든 링크는 2026-07-10에 확인했다.

### 모델 카드와 파일

- M2M100 418M 모델 카드: https://huggingface.co/facebook/m2m100_418M
- M2M100 418M 파일 크기: https://huggingface.co/facebook/m2m100_418M/tree/main
- M2M100 논문: https://arxiv.org/abs/2010.11125
- NLLB-200 distilled 600M 모델 카드·제한: https://huggingface.co/facebook/nllb-200-distilled-600M
- NLLB-200 distilled 600M 파일 크기: https://huggingface.co/facebook/nllb-200-distilled-600M/tree/main
- mBART-50 many-to-many 모델 카드·언어: https://huggingface.co/facebook/mbart-large-50-many-to-many-mmt
- mBART-50 many-to-many 파일 크기: https://huggingface.co/facebook/mbart-large-50-many-to-many-mmt/tree/main
- mBART-50 기반 checkpoint 라이선스 참고: https://huggingface.co/facebook/mbart-large-50
- OPUS-MT Japanese→English: https://huggingface.co/Helsinki-NLP/opus-mt-ja-en
- OPUS-MT English→Korean: https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-ko

### 런타임 및 호환성

- CTranslate2 Windows/Python 설치 요구사항: https://opennmt.net/CTranslate2/installation.html
- CTranslate2 Transformers 지원 모델과 M2M100/NLLB 예제: https://opennmt.net/CTranslate2/guides/transformers.html
- CTranslate2 quantization: https://opennmt.net/CTranslate2/quantization.html
- CTranslate2 CPU 성능 권장사항: https://opennmt.net/CTranslate2/performance.html
- CTranslate2 Translator thread/queue 옵션: https://opennmt.net/CTranslate2/python/ctranslate2.Translator.html
- CTranslate2 memory unload/load: https://opennmt.net/CTranslate2/memory.html
- CTranslate2 공식 저장소와 benchmark: https://github.com/OpenNMT/CTranslate2
- Hugging Face M2M100 tokenizer와 SentencePiece 의존성: https://huggingface.co/transformers/v4.11.3/model_doc/m2m_100.html
- Hugging Face Transformers 설치/호환성: https://huggingface.co/docs/transformers/v4.52.3/en/installation
- PyTorch Windows/Python 설치 선택: https://pytorch.org/get-started/locally/
- PyTorch Windows 64-bit 참고: https://docs.pytorch.org/docs/stable/notes/windows.html
