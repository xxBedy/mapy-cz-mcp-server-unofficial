"""Hlídač změn v REST API (§9).

Testuje se porovnávací logika, ne stahování — CI job si specifikace stáhne sám.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from api_drift import FINGERPRINT, SPECS, diff, fingerprint  # noqa: E402

SPEC = {
    "servers": [{"url": "https://api.mapy.com/"}],
    "paths": {
        "/v1/thing": {
            "get": {
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 5, "maximum": 15},
                    },
                    {"$ref": "#/components/parameters/Lang"},
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Result"}}
                        }
                    }
                },
            }
        }
    },
    "components": {
        "parameters": {
            "Lang": {
                "name": "lang",
                "in": "query",
                "schema": {"type": "string", "enum": ["cs", "en"]},
            }
        },
        "schemas": {"Result": {"type": "object", "properties": {"items": {"type": "array"}}}},
        "securitySchemes": {
            "headerApiKey": {"type": "apiKey", "in": "header", "name": "X-Mapy-Api-Key"}
        },
    },
}


def test_fingerprint_resolves_refs():
    """Přejmenování komponenty nesmí vypadat jako změna rozhraní."""
    fp = fingerprint("test", SPEC)
    params = fp["operations"]["GET /v1/thing"]["parameters"]
    assert params["lang"]["enum"] == ["cs", "en"]
    assert params["limit"]["maximum"] == 15


def test_fingerprint_records_auth_scheme():
    # Past 3.4: kdyby Mapy.com přejmenovaly hlavičku s klíčem, musíme to vidět.
    fp = fingerprint("test", SPEC)
    assert fp["security"]["headerApiKey"]["name"] == "X-Mapy-Api-Key"


def test_no_diff_against_itself():
    fp = fingerprint("test", SPEC)
    assert diff(fp, fp) == []


def test_diff_catches_removed_endpoint():
    before = fingerprint("test", SPEC)
    after = {**before, "operations": {}}
    changes = diff(before, after)
    assert any("ODEBRÁNO" in c and "/v1/thing" in c for c in changes)


def test_diff_catches_new_required_parameter():
    before = fingerprint("test", SPEC)
    after = json.loads(json.dumps(before))
    after["operations"]["GET /v1/thing"]["parameters"]["novy"] = {
        "in": "query",
        "required": True,
        "type": "string",
    }
    changes = diff(before, after)
    assert any("PŘIBYLO" in c and "novy" in c for c in changes)


def test_diff_catches_changed_enum():
    before = fingerprint("test", SPEC)
    after = json.loads(json.dumps(before))
    after["operations"]["GET /v1/thing"]["parameters"]["lang"]["enum"] = ["cs", "en", "de"]
    changes = diff(before, after)
    assert any("ZMĚNĚNO" in c and "lang" in c for c in changes)


def test_stored_fingerprint_covers_every_spec():
    """Otisk v repozitáři musí odpovídat seznamu sledovaných specifikací."""
    stored = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    assert set(stored) == set(SPECS)


def test_stored_fingerprint_has_the_endpoints_the_server_calls():
    stored = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    used = {
        "geocode": ["GET /v1/geocode", "GET /v1/suggest", "GET /v1/rgeocode"],
        "routing": ["GET /v1/routing/route", "GET /v1/routing/matrix-m"],
        "elevation": ["GET /v1/elevation"],
        "static": ["GET /v1/static/map", "GET /v1/static/pano"],
        "timezone": [
            "GET /v1/timezone/coordinate",
            "GET /v1/timezone/timezone",
            "GET /v1/timezone/list-timezones",
        ],
    }
    for spec, operations in used.items():
        for operation in operations:
            assert operation in stored[spec]["operations"], f"{spec}: {operation} zmizel"
