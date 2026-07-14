"""Merkle tree over manifest leaves (docs/SPEC-PROVENANCE.md section 3).

Construction:
- leaf hash  = SHA-256(0x00 || canonical_json(leaf_payload))
- inner hash = SHA-256(0x01 || left || right)
- odd node at any level: the last hash is duplicated (Bitcoin-style)
- domain-separation prefixes (0x00/0x01) block second-preimage attacks that
  reinterpret an inner node as a leaf.

The tree is order-sensitive by design: leaf order is part of what is signed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from ..utils import canonical_json

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


def hash_leaf(leaf_payload: dict[str, Any]) -> bytes:
    return hashlib.sha256(LEAF_PREFIX + canonical_json(leaf_payload)).digest()


def _hash_node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def merkle_root(leaf_hashes: Sequence[bytes]) -> str:
    """Root hex of the tree; raises on an empty leaf set (nothing to sign)."""
    if not leaf_hashes:
        raise ValueError("merkle_root: empty leaf set")
    level = list(leaf_hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def root_for_payloads(leaf_payloads: Sequence[dict[str, Any]]) -> str:
    return merkle_root([hash_leaf(p) for p in leaf_payloads])
