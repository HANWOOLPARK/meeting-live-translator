# OpenAI Build Week Development Log

This is the canonical English submission record for WhyKaigi. The
original Korean log is preserved verbatim in
[`BUILD_WEEK_LOG_KO.md`](BUILD_WEEK_LOG_KO.md) (archive SHA-256:
`95204397B48D7C36F56E79C43473038AFFDB4E763462DF42F4A295DF22BD6561`).

This document keeps the compliance record, distinguishes the pre-existing
project from work completed during the Submission Period, and records product
decisions, Codex collaboration, measured results, failures, trade-offs, and data
integrity checks. It never includes secret keys, private audio, or transcript
contents from private sessions.

- Last rules review: 2026-07-15 15:39 KST
- Official rules: <https://openai.devpost.com/rules>
- Official event page: <https://openai.devpost.com/>

## 1. Rules summary and compliance gates

This section is a working summary. The official rules take precedence if any
statement here conflicts with them. Status values in this table reflect the
time of the original review; the final deployment status is recorded at the end
of this document.

| Item | Requirement or decision | Status when recorded |
|---|---|---|
| Recommended track | Work & Productivity | Tentative selection |
| Submission Period | 2026-07-13 09:00 PT through 2026-07-21 17:00 PT | In progress |
| Deadline in Korea | 2026-07-22 09:00 KST | Confirmed |
| Existing project | Only meaningful Codex/GPT-5.6 extensions made during the period are judged | Applicable |
| Before/after evidence | Dated Codex sessions, commits, or equivalent evidence | Codex sessions existed; Git had not yet been created |
| Required development tools | Codex and GPT-5.6 | User-provided model selector screenshots and a shared conversation showed GPT-5.6 Sol |
| Project description | English explanation of the features and operation | Not yet written |
| Demo video | Public YouTube video with audio, under three minutes, explaining Codex/GPT-5.6 use | Not yet produced |
| Repository | Public, or private and shared with the designated judging account | Not yet prepared |
| README | Setup, execution, sample, Codex collaboration, and decisions | Korean runbook only |
| Codex Session ID | `/feedback` Session ID for the core implementation | Still required |
| Judge access | A free-to-run build, demo, or reproducible instructions | Lite ZIP existed, but the judging path was incomplete |
| Submission language | English, or English translations for all materials | English materials required |
| Third-party rights | Comply with SDK/API terms and open-source licenses | Notices existed; final audit required |
| Video copyright | Do not use unlicensed brands, music, or media | Use a self-created sample |

The Republic of Korea is listed as an eligible jurisdiction. The entrant must
personally confirm age eligibility, conflicts of interest, and completed Devpost
registration because these cannot be verified from the codebase.

## 2. Judging criteria

Stage 1 is a pass/fail check for theme fit and credible use of the required
tools. The four Stage 2 criteria have equal weight:

1. **Technological Implementation** — deep, capable use of Codex and a working,
   non-trivial implementation.
2. **Design** — a coherent, complete product experience rather than only a
   technical proof of concept.
3. **Potential Impact** — a convincing solution to a specific real-world user
   problem.
4. **Quality of the Idea** — creativity, differentiation, and depth of problem
   understanding.

## 3. Pre-Submission-Period baseline

The Submission Period began at 2026-07-14 01:00 KST. Features that already
existed before that time are not claimed as Build Week work:

- Windows WASAPI loopback and microphone capture with local Whisper
  transcription.
- Phase 2 asynchronous translation queue with `none`, local, and OpenAI
  providers.
- Phase 3 session lifecycle, JSONL storage, export, and post-meeting analysis.
- M2M100 CTranslate2 local translation sidecar with PID-scoped start and stop.
- Gemini translation provider.
- Initial Deepgram streaming STT integration.

These capabilities provide architectural context only and remain explicitly
separate from the judged extensions below.

## 4. Meaningful extensions during the Submission Period

This table was reconstructed from file timestamps and Codex work records. Each
item was later linked to commits or the evidence in this log.

| Time (KST) | User problem or decision | Work completed with Codex | Verification evidence |
|---|---|---|---|
| 2026-07-14 morning | Distribute the app without requiring a complex development environment | Designed and built a Lite ZIP, setup scripts, secret/session/model exclusions, and optional local-model installation | `make_lite_release.bat`, `scripts/build_lite_release.ps1`, ZIP content and hash checks |
| 2026-07-14 afternoon | Expand beyond Japanese to English-to-Korean | Added STT/translation direction constraints to the UI and API and exposed provider-specific compatibility | Direction and settings tests |
| 2026-07-14 afternoon | Detach captions, control opacity, and choose original/translation visibility | Added caption pop-out, opacity control, and original-only, translation-only, and combined views | Frontend regression tests |
| 2026-07-14 afternoon | Prevent partial/final duplicates, missing fast speech, translation backlog, and disconnect loss | Made partials display-only, translated finals only, matched by `segment_id`, and added bounded queues/retries, reconnect buffering, and diagnostics | Automated tests and diagnostics |
| 2026-07-14 evening | Reduce perceived latency on a real YouTube sample | Measured the same 60–90 second speaker → WASAPI → Deepgram → Gemini path before and after, then added a four-second Deepgram `Finalize` ceiling, initial-connect retry, and send timeout | Finals in 30 seconds: 3→7; longest chunk: 12.57s→4.04s; full suite: `228 passed, 3 skipped` |
| 2026-07-15 | Preserve Build Week and collaboration evidence | Reviewed official rules and created the baseline boundary, judging-risk log, and submission checklist | This document and Codex work history |
| 2026-07-15 | Verify early GPT-5.6 ideation and choose a differentiator | Confirmed GPT-5.6 Sol with high reasoning in user screenshots and reviewed a shared early design conversation; selected the Worksite/Adaptive Context Engine as the main differentiator | Two user screenshots and shared conversation as supporting evidence; `/feedback` still required |
| 2026-07-15 16:39 | Correct names and domain terms, but add meeting-discovered candidates only with consent | Built the Worksite Context Engine: persistent profiles, terms/people, misrecognition aliases, source-preserving deterministic normalization, Nova-3 keyterms, translation glossary, normalized analysis input, approval/ignore inbox, UI/API/diagnostics | `236 passed, 3 skipped`; browser keyterms 0→10; synthetic person CRUD; zero console errors; no 375px horizontal overflow |
| 2026-07-15 17:08 | Keep long term lists compact and allow Gemini meeting analysis | Converted term and recommendation areas to 350px keyboard-accessible scroll lists; added an official Google Gen AI SDK analysis provider with strict structured output, evidence validation, error isolation, settings, UI, and privacy notice | `247 passed, 3 skipped`; `clientHeight 350 < scrollHeight 690`; Gemini available/model/warning shown; no error overlay |
| 2026-07-15 18:12 | Let English-speaking judges operate the product | Added a Korean-default Korean/English UI toggle, persistence, cross-window sync, and translation of static and dynamic status/error/template UI while leaving user content untouched | `252 passed, 3 skipped`; both directions, refresh persistence, window sync, no unintended Korean text in the English view, and zero collected console errors |

### 4.1 Worksite Context Engine — 2026-07-15

- **User decision:** Store people separately from general terms. Never learn a
  meeting candidate automatically; ask the user to add or ignore it.
- **Codex implementation:** Added `backend/app/context_engine/`, Context REST,
  WebSocket, and diagnostics; repeated Deepgram `keyterm` parameters; a separate
  append-only `context_normalization` event beside the untouched final; normalized
  translation and analysis inputs; and profile, entry, and recommendation UI.
- **Changed components:** `backend/app/context_engine/*`, API schemas, services,
  main application, capture controller, Deepgram stream, translation manager,
  session repository/assembler, analysis modules, frontend assets,
  `tests/test_context_engine.py`, frontend tests, `.gitignore`, and `README_KO.md`.
- **Verification:** `python -m pytest -q` → `236 passed, 3 skipped`. Browser
  testing covered profile switching, synthetic person/alias add and delete,
  overlays, console output, and mobile overflow.
- **Trade-offs:** Japanese/English live before-and-after accuracy had not yet
  been measured. Recommendations use acronym, CamelCase, katakana, and honorific
  heuristics and always require approval. Deepgram keyterm changes take effect on
  the next capture rather than rebuilding an active stream.
- **Codex evidence:** GPT-5.6 Sol screenshots and the early shared conversation
  were available as supporting evidence; the core `/feedback` Session ID was
  still pending.

### 4.2 Scrollable lists and Gemini analysis — 2026-07-15

- **User decision:** Keep Context Engine cards from growing with every term and
  add Gemini as an analysis choice.
- **Codex implementation:** Applied fixed-height keyboard-focusable inner lists.
  `GeminiAnalysisProvider` reuses `GEMINI_API_KEY` and the translation model by
  default, with an optional `GEMINI_ANALYSIS_MODEL`. Only real analysis requests
  leave the machine. Structured Output, strict Pydantic validation, final
  `segment_id` evidence checks, bounded timeout, and retry behavior match the
  OpenAI path.
- **Changed components:** Gemini analysis provider and exports, services/main,
  settings/schemas, frontend assets, `.env.example`, `README_KO.md`, `AGENTS.md`,
  and Gemini/config/API/frontend tests.
- **Verification:** Full suite `247 passed, 3 skipped`. An isolated browser on
  port 8878 confirmed the 350px list (`scrollHeight=690` for ten entries), Gemini
  availability/model display, privacy/cost notice, and no overlay error, then all
  temporary tabs, processes, and ports were cleaned up.
- **Trade-offs:** No real Gemini generation was performed to avoid cost and
  disclosure. Mocked tests covered authentication, 429, timeout, 5xx, malformed
  JSON, and invalid evidence; account access, quota, and live latency remained a
  first-run check.

### 4.3 Korean/English UI switching — 2026-07-15

- **User decision:** Implement the product UI toggle immediately while keeping
  Korean as the default; write the English README, Devpost copy, and subtitles
  after feature development.
- **Codex implementation:** Added a build-free `i18n.js` dictionary keyed by the
  Korean source strings, an accessible Korean/English control, `localStorage`
  persistence, and main/caption-window synchronization through
  `BroadcastChannel` and storage events. Device, STT, provider/worker, session,
  Context Engine, analysis, WebSocket, error, confirmation, and template UI all
  follow the selected language. Transcripts, translations, user terms/names, and
  model-generated analysis are never routed through UI translation.
- **Changed components:** `i18n.js`, main/caption HTML, JS and CSS,
  `tests/test_ui_i18n.py`, `README_KO.md`, and this log.
- **Verification:** Targeted suite `35 passed`; full suite
  `252 passed, 3 skipped`. Live-browser verification covered Korean→English,
  refresh persistence, inherited language in a new caption window, translated
  templates, caption→main synchronization, meaningful rendering, and no error
  overlay. The saved language was restored to Korean.
- **Trade-offs:** A language change reloads the page once to rebuild all dynamic
  UI. It does not stop capture, but switching during active audio was not tested.
  New Korean API messages must be added to the English dictionary.

### 4.4 Korean-to-English translation — 2026-07-15

- **User decision:** Add Korean-to-English to the existing Japanese/English to
  Korean and Korean-to-Japanese directions. Korean input remains Deepgram-only,
  with Gemini or OpenAI translation; local Whisper and the Korean-target-only
  M2M100 worker are blocked.
- **Codex implementation:** Added `ko_to_en` to public settings, FastAPI schemas,
  capture routing, and translation request/result language fields. Deepgram
  receives `ko`; external translators receive `en` and must return only natural
  English meeting speech. Direction controls, headings, progress labels, and
  English UI strings were connected. Start remains disabled until compatible STT
  and translation providers are applied. Static asset versions were bumped.
