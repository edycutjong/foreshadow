# Foreshadow — Demo script

Exact commands and their expected output. Everything here runs **offline, with
zero API keys** (a session/socket guard blocks the network). Setup once:

```bash
python -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

(`.[dev]` already includes the offline animatic renderer used in step 1b —
no separate install, no network, no key.)

## 0. Prove the suite is green

```bash
./.venv/bin/pytest -q
```

Expected (last line):

```
420 passed
```

## 1. Rebuild the demo film from the incident report (the money shot)

```bash
./.venv/bin/foreshadow replay --incident forklift
```

Expected:

```
replaying forklift at $4 (offline, FakeQwen, demo keys)
  [  done] ingest  (sealed_bytes=1542)
  [  done] screenplay  (beats=3, title=Aisle Seven)
  [  done] shot_plan  (shots=8)
  [  done] budget_alloc  (mix={'hero': 3, 'connective': 3, 'kenburns': 2}, regret_rows=0, render_spend_usd=2.1)
  [  done] character_sheet  (bytes=171)
  [  done] storyboard  (batch_discount=0.5, frames=8)
  [  done] render  (kenburns=2, rendered=6)
  [  done] qc  (demoted=0, rejected=0, retries=0, reviewed=6)
  [  done] narrate  (chars=390, cost_usd=0.01014)
  [  done] stitch  (edit_entries=10, ffmpeg=stub media (deterministic replay); ffmpeg intentionally not used, film=film.mp4)
  [  done] publish  (invariants=I1-I4 PASS, leaves=36, merkle_root=4a7e3aa0..., spent_usd=2.70514)

  spent $2.7051 of $4.00
  merkle root 4a7e3aa0bd296923f7b610625b9e97eab70b43dd0b21e7e3a88038b2ddca959a
  invariants I1-I4 PASS
  committed cache: byte-identical manifest (root + signature match)
```

**The pitch line:** the ledger says this film cost **$2.71** — versus $5–15k and
6–8 weeks for a conventional safety video.

### 1b. Watch a real, playable animatic (optional)

`film.mp4` in the cache is a signed edit-list stub (kept byte-identical for
replay), so it won't open in a player. To *watch* something, render the animatic:

```bash
# renderer already present from ".[dev]" above (or: pip install -e ".[preview]")
./.venv/bin/foreshadow preview --incident forklift   # → forklift_animatic.mp4
open forklift_animatic.mp4                            # ~38s, 1280×720, H.264
```

This is a real MP4 you can open — an **offline storyboard animatic** (title
cards + narration + Ken-Burns) built from the deterministic shot plan. It is
**not** `wan`-generated footage (FakeQwen makes no video); it exists so there's a
watchable artifact without a key. Real `wan2.7-i2v` runs only with `DASHSCOPE_API_KEY`.

## 2. See the QC loop reject a bad shot (chemical incident)

```bash
./.venv/bin/foreshadow replay --incident chemical --budget 4
```

Expected (excerpt): shot C4's first render omits its PPE elements, the VL critic
rejects it, one corrective re-render passes, and the rejected clip is provably
excluded from the cut (invariant I3):

```
  [  done] qc  (demoted=0, rejected=1, retries=1, reviewed=7)
  ...
  invariants I1-I4 PASS
  committed cache: byte-identical manifest (root + signature match)
```

## 3. Verify provenance (re-hash + signature + I1–I4)

```bash
./.venv/bin/foreshadow verify \
  fixtures/cache/forklift/film.mp4 fixtures/cache/forklift/manifest.json
```

Expected:

```
manifest fixtures/cache/forklift/manifest.json
  job replay-forklift-b4 | incident forklift | spent $2.7051 of $4.00 | leaves 36
  [PASS] signature                Ed25519 signer 544aa661bf072330...
  [PASS] merkle_root              recomputed 4a7e3aa0bd296923...
  [PASS] I4_artifact_hashes       36 artifact hashes re-verified
  [PASS] I4_film_hash             film file matches its manifest leaf
  [PASS] I1_traceable_edit_list   10 cut entries trace to task ids
  [PASS] I2_budget                spent $2.71 <= budget $4.00; leaf costs $2.71 reconcile
  [PASS] I3_rejected_excluded     0 rejected clip(s) provably outside the cut
VERIFICATION PASS
```

Tamper one byte of any artifact and re-run: `I4_artifact_hashes` flips to FAIL
and the command exits 1.

## 4. Watch the economics move with the budget

```bash
./.venv/bin/foreshadow plan --incident forklift --budget 2
./.venv/bin/foreshadow plan --incident forklift --budget 8
```

At **$2** the Line Producer demotes most shots to the free Ken-Burns still tier
(quality ≈ 50%); at **$8** nearly everything renders on the hero tier
(quality ≈ 92%). The full $2/$4/$8 sweep table:

```bash
./.venv/bin/foreshadow bench        # or: python scripts/bench.py
```

## 5. One-command judge proof (socket-guarded)

```bash
./.venv/bin/python scripts/verify_offline.py; echo "exit $?"
```

Installs a socket guard (any network call raises), replays forklift@$4, verifies
I1–I4, confirms byte-identity with the committed cache, and prints
`OFFLINE VERIFICATION PASS (zero network, zero keys)` with `exit 0`.

## Live mode (optional, needs a key)

```bash
export DASHSCOPE_API_KEY=sk-...
./.venv/bin/foreshadow render --incident forklift --budget 4 --transport live
```

Chat surfaces call Qwen Cloud directly; image/video/TTS surfaces are
payload-complete but gated (`LiveSurfaceNotVerified`) in this offline-first
build — see README "Status / Pending".
