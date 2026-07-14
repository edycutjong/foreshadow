"""Merkle tree: domain separation, odd duplication, order sensitivity."""

from __future__ import annotations

import hashlib

import pytest

from foreshadow.crypto.merkle import (
    LEAF_PREFIX,
    NODE_PREFIX,
    hash_leaf,
    merkle_root,
    root_for_payloads,
)
from foreshadow.utils import canonical_json


def _h(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def test_hash_leaf_uses_leaf_prefix():
    payload = {"a": 1}
    assert hash_leaf(payload) == _h(LEAF_PREFIX + canonical_json(payload))


def test_hash_leaf_deterministic():
    assert hash_leaf({"a": 1, "b": 2}) == hash_leaf({"b": 2, "a": 1})


def test_leaf_and_node_prefixes_differ():
    assert LEAF_PREFIX != NODE_PREFIX


def test_single_leaf_root_is_leaf_hex():
    h = hash_leaf({"a": 1})
    assert merkle_root([h]) == h.hex()


def test_two_leaf_root_uses_node_prefix():
    a, b = hash_leaf({"a": 1}), hash_leaf({"b": 2})
    expected = _h(NODE_PREFIX + a + b).hex()
    assert merkle_root([a, b]) == expected


def test_odd_leaf_count_duplicates_last():
    a, b, c = hash_leaf({"i": 1}), hash_leaf({"i": 2}), hash_leaf({"i": 3})
    left = _h(NODE_PREFIX + a + b)
    right = _h(NODE_PREFIX + c + c)  # last duplicated
    expected = _h(NODE_PREFIX + left + right).hex()
    assert merkle_root([a, b, c]) == expected


def test_root_is_order_sensitive():
    a, b = hash_leaf({"a": 1}), hash_leaf({"b": 2})
    assert merkle_root([a, b]) != merkle_root([b, a])


def test_root_is_64_hex():
    root = merkle_root([hash_leaf({"i": i}) for i in range(5)])
    assert len(root) == 64
    bytes.fromhex(root)


def test_empty_leaf_set_raises():
    with pytest.raises(ValueError, match="empty leaf set"):
        merkle_root([])


def test_merkle_root_does_not_mutate_input():
    leaves = [hash_leaf({"i": 1}), hash_leaf({"i": 2}), hash_leaf({"i": 3})]
    snapshot = list(leaves)
    merkle_root(leaves)
    assert leaves == snapshot


def test_root_for_payloads_matches_manual():
    payloads = [{"i": 1}, {"i": 2}]
    assert root_for_payloads(payloads) == merkle_root([hash_leaf(p) for p in payloads])


def test_domain_separation_second_preimage_guard():
    # A leaf hash must never be reinterpretable as an inner node hash.
    leaf = hash_leaf({"x": 1})
    node = _h(NODE_PREFIX + leaf + leaf)
    assert leaf != node


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 8, 9, 16, 17])
def test_root_stable_across_sizes(n):
    leaves = [hash_leaf({"i": i}) for i in range(n)]
    assert merkle_root(leaves) == merkle_root(list(leaves))