- **Changed components:** settings, schemas, capture controller, translation
  models/providers, main UI/i18n/caption assets, `.env.example`, `README_KO.md`,
  and direction/provider/security tests.
- **Verification:** Targeted direction/provider/schema/STT/i18n suite
  `63 passed`; full suite `255 passed, 3 skipped`. In the live browser both
  Korean-source directions were disabled under local Whisper and enabled after
  choosing Deepgram; `ko_to_en`, the English-translation heading, local-provider
  disablement, and the pre-apply start guard all worked without console errors.
- **Trade-offs:** The live paid Deepgram→Gemini/OpenAI path was not invoked in
  this step. SDK/language routing used mocks and controller integration. Existing
  sessions were read only. A server restart was required to load backend changes.

### 4.5 Supporting sections collapsed by default — 2026-07-15 20:05 KST

- **User decision:** Do not build the discussed offline bidirectional mode.
  Instead, make “Meeting terms and people,” “Current session and records,” and
  “Meeting analysis” collapsible and closed by default.
- **Codex implementation:** Converted the three cards to native
  `details`/`summary`, retained headings and status badges while closed, and kept
  forms, loaded data, APIs, and result DOM intact. Added mouse and Enter/Space
  toggles, synchronized `aria-expanded`, focus styles, rotating arrows, mobile
  spacing, and updated cache identifiers.
- **Verification:** Targeted suite `22 passed`; full suite
  `256 passed, 3 skipped`. The live browser showed all cards starting at roughly
  91px with `open=false` and `aria-expanded=false`; keyboard interaction expanded
  the session card to roughly 484px and collapsed it again. No overlay or console
  errors appeared.
- **Trade-offs:** Expanded state intentionally is not persisted, so refresh and
  UI-language changes restore the compact default. Data continues to update while
  collapsed. No capture, provider application, session creation, or analysis was
  performed, and no existing session file changed.

### 4.6 Measured latency improvement

The supplied YouTube sample was played for 60–90 seconds through Windows Media
Player and captured through the default WASAPI loopback. It was not uploaded
directly to the STT API.

| Metric | Before | After |
|---|---:|---:|
| Final transcripts in 30 seconds | 3 | 7 |
| Longest source chunk | 12.57s | 4.04s |
| First completed translation | About 10.79s | At most about 6.05s |
| Gemini provider latency | 0.73–0.84s | 0.54–0.79s |

## 5. User and Codex roles

### User-led work

- Defined the real problem: usable captions for Japanese meetings, English
  meetings, and video viewing.
- Made product-priority decisions: local/external providers, reverse-direction
  constraints, detached captions, opacity, display modes, and Lite distribution.
- Supplied hardware and YouTube observations that exposed latency and UX issues.
- Made the final cost, privacy, and distribution decisions.

### Work accelerated by Codex

- Converted requirements into phased architecture, fault boundaries, and
  testable interfaces.
- Measured audio, STT, translation, and UI stages separately to identify actual
  bottlenecks.
- Built recovery paths so Deepgram, Gemini, or M2M100 failure cannot stop source
  capture.
- Implemented security boundaries, PID-scoped process management, and secret-free
  Lite packaging.
- Performed unit, integration, live-environment regression testing, and
  documentation.

### Joint product decisions

- Kept `endpointing=300ms` after `150ms` split natural short pauses.
- Measured that long Deepgram `speech_final` waits, not Gemini inference alone,
  were the dominant latency source.
- Kept partial text UI-only because translating interim hypotheses caused
  duplicates, rewrites, and cost; used official `Finalize` to obtain stable finals
  sooner.
- Excluded the local model from the ZIP and made it optional to reduce package
  size and setup friction.
- Selected the Worksite/Adaptive Context Engine over generic translation as the
  differentiator: approved domain language must remain consistent through STT,
  translation, and analysis.
- Required explicit Add/Ignore consent for Context recommendations. Person and
  worksite-term data stays outside Git and the Lite ZIP.
- Used repeated official Nova-3 `keyterm` parameters without interrupting an
  active connection. Normalization and glossary changes apply immediately; STT
  keyterms apply at the next capture connection.

## 6. Required format for subsequent records

Every Build Week change adds at least one entry using this structure:

```text
Date/time (KST):
User problem or observation:
Product decision made by the user:
What Codex proposed or implemented:
Changed files or commit:
Verification command and actual result:
Failures, trade-offs, and remaining risks:
GPT-5.6/Codex Session ID:
```

Unmeasured performance is labeled as an estimate, and unexecuted tests are never
recorded as passing. API keys and real meeting transcripts stay out of logs,
READMEs, videos, and repositories.

## 7. Objective assessment at the time of review

### Self-assessed score (out of 10)

| Criterion | Score | Evidence at the time |
|---|---:|---|
| Technological Implementation | 8.5 | Real audio, multiple providers, failure isolation, sessions, distribution, and Context Engine propagation from STT through normalization, translation, and analysis. GPT-5.6 screenshots/shared conversation existed, but the key Session ID and commit history were incomplete |
| Design | 8.0 | Coherent settings → context profile → capture → captions → translation → detached window → session workflow. Windows installation and API-key setup introduced judging friction |
| Potential Impact | 8.0 | Clear problem and user: meetings across a language barrier |
| Quality of the Idea | 7.5 | User-controlled memory for domain terms and names, with source preservation, added to general live translation. A live multilingual demo was still needed |

The project was submission-capable and above average in feature completeness,
but not yet a likely winner. The primary weaknesses were evidence and delivery,
not code volume:

1. The Context Engine differentiator lacked a before/after recognition and
   translation video.
2. Windows-only installation and participant API-key requirements created judge
   friction.
3. The project lacked a clear English submission narrative and strong evidence
   of the new GPT-5.6/Codex contribution relative to the baseline.

The recommended product center was the **Worksite Context Engine**: users control
meeting/worksite profiles, terms, names, and aliases, and the same context reaches
Deepgram keyterms, deterministic source normalization, translation glossaries,
and analysis. Both raw and normalized source remain preserved, and candidates
are never learned without user approval.

The first vertical path shipped on 2026-07-15. It connected profiles, people,
terms, aliases, Deepgram keyterms, separate normalization events, translation
glossaries, analysis input, and an approval inbox. Recommendation extraction was
still deterministic and conservative; it did not claim complete Japanese proper-
noun detection.

On top of that, the desired product experience became **multilingual meeting
memory that never loses the source during failures and lets a user return to the
evidence for every decision**.

The GPT-5.6 Decision Radar was treated as a real-time action layer over the
Context Engine rather than the sole differentiator. Because Phase 3 already had
post-meeting decision/action/evidence analysis, a simple rerun would not have
been a meaningful extension. The new target behavior was:

- Analyze final segments only and continuously update decisions, owners,
  deadlines, and unresolved questions.
- Link every result to source `segment_id` values and navigate back on click.
- Mark uncertain or conflicting items for confirmation instead of guessing.
- Continue source capture during STT/LLM failure and catch up safely.
- Demonstrate listen → translate → capture decision → open evidence in 90 seconds.

The recommended demo path became: generic-profile term error → worksite-profile
normalization → consistent translation → captured action → evidence navigation.

## 8. Submission checklist from the initial review

- [ ] Confirm Devpost registration and individual eligibility.
- [x] Confirm GPT-5.6 Sol in user-provided model screenshots and the shared early
  conversation.
- [ ] Obtain the key Codex Session ID through `/feedback`.
- [ ] Create the repository, scan out secrets, and distinguish baseline and new
  commits.
- [ ] Confirm Work & Productivity as the track.
- [ ] Complete one differentiating feature and describe only the new work clearly.
- [ ] Write English `README.md` covering problem, demo, setup, tests,
  architecture, and Codex collaboration.
- [ ] Provide a free judge path or reproducible Windows Lite package.
- [ ] Scan repository/video for keys, sessions, local paths, and copyrighted media.
- [ ] Produce a public YouTube demo under three minutes with English narration or
  subtitles.
- [ ] Explain Codex/GPT-5.6 use, user decisions, and measured before/after values.
- [ ] Enter English description, images, repository URL, and Session ID in Devpost.
- [ ] Submit safely before 2026-07-22 09:00 KST.

## 9. Evidence-linked Decision Radar — 2026-07-15 21:10 KST

- **User problem:** Translation alone does not reveal what was decided or who
  must act. Every inference needed a verifiable source, and the existing names
  and domain terms had to carry into analysis.
- **User decision:** Analyze Deepgram finals only; continuously update decisions,
  action items, unresolved questions, and names/terms/translations that need
  confirmation. Users can approve, edit, or delete suggestions and explicitly
  choose OpenAI or Gemini. Radar failure must never block transcription,
  translation, or session persistence, and existing JSONL files remain untouched.
- **Codex implementation:** Added batches of five finals or at most ten seconds,
  a concurrency-one bounded queue, timeout and finite retries, strict Structured
  Output, validation against real `segment_id` values in the active batch,
  deduplication, deletion tombstones, and a separate atomic Radar store. The
  initial OpenAI default was `gpt-5.6-luna`, selected from official model guidance
  for frequent low-latency structured analysis and overridable in `.env`.
  Availability reads make no external call; applying an external provider shows
  a disclosure notice. The UI uses three columns when wide, 2+1 at medium width,
  and one column on narrow screens, with Korean and English copy.
- **Changed components:** `backend/app/decision_radar/`, settings, services,
  capture controller, API schemas, main app, frontend assets/i18n, `.env.example`,
  documentation, `tests/test_decision_radar.py`, and the manual checklist.
- **Verification:** Full suite `264 passed, 3 skipped in 11.06s`. Node syntax
  checks passed. Playwright plus installed Edge verified 1440/1024/760px layouts,
  English UI, all three provider choices, the Gemini disclosure, and refresh with
  zero HTTP/console errors. A sorted aggregate over 179 existing session files
  remained `FD0D03ED08680FD5D1F4C138627997DE65C6EE2FC1265A9E7BAC368812948AB9`.
- **Failures and risks:** The first PowerShell hash command used unavailable
  `[IO.Path]::GetRelativePath`; a string-based relative-path calculation replaced
  it without writes. Live Radar calls were skipped to avoid cost/quota and source
  disclosure. Provider access, latency, and Japanese/English extraction quality
  still required manual validation. Without diarization, owners are safe only
  when explicit in the source. Overflow drops Radar work only, never source
  capture. Derived Radar files can contain meeting content and are excluded from
  public artifacts.
- **Codex evidence:** Design, implementation, automated tests, local browser
  verification, and documentation were completed in this Codex session. The
  Devpost Session ID must come from a real `/feedback` response.

## 10. Dedicated Radar window and native transparent overlays — 2026-07-15 23:55 KST

- **User problem and decision:** Browser pop-out opacity did not affect the
  Windows surface, and the user wanted actual Radar results—not provider
  settings—in a detachable window. Provider configuration remains in the main
  UI; the caption and Radar result windows provide true Windows transparency and
  always-on-top behavior without coupling native UI failure to capture.
- **Codex implementation:** Added a `/decision-radar` REST/WebSocket result window,
  snapshot and evidence-navigation channels, Korean/English UI, and 0–85%
  background opacity. An optional Electron shell creates only sandboxed,
  frameless, transparent, always-on-top caption/Radar overlays. Preload exposes
  limited IPC; permissions and off-localhost navigation are denied. Added a
  checksum-verified portable Node/Electron setup, native/browser fallback in
  `start_all.bat`, verified desktop PID-tree termination in `stop_all.bat`, Lite
  source-only distribution, and upstream notices.
- **Changed components:** backend main; main/caption/Radar frontend files;
  `desktop/main.cjs`, `desktop/preload.cjs`, package manifests; setup/start/stop
  scripts; Lite builder; ignore rules; documentation; and native-window tests.
