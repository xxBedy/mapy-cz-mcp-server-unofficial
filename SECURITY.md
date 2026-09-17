# Security Policy

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest released version on PyPI and to `main`.

## Reporting a vulnerability

Please report security issues **privately**, not in a public issue:

- Preferred: open a [GitHub private security advisory](https://github.com/xxBedy/mapy-cz-mcp-server-unofficial/security/advisories/new).
- Alternatively, contact the maintainer via the email on their [GitHub profile](https://github.com/xxBedy).

Please include a description, reproduction steps, and the affected version. You can expect an initial
response within a reasonable time; we'll coordinate a fix and disclosure with you.

## Handling of API keys

This server talks to the Mapy.com API using a `MAPY_API_KEY`. A few important notes:

- The key is read from the environment and sent **only in the `X-Mapy-Api-Key` request header** — never
  in a URL, so it does not leak into logs, history, or referrer headers.
- The key is **not** required to start the server or to run the test suite (tests use recorded fixtures).
- **Never commit a key** or paste one into an issue, pull request, log excerpt, or screenshot. `.env`
  and `.env.*` are gitignored for this reason.
- If you believe a key has been exposed, rotate it in the
  [Mapy.com developer portal](https://developer.mapy.com/account/) immediately.

This is an unofficial project and is not affiliated with Seznam.cz a.s. Vulnerabilities in the upstream
Mapy.com API itself should be reported to Seznam.cz, not here.
