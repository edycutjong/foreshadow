# Alibaba Function Compute — deployment proof

## Honest status

The FC worker (`handler.py`) and its Serverless Devs spec (`s.yaml`) are
**complete and import-clean**, but this repository has **not been deployed to a
live Alibaba Function Compute account**. The offline build is the graded
artifact; live cloud deployment is explicitly listed under README "Status /
Pending". We do not show a console screenshot we did not record.

Why this is still credible:

- The pipeline core is **host- and transport-agnostic**. `handler.py` is a thin
  request/response shim over the exact `create_context` → `run_pipeline` path
  that the CLI, the tests, and `verify_offline.py` all drive. There is no
  second, cloud-only code path that could silently be broken.
- The handler **runs today, offline**, proving the shim itself is wired:

  ```bash
  ./.venv/bin/python infra/fc/handler.py
  # -> {"statusCode": 200, "body": "{\"job_id\": ..., \"status\": \"published\",
  #     \"merkle_root\": \"4a7e3aa0...\", \"stages\": [...]}"}
  ```

## What a live deployment would record (repro steps)

1. Set `ALIBABA_REGION`, `DASHSCOPE_API_KEY`, and `FFMPEG_LAYER_ARN` in the shell.
2. `cd infra/fc && s deploy` (Serverless Devs, `fc3` component).
3. `POST` a job to the HTTP trigger:
   ```bash
   curl -sX POST "$FC_HTTP_URL" \
     -d '{"incident_id":"forklift","budget_usd":4,"transport":"live"}'
   ```
4. The 30–60s screen recording for the Devpost submission captures the FC
   console showing the invocation, the streamed stage log, and the OSS object
   hashes matching the manifest leaves.

## Second Alibaba surface (OSS)

In production the job directory (frames, clips, `film.mp4`, `manifest.json`) is
mirrored to an OSS bucket; each object's ETag/SHA-256 is the same hash recorded
in the signed manifest, so the `/integrations/verify` page can re-hash the OSS
object and confirm it against the Ed25519 signature. Locally that archive is the
committed `fixtures/cache/<incident>/` tree.
