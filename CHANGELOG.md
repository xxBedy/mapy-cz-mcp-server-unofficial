# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New tool `mapy_elevation_profile_image`: renders a route's elevation profile as an
  SVG image (area + line chart, km/m axes, red peak marker, baked-in attribution).
  No new dependencies — the SVG is assembled as a string.
- English `README.md` (primary) alongside the Czech `README.cs.md`.
- Community health files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue/PR templates.
- `py.typed` marker so the package ships type hints to consumers.

## [0.1.0] - 2026-09-17

### Added
- Initial release. MCP server for the Mapy.com REST API with tools for geocoding,
  reverse geocoding, routing, distance matrices, elevation, route elevation profiles,
  static maps, panoramas, and time zones.
- Resources (`mapy://attribution`, `mapy://mapsets`, `mapy://timezones`,
  `mapy://tilejson/{mapset}`, `mapy://usage`) and prompts.
- Credit budgeting, rate limiting, and header-only API-key handling.
- API drift watcher (`scripts/api_drift.py` + weekly workflow) against `api-fingerprint.json`.
- CI (lint, format, tests on Python 3.10–3.13, build) and PyPI Trusted Publishing release workflow.

[Unreleased]: https://github.com/xxBedy/mapy-cz-mcp-server-unofficial/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/xxBedy/mapy-cz-mcp-server-unofficial/releases/tag/v0.1.0