- **Verification:** Five Node syntax checks and four PowerShell parser checks
  passed. Targeted tests: `20 passed in 3.40s`; full runs:
  `275 passed, 3 skipped in 14.52s` and `275 passed, 3 skipped in 13.86s`.
  Node 24.18.0 and Electron 43.1.1 installed successfully. Native caption/Radar
  windows showed transparent backgrounds with opaque text. The real
  `start_all → stop_all → start_all` flow verified separate server, worker, and
  desktop PIDs, health, port 8765 cleanup, PID-file cleanup, and survival of an
  unrelated Codex Node process. The 0.29 MiB Lite ZIP excluded runtime, secrets,
  and sessions; SHA-256 was
  `24F4730CD44BA190C75E9377D55BA2FB8FA4D1C61482203DEF3B970DB64A4A6A`.
  The 179-session aggregate remained unchanged.
- **Failures and risks:** The first npm run skipped Electron's binary hook; a
  package-owned install hook plus executable post-check fixed it. A hidden launch
  option initially hid the UI and was removed. Browser fallback exposed a
  Playwright path issue, a narrow-layout hidden language control, and favicon
  404; each was fixed. A secret scan correctly flagged an intentional synthetic
  redaction fixture, not a real key. Electron's Windows transparent-window
  limitation requires fixed overlay sizes and toolbar dragging. Long live editing
  and evidence navigation with a real external Radar remained manual work.

## 11. One-line media captions — 2026-07-16 10:24 KST

- **User problem and decision:** The full detached transcript obscured too much
  YouTube/Netflix content. Keep it, but add a low, wide media-caption mode at the
  bottom-center of the current display with 60%, 80%, and 94% width presets. Show
  the newest sentence only, with original/translation/both and opacity controls.
- **Codex implementation:** The default is automatic, translation-first: show the
  final source immediately, then replace it with the successful translation for
  the same `segment_id`. A live partial can appear before the final. Text starts
  at the user's 22–48px size, shrinks one pixel at a time to 18px when necessary,
  and only then uses ellipsis. The toolbar is hidden until hover/focus. Electron
  positions the window 12px above the active display's `workArea`; restricted IPC
  accepts only 60/80/94 and reapplies layout after display changes. Browser
  fallback opens the same responsive page.
- **Verification:** Node checks passed. Targeted runs were `17 passed in 2.04s`
  and `25 passed in 1.94s`; full suite `276 passed, 3 skipped in 12.38s`.
  Synthetic WebSocket browser tests, isolated from real sessions, verified one
  newest item, source→translation replacement, partial precedence, one-line
  layout, 36→26px shrink at 1600px, 18px+ellipsis at 960px, no horizontal
  overflow, all presets, and both UI languages. A native button opened a
  `1605 × 220px` window at the expected lower-center position under the 94%
  preset. Health, worker, desktop, and the unchanged 179-session hash were
  rechecked. Lite: 305,370 bytes, 105 entries, SHA-256
  `8B5D431059E0B23847680A8A9B600D8BD3F2F8B33086811F4BA3E0E454EC0F5A`.
- **Failures and risks:** `agent-browser` was unavailable on PATH, so bundled
  Playwright plus Edge was used. A CSS intrinsic `max-content` track initially
  clipped rather than shrank long text; bounded flex width fixed it. One stale
  cache-buster assertion was corrected to verify that all assets share a version.
  Transparent Windows overlays use presets rather than arbitrary resize, and
  extremely long captions intentionally ellipsize below 18px.

## 12. Gemini structured-analysis compatibility — 2026-07-16 11:08 KST

- **User problem:** Gemini translation worked, but Radar returned
  `unknown_provider_error`; diagnostics showed no 429, `RESOURCE_EXHAUSTED`, quota,
  or timeout evidence.
- **User decision:** Leave the OpenAI Radar path unchanged and repair only Gemini.
- **Codex implementation:** Replaced legacy strict-Pydantic `response_schema`
  usage in Gemini Radar and post-meeting analysis with the official
  `response_json_schema=<Payload>.model_json_schema()` form. OpenAI Responses
  `text_format` remained unchanged. Added case-insensitive status normalization
  and safe mappings: 400 `INVALID_ARGUMENT` → `INVALID_RESPONSE`, 400
  `FAILED_PRECONDITION` → `PROVIDER_UNAVAILABLE`, and 429
  `RESOURCE_EXHAUSTED` → `RATE_LIMITED`. Keys and private upstream bodies never
  reach UI, logs, or exception text.
- **Verification:** The first mock run exposed a status-case defect
  (`1 failed, 24 passed`); after `casefold`, `25 passed in 0.71s`. Full suite:
  `278 passed, 3 skipped in 13.80s`. After a clean project restart, health was
  `ok`, capture `idle`, worker `ready`, Radar `idle`, and `last_error_code=null`.
  No session was modified during the change. The then-current 193-file aggregate
  was `25D4D632C732D670C544C79D26F18B15653B2942DCEDDE280DD149490FD085DA`.
  Lite SHA-256:
  `D146C216A49EDFD9F178E9AFC4038132FD886FF65AE817C405B100F79EDECD8C`.
- **Risk:** No paid/private Gemini generation was made automatically. The account,
  latency, and quality path still needed one non-sensitive manual run. The old raw
  400 response was not retained, so its exact subtype could not be proven after
  the fact; future 400 responses are now classified instead of collapsed.

## 13. Decision Radar semantic-precision guardrails — 2026-07-16 12:06 KST

- **User problem:** In a real Japanese sample, evidence IDs pointed to real
  source, but quoted general advice and conditional time ranges became Actions,
  semantically equivalent questions duplicated, and opinion uncertainty became
  a translation-confirmation item. Post-session analysis with the same Gemini
  model did not make those mistakes, so model tier alone was not the explanation.
- **User decision:** Improve the application's semantic boundary before changing
  models. Preserve sessions/JSONL and add shared OpenAI/Gemini context, strict
  speech-act rules, and false-positive retraction.
- **Codex implementation:** Kept five-item/ten-second batches and added up to 20
  preceding final segments as rolling context, while marking the new batch with
  `focus_segment_ids`. Every new item must include at least one focus evidence ID,
  enforced server-side. The precision-first prompt prohibits quotes, hearsay,
  viewer requests, examples, general advice, opinions, suggestions, rhetorical
  questions, hypotheticals, conditions, possibilities, and duration estimates
  from becoming decisions/actions without explicit participant agreement or a
  future commitment. New context can use `retract_item_ids` for unreviewed false
  or duplicate suggestions; approved/edited items and unknown IDs are protected.
  `DECISION_RADAR_CONTEXT_SEGMENTS` bounds and exposes context size.
- **Verification:** Radar tests `12 passed in 0.65s`; full suite
  `282 passed, 3 skipped in 11.18s`. Private session text was not printed, but both
  earlier false-positive locations contained the expected request/hearsay/
  conditional signals in their 20-item contexts. The installed Google Gen AI SDK
  accepted the new required JSON schema offline. After restart and provider-state
  restoration: health `ok`, capture `idle`, worker `ready`, Radar `idle`, context
  20, queue 0, no error. The 201-file aggregate remained
  `5001E02E416E6FB903A5C8914BF11AABA360F177228E3CC6351EA4111FC892D4`.
  Lite SHA-256:
  `CF30A46E4740E153B00806CFB7065F7953368ECEBBF4E4C942D8A534DC1E14E3`.
- **Failures and risks:** Local PowerShell policy blocked the first Lite build; a
  one-shot `-ExecutionPolicy Bypass` run succeeded without changing policy. A
  malformed initial secret-scan expression searched path strings and falsely
  reported 13 local paths; `Select-String -LiteralPath` corrected the scan to zero
  sensitive values in changed content. Live generation remained manual. Rolling
  context can raise input tokens, so it is capped. Suggestions remain explicitly
  reviewable because prompt rules cannot guarantee perfect semantics.

## 14. Non-blocking Radar provider confirmation — 2026-07-17 17:19 KST

- **User problem:** Applying a Radar provider made the interface appear frozen
  for about a minute. The user asked whether provider validation was blocking the
  Electron window.
- **User decision:** Keep the external-transmission/cost warning, but allow every
  other caption and translation control to remain interactive.
- **Codex implementation:** Instrumentation showed provider application performs
  only local SDK/key/model availability checks, makes no generation call, and
  responds in 3.3–15.6ms. The real blocker was browser-native `window.confirm`,
  which locks the whole Electron window. It was replaced by a non-blocking two-
  step card flow: first click exposes a warning and “Confirm external API,” second
  click applies. Changing provider cancels pending confirmation. Korean/English
  copy and cache versions were updated.
- **Verification:** Radar/i18n tests `17 passed`. In real Electron there was no
  native modal; the translation provider selector responded in 65ms during the
  pending confirmation, and the second click applied and restored the card in
  about 377ms. Four API timings were 3.3–15.6ms. A stale asset-version test first
  produced `1 failed, 281 passed, 3 skipped`; after version alignment the full
  suite was `282 passed, 3 skipped in 12.96s`.
- **Risk:** The exact one-minute report was not reproduced, but server diagnostics
  remained responsive and the native modal reproduced total control blocking,
  providing a high-confidence cause. No model generation occurred. Destructive
  confirmations elsewhere remained unchanged.

## 15. Safe partial acceptance of Radar evidence errors — 2026-07-17 17:46 KST

- **User problem:** A live `gpt-5.4-mini` test correctly created a quotation-send
  Action, but a later batch contained one nonexistent evidence ID and caused all
  valid decisions/questions in the same response to be discarded.
- **User decision:** Keep evidence safety, but do not reject correct sibling items
  because one model-generated ID is wrong.
- **Codex implementation:** Validate structured results item by item. Remove bad
  IDs from mixed-reference items and accept the item only if at least one real
  current-focus reference remains. Discard only items with no real evidence or no
  focus evidence. Preserve `INVALID_EVIDENCE` when nothing valid remains. Count
  discarded IDs/items in `discarded_evidence_references` and
  `discarded_suggestions`; server warnings contain counts, not meeting text.
- **Verification:** The first test fixture incorrectly placed `null` in a schema
  string field (`1 failed, 12 passed`); after fixing the fixture, Radar tests were
  `13 passed in 0.65s`, including mixed acceptance and all-invalid rejection.
  Full suite: `283 passed, 3 skipped in 13.92s`. A project-scoped restart restored
  Gemini translation and OpenAI `gpt-5.4-mini` Radar; health was `ok`, capture
  `idle`, worker `ready`, Radar `idle`, no error, and discard counters zero.
- **Risk:** A semantically false item can still cite a real focus ID, so approval
  remains necessary. No additional paid call was made. Runtime provider selection
  reset on restart and was restored without starting capture.

## 16. Live-session Radar quality review and cost optimization — 2026-07-17 19:15 KST

- **User problem and decision:** After a completed Radar test, inspect stored
  results for real decision quality and reduce cost. The same test also used an
  OpenAI mini model for translation, increasing request count. Use a mini Radar
  model during iteration, preserve all existing files, retain recall of core
  decisions, and reduce duplicate actions, excessive questions, and repeated
  context.
- **Codex analysis and implementation:** Compared 166 finals, 166 OpenAI-mini
  translations, 44 successful Radar batches, and 28 stored suggestions from the
  latest private session. It captured all four expected core decisions and both
  unresolved questions, but split one job into “do” and “share,” promoted a risk
  into a question, and represented evidence/deferral as separate decisions.
  Owners could not safely be inferred where names were absent from STT; product-
  name spelling was misclassified. Shared prompts now merge related work, let
  later summaries replace weak suggestions, restrict evidence/preferences/risks/
  deferrals, route spelling ambiguity to `needs_confirmation`, and prohibit
  unsupported speaker/owner guesses. Previous items are sent with only comparison-
  essential fields, omitting evidence/timestamps and repeated normalized/source
  text. Defaults changed to ten finals or 20 seconds, 16 context finals, and
  `gpt-5.4-mini`. Diagnostics gained provider attempts, analyzed-focus count, and
  cumulative/average input characters.
