# Qwen Cloud friction log

Developer-experience notes taken while building Foreshadow against the Qwen
Cloud (dashscope-intl) surface. This feeds the submission blog post
("I made an AI film crew fight over a $4 budget"). It is **honest about
scope**: the offline-first build runs entirely on `FakeQwen`, so the live-call
notes below are observations about the *documented* API surface and the shim in
`src/foreshadow/qwen/live.py` — the media surfaces are wired but gated behind
`DASHSCOPE_API_KEY` and marked pending (see README "Status / Pending").

## What was smooth

- **One base URL, many modalities.** `qwen3.7-max` (chat + thinking),
  `qwen3.6-flash`, and `qwen3-vl-plus` all speak the OpenAI-compatible
  chat-completions shape at `dashscope-intl.../compatible-mode/v1`. A single
  `OpenAI(base_url=...)` client covers four of the eight surfaces — the reason
  `LiveQwen._chat` is ~30 lines.
- **Structured output as a first-class param.** Passing
  `response_format={"type":"json_schema", ... "strict": true}` with a Pydantic
  `model_json_schema()` is exactly the ergonomic we wanted for `ShotPlan` /
  `QCVerdict`. It let the allocator treat shot weights as trustworthy integers.
- **Thinking is a flag, not a different endpoint.** `enable_thinking` via
  `extra_body` kept the screenplay call on the same code path as the flash
  calls.

## What caused friction (and how we handled it)

1. **Async video tasks have no webhook.** `wan2.7-i2v` / `wan2.6-i2v-flash`
   follow submit → poll (`X-DashScope-Async: enable`, then
   `GET /api/v1/tasks/{id}`). There is no callback, so the orchestrator
   (`render/orchestrator.py`) persists the `task_id` *before* the first poll —
   a crash between submit and completion can never orphan an unbilled render.
   `FakeQwen.poll_video` reproduces the real `RUNNING → SUCCEEDED` shape so the
   poller is exercised offline.
2. **Structured-output enum drift.** Free-form models occasionally emit a tier
   or QC action just outside the allowed enum. We guard every structured call
   with **one reject-retry** (`agents/screenwriter.py::_validated`,
   `agents/qc.py`) before failing the stage — cheap insurance that keeps the
   allocator from ever parsing a malformed plan.
3. **Cost normalization is on you.** Eight surfaces means eight price units
   ($/call, $/img, $/s, $/10k chars). We centralized every rate in
   `config.py` and made the ledger the single writer, so "this film cost $2.71"
   is one query, not a cross-vendor reconciliation.
4. **Media bytes vs. determinism.** Real `wan` clips are not byte-reproducible,
   which would break judge-side replay. We keep the live path (ffmpeg concat +
   audio mix) but ship deterministic byte-stubs on the fake transport, so the
   demo film rebuilds identically on any machine (see `render/stitch.py`).

## If we had one API request

A signed-webhook completion callback for async `wan` tasks would remove the
poll loop entirely and let the war-room UI stream "clip landed" events without
holding a connection open. Polling works; a callback would be nicer.
