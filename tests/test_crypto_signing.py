"""Ed25519 signing (pynacl): sign/verify, tamper rejection, key policy."""

from __future__ import annotations

from foreshadow.crypto.signing import (
    demo_signing_key,
    load_or_create_signing_key,
    pubkey_hex,
    sign_payload,
    verify_signature,
)


def test_demo_key_is_deterministic():
    assert bytes(demo_signing_key()) == bytes(demo_signing_key())


def test_pubkey_hex_is_64_chars():
    assert len(pubkey_hex(demo_signing_key())) == 64


def test_sign_returns_128_hex():
    sig = sign_payload(demo_signing_key(), b"payload")
    assert len(sig) == 128
    bytes.fromhex(sig)  # valid hex


def test_sign_verify_roundtrip():
    key = demo_signing_key()
    sig = sign_payload(key, b"the payload")
    assert verify_signature(pubkey_hex(key), b"the payload", sig) is True


def test_verify_fails_on_tampered_payload():
    key = demo_signing_key()
    sig = sign_payload(key, b"the payload")
    assert verify_signature(pubkey_hex(key), b"the paylo@d", sig) is False


def test_verify_fails_on_wrong_pubkey():
    key = demo_signing_key()
    sig = sign_payload(key, b"p")
    other = load_or_create_signing_key  # noqa: F841 (import touch)
    wrong_pub = "0" * 64
    assert verify_signature(wrong_pub, b"p", sig) is False


def test_verify_fails_on_bad_signature_hex():
    key = demo_signing_key()
    assert verify_signature(pubkey_hex(key), b"p", "zz" * 64) is False


def test_verify_fails_on_flipped_signature_bit():
    key = demo_signing_key()
    sig = bytearray(bytes.fromhex(sign_payload(key, b"p")))
    sig[0] ^= 0x01
    assert verify_signature(pubkey_hex(key), b"p", sig.hex()) is False


def test_signature_deterministic_for_demo_key():
    # Ed25519 is deterministic (RFC 8032): same key + message -> same signature.
    assert sign_payload(demo_signing_key(), b"x") == sign_payload(demo_signing_key(), b"x")


def test_load_or_create_persists_key(tmp_path):
    kp = tmp_path / "keys" / "signing.key"
    k1 = load_or_create_signing_key(kp)
    assert kp.exists()
    k2 = load_or_create_signing_key(kp)
    assert bytes(k1) == bytes(k2)


def test_load_or_create_writes_pubkey_file(tmp_path):
    kp = tmp_path / "signing.key"
    k = load_or_create_signing_key(kp)
    pub = kp.with_suffix(".pub")
    assert pub.exists()
    assert pub.read_text(encoding="utf-8").strip() == pubkey_hex(k)


def test_created_private_key_is_0600(tmp_path):
    kp = tmp_path / "signing.key"
    load_or_create_signing_key(kp)
    assert (kp.stat().st_mode & 0o777) == 0o600