- **Verification:** Radar/settings tests `38 passed`; full suite
  `285 passed, 3 skipped in 11.40s`. Offline replay of the 166 finals calculated
  48 calls and 1,038,809 input characters before versus 26 calls and 327,924
  characters after: 45.8% fewer calls and 68.4% fewer input characters. After a
  capture-safe restart: health `ok`, capture `idle`, worker `ready`, OpenAI mini
  translation, `gpt-5.4-mini` Radar `idle`, batch 10, wait 20s, context 16.
  Session artifacts remained 235 files and 3,801,691 bytes, aggregate
  `2F515FFB821C85A24665462E93AF8B64D16995D7FE40BE3DADF8D833B5BE8BD0`.
- **Trade-offs:** The dashboard's 254 requests included at least 166 translations
  and 44 Radar calls; the remainder could include earlier tests. Translation is
  intentionally one call per final for latency, so Radar's repeated context was
  optimized first. Offline replay proves the structural/cost reduction, not the
  live model's precision gain. The 20 seconds is a ceiling; ten finals trigger
  earlier. No extra paid call was made.

## 17. Context Engine relevant-term selection — 2026-07-17 19:45 KST

- **User problem and decision:** Large name/term lists made every translation and
  Radar request heavy. Keep the complete Deepgram keyterm list for STT, but send
  only context-relevant entries to external translation and Radar providers.
- **Codex implementation:** Context normalization now records an exact canonical
  occurrence, not only alias replacements, and deduplicates repeats within one
  final. Capture passes only canonical terms matched in that final rather than the
  entire profile. The translation manager locally searches default, user, and
  recent-context candidates and sends at most ten terms actually present in the
  current sentence or preceding three contexts; it omits the glossary instruction
  entirely when none match. Radar builds at most ten canonical/matched forms from
  actual rolling-context `context_matches`, never the full profile plus aliases.
  Deepgram keyterms and local-translation term protection remain unchanged.
  Diagnostics show candidates examined and terms/context entries transmitted.
- **Verification:** Context/translation/Gemini/Radar tests initially found two
  old assumptions that expected the full unused list; after updating those
  fixtures to the matching contract, `54 passed in 0.99s`. Full suite:
  `287 passed, 3 skipped in 12.13s`. Offline replay of the longest stored private
  session (462 finals) reduced term-entry transmissions from 7,854 to 39 (99.5%).
  Shared translation-instruction text fell from 381,612 to 249,357 characters
  (34.7%), and 423 of 462 requests omitted the glossary block. No meeting text or
  term content was placed in public documentation.
- **Trade-offs:** Matching uses NFKC, case-insensitivity, and alphanumeric word
  boundaries. A term absent from current/recent context is not pre-sent; an STT
  error unlike every registered alias therefore may not reach the translation
  glossary, though Deepgram still receives all canonical/alias keyterms. Only the
  first ten relevant entries are sent. No live API calls were made.

## 18. Installation-free participant invitation links — 2026-07-17 22:43 KST

- **User problem:** Let participants follow the host's local app with near-real-
  time captions and Radar without installation, while controlling disclosure,
  retention, extra latency, past-session exposure, and secrets.
- **User decision:** Never expose local FastAPI directly. Use a separate cloud
  relay and read-only participant site. Share only interim/final source,
  translations, Radar, and evidence IDs—never audio, keys, provider settings, or
  prior sessions. Explicit stop deletes immediately; abnormal exit expires after
  15 idle minutes; room maximum life is eight hours. Show these terms and require
  confirmation before sharing.
- **Codex implementation:** Added a failure-isolated WebSocket auxiliary sink and
  `ShareRelayManager` with an allowlist sanitizer, 256-item bounded queue, 120ms
  batching, finite retries, and 30-second heartbeat. The Sites/Vinext+D1 relay
  separates the room-creation secret from per-room host tokens and stores only the
  current viewer state. The 450ms-polling participant UI displays partial/final,
  translation, Radar, and evidence navigation; it supports Korean/English,
  source+translation/translation-only, and host-connected/ended states. The main
  UI explains sent/not-sent data and retention, requires consent, and exposes
  start/stop/copy/open controls. A newly generated social-preview image became a
  project asset.
- **Changed components:** `backend/app/sharing/`, WebSocket manager, settings,
  schemas, main app, frontend assets/i18n, `.env.example`, `.share.env.example`,
  ignore rules, tests, `viewer-site/`, and `docs/live_share_report.md`.
- **Verification:** Sharing API/WebSocket suite `13 passed`; full suite
  `293 passed, 3 skipped in 19.46s`. Viewer production build, three contract tests,
  lint, and secret scan passed. Local D1 verified room creation → partial/final/
  translation/Radar → read → explicit delete → 410. The real main UI verified
  consent gating, link creation, secret-free diagnostics, and cleanup. Participant
  browser verification covered translation, Radar, evidence navigation, language
  switch, post-end content removal, and zero console errors/warnings. Owner-only
  Sites version 1 passed `200 → create → 3 events → read → delete → 410`. Existing
  sessions remained 254 files, 3,934,097 bytes, aggregate
  `D6A748D68FA5481A360A1189E42BA1C4FFD7951B3963237DF409AC87D786E3EF`.
- **Failures and risks:** Plain Node could not load Cloudflare-only `cloudflare:`
  modules, so production-build contracts and real-browser E2E were separated. A
  missing local Vite binding initially returned 401 and was aligned with
  production. Two PowerShell drafts misused reserved `$Host`/`$Home` variables and
  confused viewer/API URLs; they wrote only disposable test rooms. The official
  Sites packaging wrapper needed bundled Git `sh.exe` because Windows lacked
  `bash`. At this point the deployment remained owner-only; public access still
  required explicit authorization. Anyone holding a room URL can read it, so link
  forwarding and participant consent remain operational risks.

## 19. In-meeting Decision Radar navigation redesign — 2026-07-17 23:41 KST

- **User problem:** Decisions, Actions, unresolved items, and confirmations grew
  in one long column, forcing page-level scrolling; the large translation settings
  card also consumed result space.
- **User decision:** Move translation state into a compact horizontal bar. Navigate
  Radar through Decisions, Action Items, and Unresolved tabs. Follow the latest
  item like captions unless the user is reading history. Keep unresolved items
  available on demand rather than as the default focus. Use the same information
  architecture for host and participant views.
- **Codex implementation:** Added a default **Core** tab combining decisions and
  actions, plus **Decisions**, **Action**, and **Unresolved** tabs. Existing
  `needs_confirmation` items remain in Unresolved. Radar uses a fixed-height inner
  scroll and follows new items only while the reader is at the latest position.
  Scrolling up pauses follow and exposes “N new items · Jump to latest.” Hidden
  tabs update counts and unread dots without forced switching. Translation
  direction/provider/state moved to a full-width compact bar; details are closed
  by default. The participant site received identical tab and follow/pause logic.
- **Verification:** Main UI/i18n/Radar tests `20 passed`; JS syntax passed; full
  suite `293 passed, 3 skipped in 11.35s`. Viewer lint, production build, and three
  contract tests passed. Secret and diff checks passed. Viewer source commit
  `0e9f70a` was pushed and owner-only Sites version 2 deployed. Running FastAPI
  served the new asset version and controls. Session state remained 261 files,
  3,973,717 bytes, aggregate
  `49630F55F63D3782B5C8AA312E40C8B46BCC3449AE41CC3CA364CF62ED53C345`.
- **Trade-offs:** One command ran in the root instead of `viewer-site` and one
  shell lacked bundled Node; both were rerun correctly. Public access was not
  changed. The active local share room was not interrupted by a server restart;
  asset versioning loaded the UI on refresh. Long-meeting usability still needed
  observation.

## 20. Collapsible live-sharing panel — 2026-07-18 01:01 KST

- **User decision:** Make live sharing collapsible like the Context, session, and
  analysis sections so captions and Radar dominate the meeting view.
- **Codex implementation:** Converted it to an accessible, closed-by-default
  `details/summary`. A status badge stays visible when closed; opening reveals the
  existing disclosure, retention, consent, start/stop, and link controls. Reused
  shared Enter/Space and `aria-expanded` behavior and bumped assets.
- **Verification:** JS/i18n syntax passed; targeted tests
  `23 passed in 0.95s`; full suite `293 passed, 3 skipped in 20.54s`. Running
  FastAPI served `liveShareDetails` and `liveShareDetailsBody`. Sessions remained
  275 files, 4,080,347 bytes, aggregate
  `07575DDA52977B0BE9BA07A0766AE238014FE779274576474EB41825219D9EBA`.
- **Trade-off:** An active share does not force the panel open. Users open it only
  to copy or terminate sharing. Long live usability remained a follow-up.

## 21. Equal-height caption/Radar panels with independent scrolling — 2026-07-18

- **User problem:** The left caption list was short with wasted space, while the
  right Radar grew down the page, making simultaneous reading difficult.
- **User decision:** On desktop, both cards use the same viewport-relative height
  and scroll independently. Narrow layouts remain vertical with bounded heights.
- **Codex implementation:** Added viewport-based `--live-panel-height` using
  `clamp()`, removed caption `max-height: 515px` and Radar `max-height: 640px`, and
  applied `min-height: 0`, inner `overflow-y: auto`, overscroll containment, and a
  visible Radar scrollbar. Updated cache versions.
- **Verification:** Targeted tests `28 passed`; full suite
  `293 passed, 3 skipped in 14.10s`; `app.js` syntax passed. Final usability across
  display scaling and very large item counts remained to be observed.

## 22. Newest participant captions pinned to the top — 2026-07-18 01:07 KST

- **User problem and decision:** Participant finals accumulated downward, forcing
  scrolling away from Radar. Always display the newest final first. On each new
  final, reset only the caption list to the top; keep page/Radar position fixed.
  Current partial speech stays above the final list.
- **Codex implementation:** Kept relay state, persistence order, and evidence
  `segment_id` semantics unchanged. Only a copied display array is reversed, and
  caption revision resets its internal `scrollTop` to zero. Returning a user from
  old captions to the newest one is intentional for this read-only view.
- **Verification:** Changed the participant component, rendered-HTML contract,
  documentation, and this log. Viewer lint, production build, three contracts,
  secret scan, and diff check passed. Source commit `a9ee5e5` was pushed and
  owner-only Sites version 3 deployed. Existing sessions/JSONL were neither read
  nor modified.

## 23. Decision Radar item preservation and change history — 2026-07-18 21:05 KST

- **User problem:** Core findings disappeared when later conversation changed
  topics, undermining trust in cumulative meeting memory.
- **Joint decision:** Never treat a model's later judgment as physical deletion.
  Keep active items cumulatively; only explicitly retracted suggestions change
  state, and preserve them in a collapsible change history. Approved or user-
  edited items remain protected from automatic change.
- **Codex implementation:** Upgraded the Radar store to schema v2 with
  `active`, `superseded`, `resolved`, and `retracted` lifecycle states plus reason
  and timestamp. `retract_item_ids` now merges a state transition instead of
  deleting. Prompt rules forbid retraction solely because of topic changes,
  silence, or elaboration. Main UI, detached Radar window, and participant viewer
  count/show only active items in tabs while displaying prior items with evidence
  in Change History.
- **Verification:** Focused Radar/sharing tests `20 passed`; full suite
  `293 passed, 3 skipped`; main and detached-window JS syntax passed; viewer
  production build passed. Viewer commit `d66364e` was deployed as owner-only Sites
  version 4. Missing lifecycle data is read as `active` for backward compatibility.
