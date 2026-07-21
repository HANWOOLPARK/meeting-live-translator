# WhyKaigi

**Context-aware, near-real-time meeting translation with evidence-linked decisions and action items.**

WhyKaigi is a near-real-time meeting translation tool built around one priority: translation should be fast without losing the context that makes it accurate. It uses language-aware speech boundaries and meeting context to produce more natural captions, then translates them as the conversation continues.

Based on that transcript, WhyKaigi identifies the meeting's key points, decisions, and action items. Unlike meeting assistants that present suggestions without showing how they were inferred, every Decision Radar item links back to the translated caption and original source segment that supports it. The user can inspect the evidence and decide whether the result is correct.

> Build Week submission track: **Work & Productivity**  
> Public, keyless Replay: [open the verified Korean → English demo](https://meeting-live-translator-viewer.bakbaul.chatgpt.site/demo).

## Why I built it

I live in Japan, and my Japanese is good enough for everyday life, but not yet strong enough for business meetings. I could recognize individual words and understand parts of the context, but I often could not tell the overall purpose of the meeting, how far the discussion had progressed, or what had actually been decided. I usually understood the full picture only after the meeting ended and I used AI to summarize it.

I built WhyKaigi to understand the conversation while the meeting is still happening. It shows me what people are discussing and surfaces decisions in real time. Meetings used to feel long and frustrating. Now I look forward to them, because an application I built is genuinely helping me understand what is happening.

WhyKaigi is part of my existing Why series. I first built [Why BJT](https://why-bjt-study.vercel.app/), a web application for studying business Japanese for the BJT exam. “WHY” stands for “What Holds You Back?” I chose that phrase after coming to Japan, when I struggled to adapt to the culture and often felt carried along by circumstances.

In the future, I want to grow the Why series into one place where people from other countries living in Japan can find tools for Japanese study, meetings, and other parts of life in Japan.

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

The Replay contains sanitized event timing and model output from the real run, synchronized to a separately bundled, consented recording of the fictional demo script. It requires no API key, does not call a Provider, does not write to the sharing database, and contains no private meeting audio, private path, original session ID, or personal meeting data.

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
- Google-verified, read-only participant sharing with Supabase identity auditing and a public verified Replay.
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

- Live application audio is never written to session storage. The public Replay's scripted demo recording is a separate, explicitly consented static asset.
- Partial captions are not persisted.
- Final source transcripts and enabled derived results are stored locally under `data/sessions`.
- Deepgram receives audio only when selected.
- Gemini/OpenAI receive finalized text only when selected; the Radar receives a bounded finalized context window plus matched approved terms.
- API keys remain in the local `.env` or hosted secret configuration and are never returned by diagnostics.
- `.env`, `.share.env`, sessions, logs, PID files, models, runtimes, and virtual environments are excluded from source and Lite releases.
- Participant sharing requires explicit consent and displays external-transfer and retention notices.
- Invite links require a verified Google identity before room data is fetched. The Viewer validates the
  Supabase access token server-side and then issues a room-scoped HTTP-only session cookie.
- Relayed meeting text is deleted when sharing ends. Link-specific verified-email/access audit records are
  retained separately for 30 days in the operational relay log and the Supabase identity registry; local
  audit files never modify session JSONL.

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

I did not begin this project with a fixed technical implementation plan. I repeatedly used the application, found behavior that did not match my intention, explained the problem to Codex with concrete examples, and defined what an acceptable result should look like. Codex turned those observations into implementation changes, tests, diagnostics, and regression checks.

For me, developing with Codex has become a hobby that fits naturally into everyday life. Codex handled the implementation problems, while I remained responsible for deciding what the product should do, testing whether it was genuinely useful in a real meeting, and rejecting results that did not meet the level I expected.

GPT-5.6 powers the final Decision Radar demo. The product does not present model output as ground truth: items are suggestions, must cite existing finalized source segments, and remain reviewable and editable by the user.

## Build Week scope disclosure

Before the Build Week submission period, the project already had its core local captioning, session storage/export, and initial translation foundation. During Build Week, the project added or materially improved Deepgram streaming stability, multi-direction translation, the Context Engine, selective transcription risk handling, evidence-linked Decision Radar, review history, participant sharing, English UI, native overlay workflows, and the sanitized public Replay. The canonical English chronological record is in [`docs/BUILD_WEEK_LOG.md`](docs/BUILD_WEEK_LOG.md); the preserved Korean source log is in [`docs/BUILD_WEEK_LOG_KO.md`](docs/BUILD_WEEK_LOG_KO.md).

## Distribution and licenses

The source is licensed under the [MIT License](LICENSE). Third-party licenses, model sources, and runtime notices are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Korean setup and distribution documentation is available in [`README_KO.md`](README_KO.md) and [`DISTRIBUTION_KO.md`](DISTRIBUTION_KO.md).
