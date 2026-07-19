# Foreshadow — Alibaba Function Compute deploy proof

**Live URL:** https://foreshadow-txebjackop.ap-southeast-1.fcapp.run
**Region:** ap-southeast-1 · **Runtime:** managed `python3.10` (no container, no ACR)
**Function:** `foreshadow` · **Handler:** `infra.fc.wsgi.handler` · **Trigger:** anonymous HTTP GET/POST
**Deployed:** 2026-07-19 (Serverless Devs `s build --use-docker` + `s deploy -y`)

All endpoints are **offline & deterministic** — FakeQwen transport, zero DASHSCOPE
key, no image/video/TTS generation. `/verify` and `/run` replay the committed
fixtures cache and re-verify the Ed25519 + Merkle provenance chain.

## GET /health

```
$ curl -s https://foreshadow-txebjackop.ap-southeast-1.fcapp.run/health
{
  "status": "ok"
}
[HTTP 200]
```

## GET /verify — re-verify the committed forklift replay (Ed25519 + Merkle + I1–I4)

```
$ curl -s https://foreshadow-txebjackop.ap-southeast-1.fcapp.run/verify
{
  "budget_usd": 4.0,
  "byte_identical_cache": true,
  "checks": [
    { "detail": "Ed25519 signer 544aa661bf072330...", "name": "signature", "ok": true },
    { "detail": "recomputed 4a7e3aa0bd296923...", "name": "merkle_root", "ok": true },
    { "detail": "36 artifact hashes re-verified", "name": "I4_artifact_hashes", "ok": true },
    { "detail": "film file matches its manifest leaf", "name": "I4_film_hash", "ok": true },
    { "detail": "10 cut entries trace to task ids", "name": "I1_traceable_edit_list", "ok": true },
    { "detail": "spent $2.71 <= budget $4.00; leaf costs $2.71 reconcile", "name": "I2_budget", "ok": true },
    { "detail": "0 rejected clip(s) provably outside the cut", "name": "I3_rejected_excluded", "ok": true }
  ],
  "incident": "forklift",
  "leaves": 36,
  "merkle_root": "4a7e3aa0bd296923f7b610625b9e97eab70b43dd0b21e7e3a88038b2ddca959a",
  "overall": "PASS",
  "source": "committed forklift replay ledger (FakeQwen, zero network, zero keys)",
  "spent_usd": 2.7051
}
[HTTP 200]
```

## GET /run — one deterministic offline pipeline replay (default incident=forklift, budget=4)

```
$ curl -s https://foreshadow-txebjackop.ap-southeast-1.fcapp.run/run
{
  "budget_mix": { "connective": 3, "hero": 3, "kenburns": 2 },
  "budget_usd": 4.0,
  "byte_identical_cache": true,
  "incident": "forklift",
  "invariants": "I1-I4 PASS",
  "leaves": 36,
  "merkle_root": "4a7e3aa0bd296923f7b610625b9e97eab70b43dd0b21e7e3a88038b2ddca959a",
  "qc": { "demoted": 0, "rejected": 0, "retries": 0, "reviewed": 6 },
  "render_spend_usd": 2.1,
  "spent_usd": 2.7051,
  "status": "published",
  "transport": "FakeQwen (offline deterministic — no key required)"
}
[HTTP 200]
```

## GET /run?incident=chemical — QC loop rejects a bad shot (invariant I3)

```
$ curl -s "https://foreshadow-txebjackop.ap-southeast-1.fcapp.run/run?incident=chemical"
{
  "budget_mix": { "connective": 3, "hero": 3, "kenburns": 1 },
  "budget_usd": 4.0,
  "byte_identical_cache": true,
  "incident": "chemical",
  "invariants": "I1-I4 PASS",
  "leaves": 36,
  "merkle_root": "f586e0ab29ede973b767aca111e11f91f473996c93b71c0b4bd77d66b842fa94",
  "qc": { "demoted": 0, "rejected": 1, "retries": 1, "reviewed": 7 },
  "render_spend_usd": 2.0,
  "spent_usd": 2.7769,
  "status": "published",
  "transport": "FakeQwen (offline deterministic — no key required)"
}
[HTTP 200]
```

The live `/verify` merkle root, spent, and 36 leaves match `DEMO.md` and the
committed `fixtures/cache/forklift/manifest.json` byte-for-byte.

## Recipe notes / gotchas

- **FC 3.0 wants an EVENT handler**, not a WSGI app. `infra/fc/wsgi.py` exposes
  `handler(event, context)` returning `{statusCode, headers, body}`; a WSGI
  callable yields a 502 (`'FCContext' object is not callable`).
- **Managed python3.10 vs. a 3.12 package.** Two 3.11+ symbols are shimmed at the
  top of `wsgi.py` *before* importing foreshadow: `enum.StrEnum` and
  `datetime.UTC` (`foreshadow.utils` does `from datetime import UTC`). Both are
  trivial aliases (`str+Enum`, `timezone.utc`) — behaviour is identical.
- **Package path.** Deps install to `/code/python` (`PYTHONPATH`); the package
  itself lives at `/code/src/foreshadow`, so `wsgi.py` does
  `sys.path.insert(0, .../src)`. `config.REPO_ROOT` resolves to `/code`, so
  `fixtures/` and `seeds/` are found automatically — both must ship (they are
  NOT in `.fcignore`).
- **Read-only bundle.** Replay writes a SQLite db + job artifacts, so the handler
  passes an explicit `home=mkdtemp()` under `/tmp`.
- No custom `role` or `logConfig` was needed — first deploy returned 200 on all
  routes.