- **Risks:** A first viewer build ran from the wrong root and was rerun correctly.
  History is capped at 200 items for memory/share bounds. Retraction frequency and
  readability in very long meetings remained observational follow-up work.

## 24. Language-aware Deepgram utterance assembly — 2026-07-18 22:18 KST

- **User problem:** Four-second forced finals split Japanese dates, modifiers, and
  predicates, producing unnatural translations and causing Radar to interpret a
  deadline in the next fragment as unresolved. Japanese and English were using
  identical segmentation settings despite different utterance structure.
- **Joint decision:** Separate screen responsiveness from translation accuracy.
  At four seconds, show only a stable partial. Automatically select Japanese
  `500ms/1300ms/8s`, English `400ms/1000ms/6s`, and initial Korean
  `450ms/1200ms/7s` endpoint/utterance/soft-limit profiles from translation
  direction. Create translation finals at actual utterance or sentence/clause
  boundaries and force only at a ten-second hard ceiling.
- **Codex implementation:** A Deepgram `Finalize` response marked
  `from_finalize` no longer becomes a product final immediately; it accumulates as
  a stable partial in the same utterance buffer. Emit one final on
  `speech_final`, `UtteranceEnd`, strong punctuation, a clause boundary after the
  language soft limit, or the ten-second hard limit. Japanese fragments join
  without inserted spaces; English keeps word spaces. Added language settings,
  legacy global fallbacks, effective-profile diagnostics, and migrated only the
  non-secret timing values in the user's `.env`.
- **Verification:** Focused Deepgram/settings/translation/Radar suite
  `63 passed`; full suite `298 passed, 3 skipped in 12.03s`. Runtime settings
  loaded `ja=(500,1300,8)`, `en=(400,1000,6)`, `ko=(450,1200,7)`, checkpoint 4,
  and hard limit 10.
- **Risk:** A first full run found one stale i18n cache-buster from the prior UI
  work; aligning all three asset versions fixed it. Korean timing remained an
  unmeasured initial value. Live human-speech A/B was still required.

## 25. Deepgram boundary-operation hardening — 2026-07-18 22:45 KST

- **User problem and decision:** Four-second forced finals can cut Japanese
  context, but waiting for a 20–30 second uninterrupted speaker makes translation
  unusably late. Use four seconds only for interim display, keep the language
  profiles above, and use ten seconds only as the no-boundary hard ceiling.
- **Codex implementation:** Removed periodic four-second `Finalize` transmission.
  Product finals now come from `speech_final`, `UtteranceEnd`, punctuation, or
  language-specific soft clause boundaries. Hard-finalize requests retain reason
  and audio boundary so late responses cannot become an incorrect final. Empty
  replies, no-reply watchdogs, late duplicates, and trailing interim on shutdown
  are handled safely. Japanese defaults to no inserted spaces; English and Korean
  preserve word spaces. Translation and Radar continue to receive finals only.
- **Compatibility:** If `HARD_LIMIT` is omitted, it expands to
  `max(10s, every language MAX)` so legacy values above ten seconds do not prevent
  startup. An explicit hard limit below a soft profile is rejected. Diagnostics
  expose the translation-direction-selected profile in `stt_runtime`.
- **Verification:** Timing-state regression `32 passed`; Deepgram/settings-
  security suite `51 passed`; full suite
  `310 passed, 3 skipped in 15.03s`. Existing sessions and JSONL were neither read
  nor changed.
- **Remaining measurement:** State-machine and deduplication behavior were
  automated; real Japanese/English prosody, network latency distribution, and
  perceived caption speed could still tune the soft limits.

## 26. Selective local Whisper transcription recheck — 2026-07-19 00:11 KST

- **User problem:** A short Deepgram `speech_final` ending in a Japanese particle,
  English conjunction, or Korean connective ending can be semantically incomplete
  and poison translation/Radar. Re-transcribing everything would add excessive
  CPU load and delay.
- **Joint decision:** Immediately finalize complete sentences and legitimate short
  replies such as “hai,” “yes,” or their Korean equivalent. Hold only structurally
  incomplete `speech_final` fragments until the next result, `UtteranceEnd`, or a
  1.5-second maximum wait. Classify word confidence, fragment length, incomplete
  ending, and forced boundary as risk reasons. Recheck only risky sentences with
  an already cached local Whisper model. Never auto-download a model, save audio,
  or rewrite existing sessions.
- **Codex implementation:** Collected word-level confidence and absolute time
  offsets and added Japanese/English/Korean completeness rules and a candidate-
  merge state machine. A roughly 14-second PCM16 rolling buffer exists in memory
  only and does not duplicate reconnect-replayed audio. Recheck uses CPU `int8`,
  `beam_size=1`, concurrency one, queue capacity two, and about a four-second
  ceiling. Missing cache, load failure, inference failure, or timeout immediately
  preserves the Deepgram result. When outputs disagree, Whisper is selected only
  if it clearly completes an incomplete sentence or has stronger evidence from
  approved Context Engine names/terms.
- **Source and delivery contract:** `FinalTranscript` and past JSONL formats did
  not change. New sessions append `transcription_quality` events containing the
  original Deepgram text and selection outcome for audit. If
  `save_original=false`, all text is removed from that event too. Deterministic
  correction of approved terms, names, and aliases happens after transcript
  selection. Translation and Radar receive the same finalized `segment_id`
  exactly once.
- **Diagnostics:** `server.stt.selective_recheck` exposes enablement, cache-only
  policy, model, in-memory bytes/seconds, queue length, requested/adopted/failed/
  timed-out/skipped counts. Environment and README documentation cover wait,
  model, buffer, timeout, queue, local-files-only behavior, and fallback.
- **Verification:** Automated Japanese, English, and Korean fragment joining;
  immediate short replies; one final on `UtteranceEnd`; partial/final dedup;
  confidence risk; Context raw-source preservation; Whisper adoption and cache-
  missing/failure/timeout fallback; text removal in non-saving sessions;
  reconnect audio offsets; and the 14-second ring. Focused suite
  `54 passed in 9.86s`; full suite
  `327 passed, 3 skipped in 17.33s`; `compileall` and four frontend Node syntax
  checks passed. `FasterWhisperEngine('small', prefer_cuda=False,
  local_files_only=True).ensure_loaded()` loaded the existing CPU-int8 cache with
  no download. Session state stayed 345 files, 4,713,890 bytes, aggregate
  `AF7B82ACB755A0E63ED6D43F980DB6E27E86A829E06BE5D44F9F1EBF1634018F`.
- **Risks:** No paid Deepgram/human-audio run occurred in this step. Native
  faster-whisper inference cannot be killed when a Python timeout expires; the app
  proceeds with Deepgram and skips new rechecks until the old thread exits. This
  protects transcription/translation/Radar but reduces recheck coverage under
  sustained overload.

## 27. Deepgram Nova-3 + Gemini live meeting validation — 2026-07-19 00:41 KST

- **Goal and setup:** With user authorization for paid Deepgram, validate real
  sentence boundaries, word confidence, selective local Whisper, and Gemini
  latency/quality using about one minute of a public Japanese Zoom meeting played
  through system audio. Codex restarted the latest server and confirmed Deepgram
  Nova-3, Japanese→Korean, Gemini `gemini-3.1-flash-lite`, loopback capture, and
  local Whisper `small/cpu/int8`. The user played
  <https://www.youtube.com/watch?v=-3YHidnEqx4>. Evaluation session
  `2026-07-19_00-30-00_0e635f` was 76.669 seconds with 13 finals. A separate
  196.530-second, zero-segment setup session was excluded.
- **Integrity:** The evaluation produced exactly 13 each of `final_transcript`,
  `transcription_quality`, `context_normalization`, and `translation`, with 1:1
  `segment_id` matches. No duplicate final, missing translation, queue residue,
  storage warning, or audio file existed. Deepgram reported no error/reconnect/
  dropped audio; capture dropped zero frames. Radar was intentionally off.
- **Gemini latency:** 13/13 translations succeeded. Provider latency: minimum
  590ms, median 675ms, mean 710.9ms, maximum 918ms. Audio-end to stored
  translation median was 2.716s overall, 1.827s for eight normal sentences, and
  3.717s for five Whisper-rechecked sentences. Gemini consumed about 0.6–0.9s;
  local recheck dominated additional risky-sentence delay.
- **STT/recheck quality:** Five of 13 were risky (`low_word_confidence` four,
  `short_fragment` one). Rechecks took 1.328s minimum, 1.426s median, 2.987s
  maximum, with no failure/timeout/queue skip and zero adoptions. Whisper clearly
  improved one malformed Japanese greeting, showing the adoption rule was overly
  conservative; it degraded other cases through word substitution, speaker-text
  deletion, or altered reply semantics, showing that loose whole-sentence
  replacement would also reduce quality.
- **Boundary and translation findings:** A short temporal adverb was finalized by
  `UtteranceEnd` and separated from the following thanks; a connective ending was
  also left alone. The existing hold rule did not cover false `UtteranceEnd`.
  Gemini recovered most core meaning naturally despite STT errors, but an isolated
  connective and the split temporal phrase remained awkward. Exact WER was not
  claimed because no machine-readable reference transcript was available.
- **Data integrity:** Excluding the newly authorized setup/evaluation artifacts,
  the original 345 files, 4,713,890 bytes, and aggregate
  `AF7B82ACB755A0E63ED6D43F980DB6E27E86A829E06BE5D44F9F1EBF1634018F`
  were unchanged.
- **Next candidates:** Give incomplete `UtteranceEnd` a 0.6–1.0s grace; extend
  Japanese connective/temporal-adverb rules; align only low-confidence spans
  rather than replacing whole sentences; and test immediate source display with
  later translation update. Product code was intentionally not changed during
  this measurement.

## 28. Deepgram Nova-3 + OpenAI live-meeting follow-up — 2026-07-19 00:56 KST

- **Goal:** Compare a user-completed OpenAI run of the same public meeting region
  against the Gemini run, separating provider latency from STT boundary/recheck
  delay. No additional paid call was made.
- **Comparison limits:** OpenAI: 75.954s, eight finals. Gemini: 76.669s, 13 finals.
  Start point and boundary decisions differed, so sentence-level rankings were not
  asserted; provider latency, faithfulness to each received source, and common
  semantic regions were compared separately.
- **Integrity:** OpenAI produced eight each of final, quality, normalization, and
  translation with 1:1 IDs and no loss, duplication, warning, or audio file.
  Diagnostics: reconnect 0, audio drop 0, frame drop 0, translation queue 0,
  rechecks 4, adoption/failure/timeout/skip all 0.
- **Latency:** OpenAI `gpt-4o-mini` provider latency was 1.116s minimum, 1.887s
  median, 2.124s mean, and 4.000s maximum (the cold first call). Against Gemini's
  prior 675ms median, OpenAI was about 2.8× slower in this region. Audio-end to
  translation median was 6.243s versus Gemini's 2.716s. However, pre-translation
  finalization/quality time was also 4.433s versus 1.871s, so not all end-to-end
  difference belongs to OpenAI.
- **Quality:** OpenAI was natural on complete long utterances but showed no
  consistent quality advantage. A split auxiliary phrase became incompatible
  tenses across two finals, a verb-root split became a completed past event, and
  a greeting exchange compressed multiple replies. Some Gemini awkwardness was
  directly caused by Deepgram source errors. The primary bottleneck remained STT
  and sentence boundaries, not the translator model.
