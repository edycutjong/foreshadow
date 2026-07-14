# Foreshadow — Provenance Specification

The formal contract behind `foreshadow verify` and invariants I1–I4. This is
the authority referenced by `crypto/`, `provenance.py`, and `schemas.py`.

## 1. Canonical form

Everything hashed or signed is serialized with `utils.canonical_json`:
UTF-8, `sort_keys=True`, compact separators `(",", ":")`, `ensure_ascii=False`.
Two structurally equal objects always produce identical bytes.

## 2. Manifest schema (C2PA-style)

A manifest has a header, a list of **leaves**, the final-cut **edit list**, the
list of **QC-rejected** clip hashes, and the signature block. Each leaf:

| field | meaning |
|---|---|
| `sha256` | hash of the artifact bytes on disk (64 hex) |
| `kind` | `screenplay` \| `shotplan` \| `clip` \| `clip_rejected` \| `clip_kenburns` \| `film` \| … |
| `model` | the Qwen model id that produced it (empty for local artifacts) |
| `prompt_sha256` | hash of the exact prompt used |
| `qwen_task_id` | the async task / request id the vendor returned |
| `parent_ids` | sha256s of the leaves this artifact derives from |
| `cost_usd` | the ledger charge for this artifact |
| `ts`, `path` | job-clock timestamp, path relative to the job dir |

## 3. Merkle construction

- leaf hash = `SHA-256(0x00 || canonical_json(leaf_payload))`
- inner hash = `SHA-256(0x01 || left || right)`
- odd level: duplicate the last node (Bitcoin-style)
- the `0x00`/`0x01` domain-separation prefixes block second-preimage attacks
  that would reinterpret an inner node as a leaf.

Leaf **order is part of what is signed**. The root is hex.

## 4. Signature

The Ed25519 signature (pynacl, no hand-rolled crypto) covers
`Manifest.signed_payload()`: version, job/incident ids, budget, spent,
`created_ts`, **leaf_count**, **merkle_root**, **edit_list**, **qc_rejected**.
Signing the edit list and the rejected set makes I1/I3 tamper-evident, not just
advisory.

Key policy: DEMO/replay uses a keypair derived deterministically from a public
seed string (`crypto/signing.py`) — judges rebuild byte-identical manifests
with zero key material; the demo key proves *mechanism*, not *identity*. Live
mode loads/creates a real gitignored keypair under `keys/`, shipping only the
public key.

## 5. Envelope (incident at rest)

Uploads are sealed with pynacl boxes (X25519 + XSalsa20-Poly1305 — the mandated
`SealedBox`/`Box` primitive). The COMPLEXITY.md shorthand "X25519+AES-GCM"
names the same envelope property; we state the actual AEAD honestly here. Only
the worker holds the unseal key; plaintext exists on disk exactly once, inside
the sealed blob. Replay uses a deterministic envelope (fixed demo sender + a
BLAKE2b nonce derived from context+plaintext) so sealed bytes are reproducible
without weakening the AEAD; live uploads use full random sealing.

## 6. Invariants (formal, tested — see `tests/test_invariants.py`)

- **I1** every entry in the final cut's edit list resolves to a leaf whose
  ancestry (`parent_ids`) reaches a leaf carrying a real `qwen_task_id`.
- **I2** `spent_usd ≤ budget_usd`, and `Σ leaf.cost_usd` reconciles with the
  ledger total.
- **I3** no QC-rejected clip hash appears in the edit list, and no
  `clip_rejected`-kind leaf is in the cut.
- **I4** re-hashing every artifact, rebuilding the Merkle root, and checking the
  signature fails on any 1-byte tamper.

## 7. Residual risk (honest)

Signing proves **pipeline integrity, not narrative truth**. A fabricated
incident report yields a validly-signed film about a fake incident — provenance
attests that *this pipeline* produced *these bytes* from *that input*, not that
the input describes a real event. Prompt-level fabrication is out of scope for a
cryptographic manifest and is not claimed otherwise.
