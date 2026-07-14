# Foreshadow — Benchmarks

Reproduce locally (offline, zero keys):

```bash
./.venv/bin/python scripts/bench.py        # or: foreshadow bench
./.venv/bin/python scripts/verify_offline.py
```

`bench.py` runs the full pipeline nine times (3 incidents × $2/$4/$8) in a
throwaway home and reports what the Line Producer actually bought. Latency
figures are FakeQwen's **deterministic simulation** — labeled as such; the
offline build never fabricates "live measurements". Unit costs are the exact
per-call prices the ledger charges (SPEC.md §5).

## Per-surface latency and unit cost

| surface | model | p50 (ms) | p95 (ms) | unit cost |
|---|---|---:|---:|---|
| screenplay | `qwen3.7-max` | 6821 | 7539 | $0.10/call |
| shot plan (structured) | `qwen3.7-max` | 3005 | 3153 | $0.05/call |
| alloc rationale | `qwen3.6-flash` | 793 | 865 | $0.01/call |
| image (character/storyboard) | `qwen-image-2.0-pro` | 9436 | 10241 | $0.075/img (batch -50%) |
| hero render | `wan2.7-i2v` | 112306 | 119412 | $0.10/s |
| connective render | `wan2.6-i2v-flash` | 45767 | 49175 | $0.05/s |
| dailies QC | `qwen3-vl-plus` | 5136 | 5599 | $0.01/review |
| narration | `cosyvoice-v3-plus` | 4004 | 4630 | $0.26/10k chars |

## Budget sweep — what the Line Producer buys at $2 / $4 / $8

| incident | budget | hero | connective | ken-burns | render $ | film total $ | quality | demotions | QC (rev/rej/retry) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| forklift | $2 | 1 | 1 | 6 | $0.75 | $1.32 | 49.8% | 5 | 2/0/0 |
| forklift | $4 | 3 | 3 | 2 | $2.10 | $2.71 | 78.4% | 0 | 6/0/0 |
| forklift | $8 | 6 | 0 | 2 | $2.70 | $3.31 | 92.0% | 0 | 6/0/0 |
| ladder | $2 | 0 | 2 | 4 | $0.60 | $1.09 | 40.0% | 4 | 2/0/0 |
| ladder | $4 | 2 | 4 | 0 | $2.40 | $2.93 | 73.3% | 0 | 6/0/0 |
| ladder | $8 | 6 | 0 | 0 | $3.60 | $4.13 | 100.0% | 0 | 6/0/0 |
| chemical | $2 | 1 | 1 | 5 | $0.75 | $1.28 | 52.1% | 5 | 2/0/0 |
| chemical | $4 | 3 | 3 | 1 | $2.00 | $2.78 | 80.8% | 0 | 7/1/1 |
| chemical | $8 | 6 | 0 | 1 | $2.60 | $3.58 | 94.5% | 0 | 7/1/1 |

### Reading the sweep

- **The allocator does something.** Quality climbs with budget as the Line
  Producer promotes shots up the tier ladder: forklift **49.8% → 78.4% → 92.0%**
  across $2 → $4 → $8. Demotions fall to zero once there is enough budget to
  give every shot its desired tier.
- **Two real price tiers.** At $2 most shots fall to the free Ken-Burns still
  tier; at $8 nearly everything renders on the hero tier. Without a cheap
  connective tier (`wan2.6-i2v-flash`) the middle column could not exist —
  that is the budget-ladder pitch, made measurable.
- **QC is grounded, not cosmetic.** Only the **chemical** incident shows
  `rej/retry = 1/1`: shot C4's first render prompt omits its PPE elements, the
  VL critic (here, FakeQwen's mechanistic stand-in for `qwen3-vl-plus`) rejects
  it, one corrective re-render passes, and the rejected clip is provably
  excluded from the cut (invariant I3). See `fixtures/cache/chemical/qc/`.
- **Films land ≈ $1–4.** The hero metric — "**$2.71 vs $15,000**" — is the
  ledger total for forklift@$4, not a slogan.

## Offline verification proof

`scripts/verify_offline.py` installs a socket guard (any network call raises),
replays forklift@$4 from scratch, verifies I1–I4, and confirms the fresh
manifest is byte-identical to the committed cache. Exit 0 = reproduced with
zero network and zero keys.

```
[guard] network disabled by verify_offline.py socket guard
[replay] rebuilding incident 'forklift' at $4 (FakeQwen, offline)
[replay] spent $2.7051; merkle root 4a7e3aa0bd296923f7b610625b9e97eab70b43dd0b21e7e3a88038b2ddca959a
[verify] PASS signature: Ed25519 signer 544aa661bf072330...
[verify] PASS merkle_root: recomputed 4a7e3aa0bd296923...
[verify] PASS I4_artifact_hashes: 36 artifact hashes re-verified
[verify] PASS I4_film_hash: film file matches its manifest leaf
[verify] PASS I1_traceable_edit_list: 10 cut entries trace to task ids
[verify] PASS I2_budget: spent $2.71 <= budget $4.00; leaf costs $2.71 reconcile
[verify] PASS I3_rejected_excluded: 0 rejected clip(s) provably outside the cut
[cache ] manifest matches committed fixtures/cache (byte-identical)
OFFLINE VERIFICATION PASS (zero network, zero keys)
```