- **Patch priority derived:** Preserve hard `Finalize` as a `hard_limit` risk even
  when Deepgram labels the reply `speech_final`; grace incomplete
  `UtteranceEnd`; strip punctuation before testing Japanese connectives; display
  forced/incomplete source immediately but deliver one canonical final; align and
  replace only safe low-confidence spans; separately measure Deepgram receive,
  assembly wait, recheck, translation queue, provider, and browser paint; compare
  providers on identical stored text; background-initialize selected SDK clients
  without blocking settings.
- **Trade-offs:** Prompt shortening or fewer context segments cannot repair the
  main boundary error. A paid warmup request would hide first-call latency but add
  cost/disclosure and was not recommended. This entry records analysis only.

## 29. STT and translation latency patch after the live comparison — 2026-07-20 12:13 KST

- **Joint decision:** Finalize complete speech immediately; briefly hold only
  semantically incomplete speech. Show risky source as an interim caption during
  recheck, but deliver only one canonical final to storage, translation, and
  Radar. Allow only conservative low-confidence-span Whisper corrections. Keep
  provider comparison as an explicit separate tool using identical text.
- **Boundary hardening:** Incomplete `UtteranceEnd` now waits with language grace:
  Japanese 0.9s, English 0.7s, Korean 0.8s. Japanese temporal adverbs, connective
  particles, and connective endings are checked after stripping punctuation;
  legitimate short replies finalize immediately. A hard `Finalize` reason wins
  even when the response is marked `speech_final`. On hold timeout, the newest
  interim is merged. Timestamps remove already-finalized prefixes from late stable
  replies, retaining only unseen suffixes.
- **Recheck and delivery:** Risky finals first broadcast `quality_review` interim.
  Word-confidence positions align Deepgram and Whisper, allowing only small safe
  insertion/substitution, while rejecting semantic deletion, lost clauses, and
  unsupported character changes. Forced/incomplete metadata reaches translators
  so they do not invent tense, decisions, or sentence closure. Original Deepgram
  text and selection reason remain only in new append-only quality events; past
  `FinalTranscript` and JSONL stay unchanged.
- **Latency diagnostics and provider preparation:** Added recent/mean/max STT
  audio-end→provider-receive and canonical-processing metrics, plus translation
  queue/provider/total metrics. Selected OpenAI/Gemini SDK clients initialize in
  the background; reads/applies neither await them nor generate content. Local
  settings reads were 18ms cold then about 4–6ms, Gemini apply 125ms, OpenAI apply
  158ms, and the slowest provider-switch cleanup 740ms, with zero generation
  calls.
- **A/B tool:** Added `scripts/compare_translation_providers.py`, sending one
  UTF-8 sentence per line to OpenAI and Gemini concurrently without context,
  session persistence, or automatic retries. It requires both
  `RUN_TRANSLATION_AB_TEST=1` and `--confirm-external-calls`. Automated validation
  exercised only the refusal path.
- **Verification:** Focused STT/recheck/translation/API suite `106 passed`;
  provider-preparation suite `45 passed`. A Windows timer edge reporting 0ms queue
  wait was clamped to at least 1ms and passed 20 consecutive runs. Full suite:
  `339 passed, 3 skipped in 21.08s`. `compileall`, four frontend syntax checks,
  and dual-authorization refusal passed. Restarted server and worker had distinct
  ready PIDs and exposed the new grace/latency diagnostics.
- **Data integrity and remaining measurement:** Sessions remained 364 files,
  4,810,055 bytes, aggregate
  `8F263043093F9A4527F9A3DB575C53A26831118BF4355EB018E9CB87B7829290`.
  No new paid STT/translation call was made in this patch step. The next live A/B
  would inspect boundary error count, local correction adoption, and audio-end→
  translation completion. Browser paint remained a separate future metric.

## 30. Ten-sentence OpenAI/Gemini identical-input A/B — 2026-07-20

- **Experiment:** With explicit user approval, sent ten identical context-free
  synthetic Japanese meeting sentences to OpenAI and Gemini. The fixture contained
  decisions, owners, deadlines, an unresolved cost, and a follow-up meeting. It
  bypassed sessions, JSONL, and Radar.
- **Tool defect found:** Both providers completed the first run, but a Windows
  CP949 console failed while printing Japanese JSON. Because the calls had already
  happened, rerunning added one unplanned request set. The CLI now forces UTF-8 on
  stdout/stderr. No key, prompt, or response was added to product logs.
- **Second-run results:** OpenAI `gpt-4o-mini` succeeded 10/10; provider latency
  median 1,132ms and mean 1,212.5ms. Gemini `gemini-3.1-flash-lite` succeeded
  6/10; successful latency median 721ms and mean about 756.7ms. Four safely failed
  with `GEMINI_QUOTA_EXHAUSTED`. First-sentence total time, including cold client
  creation, was 3,277ms OpenAI and 2,771ms Gemini and was kept separate from
  provider latency.
- **Quality:** On the six shared successes, Gemini was slightly more concise and
  natural in some meeting phrasing; OpenAI generally preserved meaning, owners,
  dates, and times. One OpenAI output visibly retained untranslated Japanese; the
  other nine were practically understandable. Successful-result naturalness
  slightly favored Gemini, while this free-quota run's availability clearly
  favored OpenAI.
- **Interpretation:** Gemini's successful median was about 36% lower, but shared
  free quota across translation and Radar risked missing segments. The product's
  source-first fault isolation therefore remained necessary. This single
  synthetic run did not establish a universal ranking. The UTF-8-fixed CLI printed
  Japanese source and Korean output correctly, required the dual consent gates,
  cleared the approval variable afterward, and did not modify session storage.

## 31. NVIDIA Riva Translate 4B added to the A/B harness — 2026-07-20

- Added hosted `nvidia/riva-translate-4b-instruct-v1.1` as a third target in the
  explicit comparison tool only; it was not registered in the product UI or
  default translation path.
- Used NVIDIA's official OpenAI-compatible Chat Completions endpoint with
  `temperature=0`, zero automatic retries, and a 512-token per-sentence output
  ceiling. Inputs remain the same context-free fixture and never enter sessions or
  JSONL.
- The dual external-transmission consent gate applies to all three providers. A
  missing `NVIDIA_API_KEY` was confirmed to reject the whole comparison at health
  check before any translation request.
- Unit tests covered success, exact model/language prompt, missing key, empty
  output, and client close. A live NVIDIA quality/latency run remained optional.

## 32. Paid Gemini 3.1 Flash-Lite versus OpenAI rerun — 2026-07-20

- With explicit approval after the user's Gemini account moved to paid billing,
  sent the same ten context-free Japanese meeting sentences concurrently to
  `gpt-4o-mini` and `gemini-3.1-flash-lite`, without session/JSONL persistence.
- Both providers succeeded 10/10; the four prior free-quota Gemini failures did
  not recur.
- Provider latency: OpenAI median 1,280.5ms, mean 1,468.2ms; Gemini median 636.5ms,
  mean 731.0ms. Gemini was faster including the first request and about 2.0× faster
  by warm median.
- Both preserved dates, times, decision state, and unresolved state. Gemini more
  directly preserved the modifier relationship for “three companies” and the
  revised quotation; OpenAI rendered “progress meeting” more naturally. Overall
  quality was comparable with a slight Gemini edge, while latency and uninterrupted
  success favored Gemini in this run.
- Added `--providers openai gemini` selection so approved providers can be tested
  independently when no NVIDIA key exists. The default remains all three.

## 33. Multilingual English-demo conversion and public-submission foundation — 2026-07-20 15:23 KST

- **User decision:** An English-speaking judge should see immediately
  understandable output rather than Japanese→Korean. First add and validate
  Japanese→English and English→Japanese; record the final public Replay as Korean
  source→English translation with English Decision Radar.
- **Translation directions:** Added `ja_to_en` and `en_to_ja` to settings, API
  schemas, capture controller, and Korean/English UI. Both may use local Whisper or
  Deepgram STT, but the existing Korean-target M2M100 worker is incompatible, so
  capture requires an applied Gemini/OpenAI translator. Korean-source directions
  remain Deepgram-only. One contract now validates source/target language for all
  six directions. Existing `.env` defaults were not changed.
- **Radar language:** Added target language to final WebSocket/Radar payloads and
  provider prompts. Korean, English, and Japanese result instructions use separate
  unknown-value labels. Events without target language remain backward-compatible
  and default to Korean. Korean→English demos therefore generate English decisions,
  actions, and unresolved items as well as English translation.
- **Live translation validation:** An explicit non-session tool sent two Japanese→
  English and two English→Japanese sentences once each to Gemini
  `gemini-3.1-flash-lite`. All 4/4 succeeded in 733–952ms, median 843ms, preserving
  names, a Friday 3 PM deadline, an August 20 decision, and unresolved monthly
  server cost. Temporary inputs were removed and sessions remained untouched.
- **Replay/export changes:** The exporter validates the session's real
  `translation_direction` against each translation target and writes the pair to
  the public fixture. UI language badges follow fixture metadata. Added a public
  Korean→English synthetic meeting script and expected evaluation signals, with an
  explicit rule that real provider output must not be rewritten into an ideal
  answer. Tests verify private IDs/path removal, evidence integrity, direction,
  and original fixture hash invariance.
- **Repository preparation:** Added English README, MIT License, privacy/failure-
  isolation/Codex/GPT-5.6/before-after documentation. Git excludes work files,
  secrets, PIDs, runtime, models, virtual environments, sessions, and local
  Context/Radar stores. The nested viewer history was preserved as a verified
  private Git bundle outside the project, then removed to create one root
  repository. Lite allowlists gained the English README and License.
- **Verification:** Direction/Radar/Replay suite `53 passed`; full suite
  `352 passed, 3 skipped in 18.67s`. `compileall`, seven frontend/Electron/Replay
  JS checks, viewer production build, and viewer tests `7/7` passed. Recomparison
  of the 85 pre-work JSONL paths, lengths, and SHA-256 values found zero changed or
  missing.
- **Status at this point:** Korean Windows TTS was unavailable, so the final
  60–90 second Deepgram run had not happened. `Build Week Demo EN` profile and
  script were ready and the prior active profile was restored. The public fixture
  still represented an earlier Japanese→Korean run and was not claimed as final.
  GitHub CLI was not yet installed, so remote repository, push, and Release were
  pending.

## 34. Verified Korean-to-English Replay and Luna selection — 2026-07-20 17:00 KST

- **Final model decision:** Fix the English-judge demo pipeline as
  **Deepgram Nova-3 Korean transcription → approved Context Engine normalization →
  Gemini 3.1 Flash Lite English translation → GPT-5.6 Luna English Decision
  Radar**. Do not use Terra in the final demo.
- **Luna versus Terra:** On the same 13 finals, Terra created nine items
  (3 decisions, 5 actions, 1 unresolved); Luna created 12
  (3 decisions, 6 actions, 3 unresolved), all with valid evidence IDs. The
  comparison made three Terra external requests, after which Terra calls stopped.
- **Actual audio run:** With user-approved paid Deepgram and selected Gemini/OpenAI
  providers, ran a non-private 89.04-second synthetic work meeting. It produced 13
  finals and 13 English translations. Translation-provider latency median was
  843ms, p95 1,172ms, maximum 1,265ms.
- **Final Radar:** Revision 4 produced ten items: 3 decisions, 4 actions, and 3
  unresolved questions. All 10/10 `evidence_segment_ids` existed in the public
  source segments, with zero missing evidence. Provider output was not rewritten
  as an ideal answer.
- **STT hardening:** Added `malformed_date_format` risk for high-confidence Korean
  dates malformed by Deepgram smart formatting. Cached local Whisper can be
  chosen only when it provides a valid explicit date while preserving sentence
  structure; original Deepgram output remains in append-only quality metadata.
  Translation prompts explicitly describe Korean numeric-date particle boundaries.
