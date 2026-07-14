"""ECIES-style sealing of incident uploads at rest (pynacl, libsodium boxes).

Envelope format (1-byte header):
  b"S" + SealedBox(worker_pub).encrypt(plaintext)
        random ephemeral X25519 key -> XSalsa20-Poly1305. LIVE mode.
  b"D" + sender_pub(32) + Box(sender, worker).encrypt(plaintext, nonce)
        deterministic DEMO/replay envelope: fixed demo sender key and a
        24-byte BLAKE2b nonce derived from (context, plaintext). The nonce is
        unique per (key pair, message) — the SIV-style argument — so replays
        are byte-identical without weakening the AEAD. Judges rebuild the
        exact sealed blob; live uploads keep full random sealing.

(COMPLEXITY.md says "X25519+AES-GCM"; the mandated primitive — pynacl
SealedBox/Box — is X25519 + XSalsa20-Poly1305. Same envelope property,
documented honestly in docs/SPEC-PROVENANCE.md.)

Only the worker holds the unseal key. The plaintext incident text exists on
disk exactly once: inside the sealed blob.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from nacl.encoding import RawEncoder
from nacl.hash import blake2b
from nacl.public import Box, PrivateKey, PublicKey, SealedBox

DEMO_WORKER_SEED = b"foreshadow-demo-worker-x25519-v1"
DEMO_SENDER_SEED = b"foreshadow-demo-sender-x25519-v1"

HEADER_SEALEDBOX = b"S"
HEADER_DETERMINISTIC = b"D"


def demo_worker_key() -> PrivateKey:
    """Deterministic DEMO worker key (same rationale as the demo signing key:
    replayable mechanism proof, explicitly not an identity secret)."""
    return PrivateKey(hashlib.sha256(DEMO_WORKER_SEED).digest())


def demo_sender_key() -> PrivateKey:
    return PrivateKey(hashlib.sha256(DEMO_SENDER_SEED).digest())


def load_or_create_worker_key(key_path: Path) -> PrivateKey:
    if key_path.exists():
        return PrivateKey(key_path.read_bytes())
    key = PrivateKey.generate()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(bytes(key))
    key_path.chmod(0o600)
    return key


def seal(plaintext: bytes, worker_pubkey: PublicKey) -> bytes:
    """LIVE envelope: anonymous sealed box (random ephemeral sender)."""
    return HEADER_SEALEDBOX + SealedBox(worker_pubkey).encrypt(plaintext)


def seal_deterministic(plaintext: bytes, worker_pubkey: PublicKey, context: str) -> bytes:
    """DEMO/replay envelope: byte-identical for identical inputs."""
    sender = demo_sender_key()
    nonce = blake2b(
        context.encode("utf-8") + b"\x00" + plaintext,
        digest_size=24,
        encoder=RawEncoder,
    )
    encrypted = Box(sender, worker_pubkey).encrypt(plaintext, nonce)
    return HEADER_DETERMINISTIC + bytes(sender.public_key) + bytes(encrypted)


def unseal(sealed: bytes, worker_key: PrivateKey) -> bytes:
    """Open either envelope. Raises nacl.exceptions.CryptoError on tamper."""
    if not sealed:
        raise ValueError("empty envelope")
    header, body = sealed[:1], sealed[1:]
    if header == HEADER_SEALEDBOX:
        return SealedBox(worker_key).decrypt(body)
    if header == HEADER_DETERMINISTIC:
        sender_pub = PublicKey(body[:32])
        return Box(worker_key, sender_pub).decrypt(body[32:])
    raise ValueError(f"unknown envelope header: {header!r}")
