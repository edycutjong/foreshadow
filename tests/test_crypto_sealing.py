"""ECIES-style sealing (pynacl boxes): roundtrips, determinism, tamper."""

from __future__ import annotations

import pytest
from nacl.exceptions import CryptoError

from foreshadow.crypto.sealing import (
    HEADER_DETERMINISTIC,
    HEADER_SEALEDBOX,
    demo_sender_key,
    demo_worker_key,
    load_or_create_worker_key,
    seal,
    seal_deterministic,
    unseal,
)

PLAINTEXT = b"OSHA near-miss narrative: forklift blind corner"


def test_seal_unseal_roundtrip_live():
    worker = demo_worker_key()
    sealed = seal(PLAINTEXT, worker.public_key)
    assert sealed[:1] == HEADER_SEALEDBOX
    assert unseal(sealed, worker) == PLAINTEXT


def test_live_seal_is_randomized():
    worker = demo_worker_key()
    assert seal(PLAINTEXT, worker.public_key) != seal(PLAINTEXT, worker.public_key)


def test_deterministic_seal_is_byte_identical():
    worker = demo_worker_key()
    a = seal_deterministic(PLAINTEXT, worker.public_key, context="job-1")
    b = seal_deterministic(PLAINTEXT, worker.public_key, context="job-1")
    assert a == b


def test_deterministic_seal_has_header_and_sender_pubkey():
    worker = demo_worker_key()
    sealed = seal_deterministic(PLAINTEXT, worker.public_key, context="job-1")
    assert sealed[:1] == HEADER_DETERMINISTIC
    assert sealed[1:33] == bytes(demo_sender_key().public_key)


def test_deterministic_seal_context_changes_ciphertext():
    worker = demo_worker_key()
    a = seal_deterministic(PLAINTEXT, worker.public_key, context="job-1")
    b = seal_deterministic(PLAINTEXT, worker.public_key, context="job-2")
    assert a != b


def test_deterministic_seal_plaintext_changes_ciphertext():
    worker = demo_worker_key()
    a = seal_deterministic(PLAINTEXT, worker.public_key, context="c")
    b = seal_deterministic(PLAINTEXT + b"!", worker.public_key, context="c")
    assert a != b


def test_deterministic_unseal_roundtrip():
    worker = demo_worker_key()
    sealed = seal_deterministic(PLAINTEXT, worker.public_key, context="job-1")
    assert unseal(sealed, worker) == PLAINTEXT


def test_unseal_rejects_tampered_deterministic_ciphertext():
    worker = demo_worker_key()
    sealed = bytearray(seal_deterministic(PLAINTEXT, worker.public_key, context="c"))
    sealed[-1] ^= 0x01  # flip a ciphertext byte
    with pytest.raises(CryptoError):
        unseal(bytes(sealed), worker)


def test_unseal_rejects_tampered_sealedbox():
    worker = demo_worker_key()
    sealed = bytearray(seal(PLAINTEXT, worker.public_key))
    sealed[-1] ^= 0x01
    with pytest.raises(CryptoError):
        unseal(bytes(sealed), worker)


def test_unseal_wrong_worker_key_fails():
    worker = demo_worker_key()
    sealed = seal(PLAINTEXT, worker.public_key)
    from nacl.public import PrivateKey
    with pytest.raises(CryptoError):
        unseal(sealed, PrivateKey.generate())


def test_unseal_unknown_header_raises_value_error():
    with pytest.raises(ValueError, match="unknown envelope header"):
        unseal(b"Z" + b"garbage", demo_worker_key())


def test_unseal_empty_envelope_raises():
    with pytest.raises(ValueError, match="empty envelope"):
        unseal(b"", demo_worker_key())


def test_demo_worker_key_deterministic():
    assert bytes(demo_worker_key()) == bytes(demo_worker_key())


def test_load_or_create_worker_key_persists(tmp_path):
    kp = tmp_path / "worker.key"
    k1 = load_or_create_worker_key(kp)
    assert kp.exists() and (kp.stat().st_mode & 0o777) == 0o600
    assert bytes(k1) == bytes(load_or_create_worker_key(kp))


def test_plaintext_absent_from_envelope():
    worker = demo_worker_key()
    sealed = seal_deterministic(PLAINTEXT, worker.public_key, context="c")
    assert PLAINTEXT not in sealed