- **Public fixture:** Exported 43 relative-time events spanning 112,637ms to
  `viewer-site/public/demo/verified-session.json`, removing private session IDs,
  internal paths, keys, and original segment IDs. Audio was never stored in a file,
  JSONL, or fixture. `/demo` runs without providers or keys and supports play,
  pause, restart, 1×/2×, and evidence navigation.
- **Browser verification:** Opened landing and `/demo` without login and confirmed
  Nova-3, Gemini 3.1 Flash Lite, GPT-5.6 Luna, median/p95 values, 10/10 evidence,
  and Replay controls. Clicking evidence produced exactly one highlighted source;
  console errors and warnings were zero.
- **Regression and packaging:** Python
  `358 passed, 3 skipped in 20.23s`; seven JS syntax checks, viewer lint/build,
  and seven Replay tests passed. A scan of 236 Git candidates found zero key
  patterns, user paths, or private session IDs. Lite ZIP: 355,155 bytes,
  112 entries, zero prohibited entries, one manifest, SHA-256
  `FA0326E19D21962AE711801EAC648CED73A86FD0CEB16F6E45FE5C3D1FA5F9E5`.
  In a fresh directory, `setup.bat /no-local → start_all.bat → stop_all.bat`
  produced health `ok`, a recorded server PID, and zero listeners/PID files after
  stop.
- **Existing-data integrity:** Rechecked all 216 pre-work session files, including
  91 JSONL files: zero changed and zero missing. Another 32 files came only from
  later user-approved live-provider/demo validation and are excluded from Git and
  Lite distribution.

## 35. Public repository and Sites production deployment — 2026-07-20 17:18 KST

- Re-scanned 236 public candidates immediately before commit: zero real API keys,
  local user paths, private demo session IDs, or files over 5 MiB. `.env`,
  `.share.env`, sessions, logs, PIDs, models, environments, `node_modules`, local
  Sites DB, and build caches remained untracked.
- Created initial verified commit
  `5d2d1670dcb85da54cea152dbacb5d4ec4881a30` and pushed `main` to the public
  `HANWOOLPARK/meeting-live-translator` repository. No nested Git repository
  remained; `viewer-site` source is in the same commit.
- Did not force-push old Sites history. A fast-forward commit
  `1c2b2824befb5e31be3bfa5b66e345398bba997b`, whose tree exactly matched the
  verified viewer subtree and whose parent was the prior remote HEAD, was pushed.
  Short-lived source credentials existed only in a command-scoped HTTP header and
  were not stored in URLs, Git configuration, or files.
- The official plugin packaging helper bundled the same `dist`, hosting metadata,
  and D1 migration as Sites version 5: 52 files, 3,399,680 bytes. Under the
  user-approved submission plan, access changed to `public` and that version was
  deployed to production.
- Unauthenticated, keyless HTTP checks returned 200 for
  <https://meeting-live-translator-viewer.bakbaul.chatgpt.site> and `/demo`, with
  Replay entry and body present. A secret-free `POST /api/rooms` correctly returned
  401. The local viewer dev server was stopped after verification.
- **Relay security:** No key is in the public repository. The room-creation secret
  was rotated to a fresh 256-bit random value and stored only in local
  `.share.env` and Sites secret environment revision 2, followed by a version-5
  redeployment. A temporary-room E2E passed
  `201 create → 200 read → 200 delete → 410 confirmed deleted` without printing
  room text or host token. Any Gemini key previously visible in a screenshot or
  conversation still had to be revoked and replaced by the user in Google's
  provider console.
- Published GitHub Release `v1.0.0-build-week`, neither draft nor prerelease, with
  the Lite ZIP. Unauthenticated repository and release pages returned 200. A
  memory-only redownload was 355,155 bytes and matched local SHA-256
  `FA0326E19D21962AE711801EAC648CED73A86FD0CEB16F6E45FE5C3D1FA5F9E5`.
- Restored the user's pre-demo Context profile. The process-only Luna demo server
  was stopped, and the unchanged `.env` was restarted normally. FastAPI health was
  `ok`, the local translation worker `ready`, and server/worker/desktop each ran
  under its own project PID.
- Remaining user-account steps were the Devpost video, real `/feedback` Session
  ID, final form submission, and confirmation that any previously exposed Gemini
  credential had been rotated.

## 36. English submission-document conversion — 2026-07-20 KST

- The 635-line Korean development log was archived byte-for-byte as
  [`BUILD_WEEK_LOG_KO.md`](BUILD_WEEK_LOG_KO.md) before the English canonical log
  was created.
- The English version preserves the baseline boundary, chronological product
  decisions, model/provider names, measured latency, test counts, commit IDs,
  release/package hashes, data-integrity hashes, failures, trade-offs, and pending
  submission steps. Korean UI labels and transcript examples were expressed in
  English so judges can read the document without a separate translation.
- `README.md` links to this canonical English record; `README_KO.md` links to the
  preserved Korean archive.
- This documentation-only change does not read or modify session data, JSONL,
  provider configuration, runtime PIDs, or application behavior.

## 37. Synchronized scripted audio for the public Replay — 2026-07-20 18:59 KST

- **User problem and decision:** The keyless Replay was difficult to understand
  without hearing the Korean source. The user explicitly approved a 76.61-second
  recording of the fictional Build Week script for the public demo. Live meeting
  audio remains outside the product's persisted session format.
- **Actual pipeline validation:** Ran the same scripted recording through paid
  Deepgram Nova-3 Korean STT, approved Context normalization, Gemini 3.1
  Flash-Lite English translation, and GPT-5.6 Luna Radar. Context aliases were
  refined only from repeatable STT forms; neither translations nor model output
  were rewritten after generation. The selected run produced five finalized
  segments, five translations, five visible context corrections, and 12 Radar
  items: three decisions, six actions, and three open questions. All 12 evidence
  references resolved to public finalized segments.
- **Measured result:** Selected-run translation latency was 610ms minimum,
  1,078ms median, 1,141ms nearest-rank p95, and 1,141ms maximum. The public event
  timeline was shifted by the measured 1,903ms capture-to-playback offset. The
  bundled 96kbps mono MP3 is 919,721 bytes and 76,610ms, SHA-256
  `96870E48C9AEDF776AC912EED27E37DED2A0D8E7F6B44E6F9A0C4D41740F089F`.
- **Replay implementation:** Added optional audio metadata and timing offset to
  the sanitizer/exporter, with site-relative URL and SHA-256 validation. `/demo`
  now starts only after a user gesture, keeps audio and events on one clock,
  supports play/pause/restart/seek, 1×/2×, mute, and volume, then continues the
  short post-audio Radar tail. Disclosure distinguishes the consented fictional
  demo asset from private meeting audio and local session storage.
- **Privacy and authenticity:** The selected local session kept `save_audio=false`.
  The public fixture contains no original session/segment identifiers, API keys,
  local paths, host token, or relay secret. Original Deepgram text and approved
  normalization remain separately visible; residual recognition imperfections
  were not hidden or converted into an ideal answer.
- **Failures and trade-offs:** Early Windows playback setup attempts failed before
  audio started and created no usable public data. A later Deepgram connection
  attempt with a larger alias profile failed before playback with
  `connection_failed`; the prior successful run was retained. The isolated pnpm
  install blocked unapproved native build scripts and generated a temporary
  policy placeholder, which was removed; installed local binaries completed the
  checks. The first Replay test run also lacked Git's untracked empty preview
  directory; recreating that empty directory produced 7/7 passes.
- **Verification:** Replay exporter tests `3 passed`; full Python suite
  `359 passed, 3 skipped in 17.87s`; Python compileall passed; viewer lint and
  production build passed; Replay tests `7/7` passed. Fixture/audio SHA-256,
  evidence integrity, private-pattern scanning, and `git diff --check` passed.
  Work was isolated from the user's unrelated uncommitted main-worktree changes.
- **Publication:** Feature commit `6eb6b4607970a3b7e70759037d6988758de1711f`
  was pushed in PR #2. The exact viewer tree was fast-forwarded to the Sites
  source as `d64ee43c24a93967d790ab1ffe4868f469411b60`, saved as Sites version 6,
  and deployed successfully to the existing public URL. Anonymous checks returned
  200 for `/` and `/demo`; the deployed MP3 was 919,721 bytes with the expected
  SHA-256; a secret-free room creation request remained denied with 401.
## 38. Email-verified participant links and per-link access audit — 2026-07-20 18:27 KST

- **User problem:** A public participant link could be opened by anyone who
  obtained the room URL, and the host could not tell which recipients had
  actually entered. The requested product contract was external-recipient access
  without installation, an email plus verification-code gate before viewing, and
  a link-specific access record for the host.
- **Product decision:** Keep the Sites application public but make every live room
  fail closed behind an application-owned email OTP. A link alone grants no room
  state. Separate short-lived authentication data from the meeting relay text:
  raw codes are never stored, OTP challenges are retained for at most 24 hours,
  relay text still deletes on stop/expiry, and verified-email/access audit data is
  retained for 30 days. Raw IP addresses are replaced with a secret-keyed HMAC.
- **Authentication implementation:** Added six-digit cryptographically generated
  codes, a ten-minute expiry, five-attempt lock, 45-second resend interval,
  15-minute per-email/per-IP limits, HMAC-bound code hashes, constant-time hash
  comparison, one-time challenge consumption, and room-scoped
  Secure/HttpOnly/SameSite=Strict viewer sessions. The room-state endpoint now
  returns 401 before verification; host bearer access remains available. Logout,
  room stop, hard expiry, and session expiry deny further content access.
- **Delivery and fail-closed boundary:** OTP mail uses the Resend HTTPS API with an
  idempotency key and a sending-only runtime credential. Room creation is rejected
  with a safe configuration error unless a valid sender, API key, and at least
  32-character signing secret are available. The key is never accepted by the
  browser or stored in source. Production requires a user-owned verified sender
  domain; no live mail was sent during this change because those external
  credentials were not available.
- **Audit implementation:** D1 now separates challenges, viewer sessions, and
  access events. The host-token-only access-log endpoint aggregates verified
  email, first verification, last seen, active-within-60-seconds state, view
  count, and bounded events per room. The local FastAPI relay fetches this record,
  shows it in the collapsible sharing panel, polls every ten seconds while active,
  and saves a secret-free final copy under `data/share-access`. These files are
  ignored by Git, pruned after retention, and never modify session JSONL.
- **Participant and host UX:** The viewer now shows a Korean/English email entry
  and one-time-code screen before any caption/Radar polling begins. It discloses
  Resend delivery and the 30-day audit retention, survives refresh with the secure
  cookie, and provides sign-out. The host panel adds link history, verified and
  rejected counts, attendee email, first/last access, active state, manual refresh,
  and the new retention/authentication consent boundary.
- **Changed components:** `viewer-site/lib/access-auth*.ts`, room auth/access-log
  routes, protected room route, D1 schema and migration `0002`, viewer UI/CSS and
  tests, `backend/app/sharing/manager.py`, local share API, host HTML/JS/CSS/i18n,
  sharing tests, ignored audit directory, runtime examples, READMEs, live-share
  report, and this record.
- **Actual verification:** Targeted sharing/UI/i18n tests passed `24/24`. Full
  Python regression and compile check passed `359 passed, 3 skipped`; the skips
  remain the explicitly gated live OpenAI analysis, OpenAI translation, and local
  translation tests. Viewer ESLint had zero warnings, production build succeeded,
  and all 12 Node tests passed, including OTP generation/hash/cookie contracts.
  A local Vinext+D1 route run passed `anonymous room 401 → auth status false →
  invalid challenge 400 → host room 200 → host audit 200 → delete 200 → ended
  410`; its exact Node PID tree and test port were cleaned. The 456 existing
  session files, including 107 JSONL files and 5,600,489 bytes, retained aggregate
  SHA-256 `9263139A75FE0108382864618ED3D9A489C7BD280120D636EBE188AA46456DE8`
  before and after the final regression.
