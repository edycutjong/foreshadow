# Security Policy

## Supported Versions
| Version | Supported |
|---|---|
| latest (`main`) | ✅ |

## Reporting a Vulnerability
Please **do not** open a public issue for security vulnerabilities. Instead,
report them privately:

- Email **edy.cu@live.com**, or
- Use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) (Security → Report a vulnerability).

You'll get an acknowledgment within 48 hours and a resolution timeline after
triage. Please give us a reasonable window to patch before public disclosure.

## Notes specific to this project
- The default `fake` transport never makes a network call (enforced by a
  session-wide socket guard in tests and `scripts/verify_offline.py`) and
  never requires or reads real API keys.
- The live Qwen transport reads `DASHSCOPE_API_KEY` from the environment only
  — it is never logged, written to disk, or included in the signed manifest.
- Demo signing keys (`foreshadow.crypto.signing`) are derived deterministically
  from a public seed for reproducible replays — they intentionally prove
  *mechanism*, not identity, and must never be treated as real key material.
