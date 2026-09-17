# Contributing

Thanks for your interest in improving this project! This is an **unofficial** MCP server for the
Mapy.com REST API. Contributions of all sizes are welcome — bug reports, fixes, new tool coverage,
docs, and translations.

> 🇨🇿 Preferuješ češtinu? Klidně piš issue i PR česky — projekt je česko-anglicky dvojjazyčný.

## Getting started

Prerequisites: [`uv`](https://docs.astral.sh/uv/) and Python 3.10+ (CI tests 3.10–3.13).

```bash
git clone https://github.com/xxBedy/mapy-cz-mcp-server-unofficial
cd mapy-cz-mcp-server-unofficial
uv sync --extra dev
```

You do **not** need a Mapy.com API key to develop or run the tests — the suite runs against recorded
fixtures via `respx` and spends no credits. A key is only needed to make real API calls at runtime.

## Development workflow

```bash
uv run pytest                          # run the test suite (fixtures, no credits)
uv run ruff check src tests scripts    # lint
uv run ruff format src tests scripts   # auto-format
uv run python -m mapy_mcp              # run the server on stdio
```

CI runs exactly these checks (`ruff check`, `ruff format --check`, `pytest`) across Python 3.10–3.13,
plus `uv build` + `twine check`. Run them locally before pushing and you should be green.

## Making a change

1. Create a branch off `main` (e.g. `fix/geocode-limit`, `feat/isochrone-tool`).
2. Write or update tests. New behaviour needs a test; bug fixes should add a regression test.
   Tests use fixtures — see `tests/conftest.py` and existing tests for the `respx` pattern.
3. Keep the code style consistent (`ruff format`). Line length is 100.
4. Update the docs when behaviour changes: both `README.md` (English) and `README.cs.md` (Czech),
   and add a `CHANGELOG.md` entry under `## [Unreleased]`.
5. Open a pull request against `main`. Fill in the PR template. CI must pass; `main` requires a PR.

## API drift

The server tracks the shape of the upstream API in `api-fingerprint.json`. If you adapt the server to
an upstream change, refresh the fingerprint:

```bash
uv run python scripts/api_drift.py            # show the diff
uv run python scripts/api_drift.py --update   # accept and store the new surface
```

## Credits & attribution

Map data from the Mapy.com API may only be displayed **with attribution** — please keep the
`attribution` fields and the `mapy://attribution` resource intact in any change that touches responses.

## Reporting bugs & requesting features

Use the [issue templates](https://github.com/xxBedy/mapy-cz-mcp-server-unofficial/issues/new/choose).
Please **never paste your `MAPY_API_KEY`** (or any secret) into an issue, PR, or log excerpt.

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