- **Failures, trade-offs, and remaining step:** The first local dev harness timed
  out while requesting the IPv4 address even though Vinext had bound IPv6
  localhost; its exact PID/port were cleaned. A second script incorrectly attached
  an empty body to GET and failed in PowerShell before the product route; it was
  corrected. Direct `vinext start` remains unsuitable for this Cloudflare-targeted
  build because Node cannot load `cloudflare:` URLs, so the successful runtime
  check used Vinext dev+D1 as in prior relay verification. The existing Sites
  version remains live and unchanged: deploying the new fail-closed version before
  configuring a verified Resend sender would disable new room creation. Final
  production deployment and real code-receipt/refresh/log/stop E2E therefore wait
  for the user's verified sender domain and sending-only Resend key.
- **Codex/GPT-5.6 collaboration evidence:** In this Codex task, the user's access
  requirement was decomposed into link entropy, verified identity, brute-force and
  resend limits, session scope, privacy retention, host observability, failure
  isolation, and deployment safety. The implementation and evidence above were
  produced without inventing a Devpost session ID or claiming an unrun live-email
  test.

## 39. OTP production release attempt and safe rollback — 2026-07-21 KST

- **User action:** The user configured the Resend test sender and a local API key,
  authorizing the pending production deployment and live delivery check.
- **Pre-deploy verification:** The secret file remained untracked, its values were
  never printed, the Viewer production build and ESLint passed, all 12 Viewer Node
  tests passed, `git diff --check` passed, and the deployment-source secret scan was
  clean.
- **Release attempt:** Sites runtime revision 3 received the Resend key, test sender,
  and a newly generated 48-byte OTP signing secret while preserving the existing
  relay-create secret. Viewer version 7 was saved from the exact pushed source and
  deployed successfully with the D1 OTP migration.
- **Production probe:** Room creation returned 201 with `access_control=email_otp`,
  anonymous room-state access returned 401, auth status returned 200 with delivery
  configured, and the host-only access-log endpoint returned 200. The OTP request
  returned 503 because a direct safe Resend diagnostic reported `401 API key is
  invalid`; no key value was logged or persisted in source.
- **Recovery:** To avoid leaving all participant links unable to authenticate, the
  three OTP mail variables were removed from Sites, the previous stable Viewer
  version 6 was redeployed with environment revision 4, and the known test room was
  deleted successfully. The existing relay-create secret was preserved. One empty
  room created by the first diagnostic harness has no recoverable host token and
  expires automatically under the 15-minute idle policy.
- **Remaining step:** Create a new active Resend API key, replace only the local
  `RESEND_API_KEY`, and repeat the version-7 deployment and real code-receipt flow.
  Until then, production intentionally remains on the pre-OTP link-sharing behavior.

## 40. OTP production redeployment with a valid Resend key — 2026-07-21 KST

- **Credential recovery:** The user replaced the rejected key and independently
  confirmed that Resend could deliver a test message from `onboarding@resend.dev`
  to the account email. The replacement local key retained the expected format,
  remained outside Git, and was never printed.
- **Production configuration:** Sites environment revision 5 received the new
  Resend key, the test sender, and a newly generated 48-byte signing secret while
  preserving the existing relay-create secret.
- **Deployment:** The already validated and saved email-OTP Viewer version 7 was
  redeployed successfully to the existing public Sites URL.
- **Live production evidence:** A new room returned 201 with email-OTP access,
  anonymous room-state access returned 401, auth status returned 200 with mail
  delivery configured, the Resend-backed OTP request returned 202, and the
  host-only audit endpoint returned 200 with a `verification_code_sent` event.
- **Pending human boundary:** The user must enter the received code in the test
  room before verified-session cookie, refresh persistence, attendee identity,
  and final room deletion can be confirmed. The test room contains no meeting
  content and expires under the configured idle policy if unused.

## 41. Expired-room recreation failure fix - 2026-07-21 KST

- **Observed failure:** After an earlier shared room expired, starting another
  share from the desktop UI produced only the generic relay error.
- **Root causes:** The local ignored `.share.env` still targeted a stale Vinext
  development relay on port 3000. After correcting it to the production Viewer,
  Cloudflare rejected Python urllib's default browser signature with error 1010
  before the request reached the Sites worker.
- **Fix:** The ignored local relay URL now targets the deployed Viewer, the stale
  owned development process was stopped, and every backend relay request now sends
  the stable product user agent `MeetingLiveTranslator/0.6`.
- **Verification:** All 7 focused live-share tests passed, including a new contract
  test for the explicit user agent. After restarting the desktop application, a
  real request through the local FastAPI endpoint created a production room, and
  the matching stop request deleted it. The final local share state was `idle` and
  inactive. No production redeployment was required.

## 42. Redundant host viewer button removal - 2026-07-21 KST

- **User feedback:** The host-side `Open viewer` action duplicated the invite-link
  copy flow and was confusing because the hardened Electron shell denies arbitrary
  popup windows.
- **Change:** Removed the button, its translation entry, DOM binding, disabled-state
  update, click handler, and popup helper. Invite-link copying, email verification,
  participant viewing, and per-link access logs remain unchanged.

## 43. VerbaRadar product rebrand and icon rollout - 2026-07-21 KST

- **User direction:** The user selected `VerbaRadar` as the product-facing name
  for the Build Week submission and future commercial service, replacing the
  generic `Meeting Live Translator` label across the application and public
  Viewer.
- **Visual identity:** Generated a 3:2 Devpost brand asset and derived a clean
  square application icon plus Windows ICO. The same verified speech-bubble and
  radar mark now identifies the desktop window, caption surfaces, main UI,
  public Viewer, social preview, and OTP email sender copy.
- **Product changes:** Updated visible titles, metadata, navigation branding,
  export headings, package descriptions, setup/start/stop messages, Lite release
  naming, documentation, and public replay attribution to `VerbaRadar`. Electron
  now supplies the icon to both native windows and registers the application as
  `VerbaRadar` for Windows taskbar grouping.
- **Compatibility boundary:** Retained existing `MLT_*` environment variables,
  storage keys, session formats, relay protocol, working-directory name, and the
  already distributed public Viewer URL. This avoids invalidating installations,
  saved sessions, active participant links, or secrets while changing only the
  product-facing identity.
- **Deployment:** Published Viewer version 8 with environment revision 6 to the
  existing Sites project. Production landing, demo, icon asset, and active-room
  authentication endpoints all returned HTTP 200; the active room remained
  available throughout deployment.
- **Verification:** Full Python regression passed `363 passed, 3 skipped` with
  only explicitly gated live-provider tests skipped. Viewer ESLint and production
  build passed, and the deployment retained the existing room and data stores.
- **Operational note:** The running desktop process was intentionally not
  restarted while sharing was active. The new native window/taskbar icon and app
  name take effect on the next normal `stop_all.bat` / `start_all.bat` cycle.

## 44. Renderer cache repair and recorded-audio demo restoration - 2026-07-21 KST

- **Observed regression:** After the VerbaRadar rebrand, the Electron header
  showed an empty icon and initialization stopped with
  `Cannot set properties of null (setting 'disabled')`, leaving controls in their
  loading state.
- **Root cause:** Electron had combined the newly deployed HTML, where the
  redundant host viewer button no longer exists, with a cached older JavaScript
  bundle that still accessed that button. The same stale CSS expected an inline
  SVG while the new header used the generated icon asset.
- **Repair:** Added no-store headers for app-shell and static responses, assigned a
  release-specific cache token to every renderer asset, cleared Electron HTTP and
  code caches before creating the main window, rendered the real PNG in the brand
  mark, and retained a hidden compatibility target for any already-cached bundle.
  Local settings and session storage remain untouched.
- **Real-app verification:** Restarted only VerbaRadar-owned processes. The live
  Electron window displayed the icon, populated the selected loopback device,
  reached app-ready and WebSocket-connected states, and opened the Context Engine
  panel through an actual click with no error banner. The translation worker and
  FastAPI diagnostics were healthy.
- **Demo correction:** Restored the previously verified, consented scripted demo
  recording and synchronized replay fixture from the merged audio-demo work. The
  public MP3 is 919,721 bytes (76.565 seconds) with SHA-256
  `96870E48C9AEDF776AC912EED27E37DED2A0D8E7F6B44E6F9A0C4D41740F089F`.
  No private session audio or identifiers are included.
- **Production deployment:** Published Sites Viewer version 9 from source commit
  `71d09959a9dd0efa9f4f6d74166ad2355ed4ab1d`, preserving environment revision 6
  and the existing public URL. The deployed audio downloaded with the exact same
  byte count and SHA-256; the public demo exposed the audio controls, bilingual UI,
  5 finalized captions, 5 translations, 5 context corrections, and 12 verified
  Radar evidence links.
- **Regression evidence:** Full Python regression passed `366 passed, 3 skipped`;
  the three skips remain explicitly gated live-provider tests. Viewer production
  build and ESLint passed, all 12 Viewer tests passed, 33 focused renderer tests
  passed, and JavaScript syntax checks passed.

## 45. User-authored WhyKaigi identity and release hardening - 2026-07-21 KST

- **User decision and authorship boundary:** The user personally selected
  `WhyKaigi` as the final product name and supplied the existing black `Why?`
  wordmark already used across their own applications. Codex did not invent the
  name or visual concept; it cleaned, upscaled, and adapted that supplied mark
  into the required runtime and submission formats.
- **Product-facing rebrand:** Updated the FastAPI title, Electron application and
  window identity, main UI, detached caption and Radar windows, public Viewer,
  OTP email copy, exports, package metadata, setup/start/stop messages, Lite
  distribution name, documentation, and public replay attribution to
  `WhyKaigi`. The same 512x512 PNG is used by all runtime surfaces, with a
  multi-resolution Windows ICO plus 3:2 Open Graph and Devpost assets.
- **Compatibility boundary:** Kept `MLT_*` environment variables, `mlt-*`
  cookies/storage/broadcast keys, API and relay schemas, D1 bindings, session
  formats, the local working-directory name, and the existing Sites project ID.
  Historical specifications and previous VerbaRadar log entries remain intact.
  No existing session, JSONL, model, credential, or access-log data was changed.
- **Regression prevention:** Added checks for the exact WhyKaigi brand markers,
  identical 512x512 runtime PNGs, removal of every legacy asset, absence of old
  display names in runtime source, cache-safe renderer assets, and absence of
  local Windows user paths from Viewer production bundles. Removing `next/font`
  eliminated a build artifact that had embedded a developer-local absolute font
  path in the previously published HTML.
- **Actual verification:** Full Python regression passed `369 passed, 3 skipped`;
  skips are the existing explicitly gated live-provider tests. Viewer ESLint,
  Vinext production build, and all 13 Node tests passed. JavaScript syntax and
  PowerShell parser checks passed. A real Electron restart reached healthy
  FastAPI, translation Worker, app-ready, populated loopback device, and connected
  WebSocket states while visibly rendering the new `Why?` mark and WhyKaigi
  title.
- **Lite release evidence:** Built `whykaigi-lite-20260721.zip` with 115 entries,
  no tracked secrets, sessions, models, virtual environments, runtime PID files,
  or legacy brand assets. SHA-256 is
  `CD2AE6361BFCF0A828ED12E65DABC7B63A0B30ECE014FE31D1854FDD316B86EC`.
- **External release boundary:** The source and package are ready for the same
  existing Sites project, Devpost entry, and GitHub repository to be renamed and
  updated without replacing their data-bearing identifiers. Those external
  results will be recorded after the live deployment and PR checks complete.
