#!/usr/bin/env python3
"""Judge-facing offline proof (COMPLEXITY.md section 5).

1. Installs a socket guard: ANY network attempt raises immediately.
2. Replays the "forklift" demo film end-to-end (FakeQwen, demo keys).
3. Verifies the signed manifest: signature, Merkle root, invariants I1-I4.
4. Confirms the manifest matches the committed fixture cache byte-for-byte.

Exit 0 = everything reproduced and verified with zero network and zero keys.
"""

from __future__ import annotations

import socket
import sys
import tempfile
from pathlib import Path


def install_socket_guard() -> None:
    def _blocked(*args, **kwargs):
        raise RuntimeError("network disabled by verify_offline.py socket guard")

    socket.socket.connect = _blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]


def main() -> int:
    install_socket_guard()
    # prove the guard actually guards
    try:
        socket.create_connection(("example.com", 443), timeout=1)
    except RuntimeError as exc:
        print(f"[guard] {exc}")
    else:
        print("[guard] FAILED: socket guard did not block network")
        return 1

    from foreshadow.pipeline.engine import replay
    from foreshadow.provenance import verify_manifest
    from foreshadow.schemas import Manifest

    with tempfile.TemporaryDirectory(prefix="foreshadow-offline-") as tmp:
        print("[replay] rebuilding incident 'forklift' at $4 (FakeQwen, offline)")
        result, matches_cache = replay("forklift", 4.0, home=Path(tmp))
        print(f"[replay] spent ${result.spent_usd:.4f}; merkle root {result.merkle_root}")

        manifest = Manifest.load(result.manifest_path)
        report = verify_manifest(manifest, base_dir=result.job_dir,
                                 film_path=result.job_dir / "film.mp4")
        for check in report.checks:
            print(f"[verify] {'PASS' if check.passed else 'FAIL'} "
                  f"{check.name}: {check.detail}")
        if not report.ok:
            print("[verify] FAILED")
            return 1

        if matches_cache is True:
            print("[cache ] manifest matches committed fixtures/cache (byte-identical)")
        elif matches_cache is None:
            print("[cache ] no committed cache found for forklift@$4")
            return 1
        else:
            print("[cache ] MISMATCH vs committed cache — determinism broken")
            return 1

    print("OFFLINE VERIFICATION PASS (zero network, zero keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
