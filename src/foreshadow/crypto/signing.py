"""Ed25519 signing of the manifest payload (pynacl — no hand-rolled crypto).

Key policy (docs/SPEC-PROVENANCE.md section 5):
- DEMO/replay mode uses a keypair derived deterministically from a public
  seed string. This is intentional: judges replay byte-identical manifests
  with zero key material. The demo key proves *mechanism*, not *identity*.
- LIVE mode loads (or creates) a real keypair under keys/; the private key is
  gitignored, only the public key ships.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

DEMO_SIGNING_SEED = b"foreshadow-demo-signing-ed25519-v1"


def demo_signing_key() -> SigningKey:
    """Deterministic DEMO key — public by design, replayable everywhere."""
    return SigningKey(hashlib.sha256(DEMO_SIGNING_SEED).digest())


def load_or_create_signing_key(key_path: Path) -> SigningKey:
    """LIVE key: load from disk, or create once and persist (0600)."""
    if key_path.exists():
        return SigningKey(key_path.read_bytes())
    key = SigningKey.generate()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(bytes(key))
    key_path.chmod(0o600)
    pub_path = key_path.with_suffix(".pub")
    pub_path.write_text(key.verify_key.encode().hex() + "\n", encoding="utf-8")
    return key


def sign_payload(key: SigningKey, payload: bytes) -> str:
    """Detached signature, hex."""
    return key.sign(payload).signature.hex()


def pubkey_hex(key: SigningKey) -> str:
    return key.verify_key.encode().hex()


def verify_signature(pubkey_hex_str: str, payload: bytes, signature_hex: str) -> bool:
    try:
        VerifyKey(bytes.fromhex(pubkey_hex_str)).verify(
            payload, bytes.fromhex(signature_hex)
        )
        return True
    except (BadSignatureError, ValueError):
        return False
