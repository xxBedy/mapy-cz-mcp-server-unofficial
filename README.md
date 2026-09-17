# Mapy.com MCP Server (unofficial)

*🇬🇧 English · 🇨🇿 [Čeština](README.cs.md)*

[![CI](https://github.com/xxBedy/mapy-cz-mcp-server-unofficial/actions/workflows/ci.yml/badge.svg)](https://github.com/xxBedy/mapy-cz-mcp-server-unofficial/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mapy-cz-mcp-server-unofficial)](https://pypi.org/project/mapy-cz-mcp-server-unofficial/)
[![Python](https://img.shields.io/pypi/pyversions/mapy-cz-mcp-server-unofficial)](https://pypi.org/project/mapy-cz-mcp-server-unofficial/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An MCP server for the [Mapy.com REST API](https://developer.mapy.com/en/rest-api/) — geocoding, route
planning, distance matrices, elevation, route elevation profiles, static maps, panoramas and time zones.

> **Unofficial project.** Not a product or service of Seznam.cz a.s. Map data © Seznam.cz a.s. and others.

The design write-up and the API pitfalls it works around are in [DESIGN.md](DESIGN.md).

## Installation

You need an API key from [developer.mapy.com](https://developer.mapy.com/account/). The key must have the
services you intend to use enabled in the portal — otherwise the API returns `403` even with a valid key.

### Claude Code

```bash
claude mcp add mapy --env MAPY_API_KEY=your_key -- uvx mapy-cz-mcp-server-unofficial
```

### Claude Desktop

```json
{
  "mcpServers": {
    "mapy": {
      "command": "uvx",
      "args": ["mapy-cz-mcp-server-unofficial"],
      "env": { "MAPY_API_KEY": "your_key" }
    }
  }
}
```

## Tools

| Tool | What it does | Credits |
|---|---|---|
| `mapy_geocode` | Find a place by name or address (`mode="suggest"` for autocomplete) | 4 |
| `mapy_reverse_geocode` | Resolve an address and regional structure for coordinates | 4 |
| `mapy_route` | Plan a route between places, optionally via waypoints | 4 + geocoding |
| `mapy_route_matrix` | Distance/time matrix between multiple points (max 100 cells) | ~0.4 / cell |
| `mapy_elevation` | Elevation for up to 256 points | 4 |
| `mapy_elevation_profile` | Route elevation profile: ascent, descent, sparkline | 8+ |
| `mapy_elevation_profile_image` | Render a route's elevation profile as an SVG image | 8+ |
| `mapy_static_map` | A map image with markers and shapes — the model can see it | 4 |
| `mapy_panorama` | A panoramic image from a place | 4 |
| `mapy_timezone` | Time zone, local time and offset | 1 |

Every coordinate-taking tool accepts **either a place name or coordinates**:
`start="Prague"` works the same as `start={"lat": 50.087, "lon": 14.421}`.

## Resources

| URI | Contents |
|---|---|
| `mapy://attribution` | Required attribution text and logo-display rules |
| `mapy://mapsets` | Map sets for static maps and for tiles |
| `mapy://timezones` | List of IANA time zones |
| `mapy://tilejson/{mapset}` | TileJSON for a client rendering its own map |
| `mapy://usage` | Credits spent in this session |

## Prompts

`naplanuj-vylet` (plan a trip), `porovnej-trasy` (compare routes), `kde-to-je` (where is it).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MAPY_API_KEY` | — | API key (required for calls, not for starting the server) |
| `MAPY_DEFAULT_LANG` | `cs` | Response language |
| `MAPY_CREDIT_BUDGET` | — | Per-session credit ceiling; tools refuse to call once exceeded |
| `MAPY_BASE_URL` | `https://api.mapy.com` | API base URL |
| `MAPY_TIMEOUT` | `20.0` | Request timeout in seconds |
| `MAPY_IMAGE_DIR` | temp dir | Where to save images for `output="file"` |

The key is sent **only in the `X-Mapy-Api-Key` header**, never in the URL — so it stays out of logs and
history.

## Attribution

Using data from the API requires [displaying attribution](https://developer.mapy.com/en/rest-api-mapy-cz/atribution/).
Static maps and panoramas have attribution burned into the image. For geocoding and routing your application
must display it — every non-image response therefore carries an `attribution` field, and the full text is in
the `mapy://attribution` resource.

## Development

```bash
uv sync --extra dev
uv run pytest                          # tests run against fixtures, no credits
uv run ruff check src tests scripts
uv run ruff format src tests scripts
uv run python -m mapy_mcp              # run on stdio
```

Tests run against stored fixtures via `respx`, so they need no API key and spend no credits.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor guide.

## API drift watcher

The Mapy.com REST API specs are public, so there's no reason to wait for something to break in production:

```bash
uv run python scripts/api_drift.py            # compare against api-fingerprint.json
uv run python scripts/api_drift.py --update   # refresh the fingerprint after adapting to changes
```

`api-fingerprint.json` stores a **fingerprint of the API surface** — paths, parameters, their types,
enumerations and limits, plus the auth scheme. It is not a copy of the specs but a derived description of the
interface, so a diff shows exactly what this server cares about.

The `Mapy.com REST API watcher` workflow runs every Monday. When the interface changes the job fails and opens
an issue with the diff (or comments on an already-open one).

## Releasing

Publishing goes through [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/), so there is no
API token in the repository.

One-time setup:

1. On PyPI, register a pending publisher for `mapy-cz-mcp-server-unofficial`: repository
   `xxBedy/mapy-cz-mcp-server-unofficial`, workflow `release.yml`, environment `pypi`.
2. On GitHub, create the `pypi` environment (Settings → Environments).

Each release:

```bash
# 1. bump version in pyproject.toml
# 2. tag it — the tag must match the version, or the workflow fails
git tag v0.1.0 && git push origin v0.1.0
```

The `release.yml` workflow runs the full CI, builds the package and publishes it.

## Contributing

Contributions are welcome! Read [CONTRIBUTING.md](CONTRIBUTING.md) (how to set up your environment, run tests
and open a PR) and the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Report vulnerabilities per
[SECURITY.md](SECURITY.md). Notable changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE). The license covers this server's code, not the map data, which is subject to the
[Mapy.com terms](https://developer.mapy.com/en/terms-and-conditions/).
