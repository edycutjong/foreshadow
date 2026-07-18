# Contributing

Thanks for your interest in improving Foreshadow!

## Getting Started
1. Fork the repo and branch from `main`: `git checkout -b feat/your-feature`
2. Create a venv and install with dev extras:
   ```bash
   python -m venv .venv
   ./.venv/bin/pip install -e ".[dev]"
   ```
3. (Optional) Copy the env template if you want to exercise the live Qwen
   transport: `cp .env.example .env` and set `DASHSCOPE_API_KEY`. The default
   `fake` transport needs no key at all.
4. Run the offline demo: `./.venv/bin/foreshadow replay --incident forklift`

## Before You Open a PR
- `ruff check .` passes (lint).
- `pytest --cov=src/foreshadow` passes — all 420 tests are offline via a
  session-wide socket guard.
- `python scripts/verify_offline.py` exits `0` (socket-guarded replay + I1-I4
  invariant re-verification).
- `mypy src` — advisory, but please don't add new errors.
- Add or update tests for any behavior change.
- Keep commits conventional (`feat:`, `fix:`, `docs:`, `chore:`).

## Reporting Bugs / Requesting Features
Open an issue using the provided templates. Include repro steps, expected vs.
actual behavior, and environment details.
