# Meeting Live Translator

**Live translation with evidence-linked decisions.**

Meeting Live Translator is a Windows-first meeting companion for people who need to follow a conversation in another language and verify what the meeting actually decided. It preserves the finalized source transcript, applies only user-approved terminology corrections, translates the corrected text, and turns explicit decisions, actions, and unresolved questions into a live Decision Radar. Every Radar item links back to the source segments that support it.

> Build Week submission track: **Work & Productivity**  
> Public, keyless Replay: [open the verified Korean → English demo](https://meeting-live-translator-viewer.bakbaul.chatgpt.site/demo).

## Why it is different

Most meeting tools stop at captions, translation, or an AI summary. This project makes the entire decision path inspectable:

```text
final source transcript
  → approved Context Engine corrections
  → translation
  → evidence-linked Decision Radar
  → jump back to source evidence
  → user approve / edit / delete
  → append-only change history
```

The source transcript remains available even when translation, Radar, the local model Worker, or an external Provider fails.

## Build Week demo pipeline

The final public Replay uses a fictional Korean product meeting recorded through the real application pipeline:

```text
Deepgram Nova-3 (Korean STT)
  → Context Engine (approved people and terms)
  → Gemini 3.1 Flash Lite (Korean → English translation)
  → GPT-5.6 Luna (English Decision Radar)
```

The Replay contains sanitized event timing and model output from the real run. It requires no API key, does not call a Provider, does not write to the sharing database, and contains no retained audio, private path, original session ID, or personal meeting data.

## Features

- Near-real-time system-audio or microphone captions on Windows 11.
- Local faster-whisper STT or Deepgram Nova-3 streaming STT.
- Japanese → Korean/English, English → Korean/Japanese, and Korean → Japanese/English directions.
- Gemini, OpenAI, or optional local M2M100 CTranslate2 translation.
- Partial captions shown immediately; only finalized segments are translated and analyzed.
- Deterministic correction of approved names, terms, and known aliases while retaining the unmodified STT result for audit.
- Evidence-linked decisions, action items, open questions, and confirmation needs.
- Separate caption, one-line media caption, and Radar windows; optional Electron always-on-top transparent overlays.
- Local append-only sessions, JSONL records, recovery, and exports.
- Read-only participant sharing and a public verified Replay.
- Korean/English UI.

## Architecture and failure boundaries

```text
Windows audio
  └─ bounded PCM queue
      ├─ local faster-whisper
      └─ Deepgram streaming STT
           └─ final transcript + quality metadata
               ├─ local append-only session record
               ├─ Context Engine normalization
               ├─ translation queue ── Gemini / OpenAI / local Worker
               └─ Radar queue ─────── GPT-5.6 / Gemini
                        └─ evidence validation + review history

FastAPI + WebSocket ── main UI / native overlays / read-only relay
Public Sites app ───── keyless Replay + participant viewer
```

Queues are bounded, Provider calls are asynchronous, and every external failure is recoverable. No audio callback performs model inference, network I/O, or file I/O. Translation and Radar results are matched by `segment_id`, so a delayed response cannot attach to the wrong caption.

## Privacy boundary

- Audio is never written to disk by the application.
- Partial captions are not persisted.
- Final source transcripts and enabled derived results are stored locally under `data/sessions`.
- Deepgram receives audio only when selected.
- Gemini/OpenAI receive finalized text only when selected; the Radar receives a bounded finalized context window plus matched approved terms.
- API keys remain in the local `.env` or hosted secret configuration and are never returned by diagnostics.
- `.env`, `.share.env`, sessions, logs, PID files, models, runtimes, and virtual environments are excluded from source and Lite releases.
- Participant sharing requires explicit consent and displays external-transfer and retention notices.

## Install on Windows 11

Requirements:

- Python 3.11 x64
- A supported Windows audio input or WASAPI loopback device
- Your own Provider keys for optional Deepgram, Gemini, or OpenAI features

From an extracted release folder:

```bat
setup.bat
start_all.bat
```

Stop only the processes owned by this project:

```bat
stop_all.bat
```

`stop_all.bat` validates the recorded server, local translation Worker, and Electron PIDs. It never terminates every Python or Electron process on the machine.

Copy `.env.example` to `.env` if setup has not already created it, then add only your own keys. Do not commit or redistribute `.env`.

Optional components:

```bat
setup_local_translation.bat
setup_desktop_overlay.bat
```

The local M2M100 setup uses a separate `.venv-translation`; Torch and Transformers are not installed in the main `.venv`. The desktop overlay setup uses a project-local portable Node/Electron runtime.

## Development

```bat
.venv\Scripts\python.exe -m pytest -q
```

The public viewer lives in `viewer-site` and uses the checked-in package manager lockfile:

```text
pnpm --dir viewer-site test
pnpm --dir viewer-site build
```

Live external tests are opt-in and guarded by explicit environment flags and confirmation arguments. Normal test runs do not call paid APIs.

## Built with Codex and GPT-5.6

Codex was used as the implementation and verification partner throughout Build Week: translating product observations into testable contracts, tracing latency across STT/translation/UI stages, hardening Deepgram sentence assembly and reconnect behavior, building the Context Engine and evidence validator, reproducing Provider failures, checking process ownership and data invariants, and creating the public Replay path.

GPT-5.6 powers the final Decision Radar demo. The product does not present model output as ground truth: items are suggestions, must cite existing finalized source segments, and remain reviewable and editable by the user.

## Build Week scope disclosure

Before the Build Week submission period, the project already had its core local captioning, session storage/export, and initial translation foundation. During Build Week, the project added or materially improved Deepgram streaming stability, multi-direction translation, the Context Engine, selective transcription risk handling, evidence-linked Decision Radar, review history, participant sharing, English UI, native overlay workflows, and the sanitized public Replay. The canonical English chronological record is in [`docs/BUILD_WEEK_LOG.md`](docs/BUILD_WEEK_LOG.md); the preserved Korean source log is in [`docs/BUILD_WEEK_LOG_KO.md`](docs/BUILD_WEEK_LOG_KO.md).

## Distribution and licenses

The source is licensed under the [MIT License](LICENSE). Third-party licenses, model sources, and runtime notices are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Korean setup and distribution documentation is available in [`README_KO.md`](README_KO.md) and [`DISTRIBUTION_KO.md`](DISTRIBUTION_KO.md).
