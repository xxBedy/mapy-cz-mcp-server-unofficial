#!/usr/bin/env python3
"""Hlídač změn v REST API Mapy.com.

Specifikace API jsou veřejně dostupné, takže není důvod čekat, až se něco rozbije
v produkci — stáhnou se a porovnají s uloženým otiskem.

Ukládá se **otisk povrchu API**, ne kopie specifikací: seznam cest, parametrů,
jejich typů, enumerací a výchozích hodnot, plus názvy polí v odpovědích. To je
odvozený faktický popis rozhraní, ne rozmnožování cizího dokumentu, a diff nad
ním ukazuje přesně to, na čem tomuhle serveru záleží.

Použití:
    python scripts/api_drift.py            # porovná, nenulový návratový kód při změně
    python scripts/api_drift.py --update   # přepíše otisk aktuálním stavem
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

FINGERPRINT = Path(__file__).resolve().parent.parent / "api-fingerprint.json"

# Část specifikací je JSON, část YAML — rozhoduje přípona, kterou servíruje docs.
SPECS: dict[str, str] = {
    "commons": "https://api.mapy.com/v1/docs/commons/openapi.yaml",
    "geocode": "https://api.mapy.com/v1/docs/geocode/openapi.json",
    "routing": "https://api.mapy.com/v1/docs/routing/openapi.json",
    "elevation": "https://api.mapy.com/v1/docs/elevation/openapi.json",
    "static": "https://api.mapy.com/v1/docs/static/openapi.json",
    "maptiles": "https://api.mapy.com/v1/docs/maptiles/openapi.yaml",
    "timezone": "https://api.mapy.com/v1/docs/timezone/openapi.yaml",
}

TIMEOUT = 30


def fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310
        raw = response.read().decode("utf-8")
    if url.endswith(".json"):
        return json.loads(raw)
    import yaml  # importuje se až tady, ať běžný provoz serveru YAML nepotřebuje

    return yaml.safe_load(raw)


def _resolve(spec: dict[str, Any], node: Any, depth: int = 0) -> Any:
    """Rozbalí $ref, aby se otisk nelišil jen kvůli přejmenování komponenty."""
    if depth > 6:
        return node
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target: Any = spec
            for part in ref.lstrip("#/").split("/"):
                if not isinstance(target, dict) or part not in target:
                    return node
                target = target[part]
            return _resolve(spec, target, depth + 1)
        return {k: _resolve(spec, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(spec, item, depth + 1) for item in node]
    return node


def _param_fingerprint(spec: dict[str, Any], param: dict[str, Any]) -> dict[str, Any]:
    param = _resolve(spec, param)
    schema = param.get("schema") or {}
    if isinstance(schema.get("allOf"), list) and len(schema["allOf"]) == 1:
        merged = dict(schema["allOf"][0])
        merged.update({k: v for k, v in schema.items() if k != "allOf"})
        schema = merged

    enum = schema.get("enum")
    if enum is None and isinstance(schema.get("items"), dict):
        enum = schema["items"].get("enum")

    out: dict[str, Any] = {
        "in": param.get("in"),
        "required": bool(param.get("required")),
        "type": schema.get("type"),
    }
    if enum is not None:
        out["enum"] = sorted(str(e) for e in enum)
    for key in ("default", "minimum", "maximum", "minItems", "maxItems"):
        if key in schema:
            out[key] = schema[key]
    return out


def _schema_fields(spec: dict[str, Any], schema: Any, depth: int = 0) -> Any:
    """Názvy polí odpovědi. Hloubka stačí malá — jde o tvar, ne o úplný model."""
    if depth > 4:
        return "..."
    schema = _resolve(spec, schema, depth)
    if not isinstance(schema, dict):
        return None
    if schema.get("type") == "array":
        return [_schema_fields(spec, schema.get("items"), depth + 1)]
    props = schema.get("properties")
    if isinstance(props, dict):
        return {k: _schema_fields(spec, v, depth + 1) for k, v in sorted(props.items())}
    if "enum" in schema:
        return {"enum": sorted(str(e) for e in schema["enum"])}
    return schema.get("type")


def fingerprint(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for path, operations in sorted((spec.get("paths") or {}).items()):
        if not isinstance(operations, dict):
            continue
        for method, operation in sorted(operations.items()):
            if method not in ("get", "post", "put", "delete") or not isinstance(operation, dict):
                continue
            # Parametr může být zapsaný přes $ref (maptiles tak sdílí mapset i lang).
            # Rozbalit se musí dřív, než se sáhne na jméno — jinak by všechny takové
            # parametry spadly pod jeden klíč a jejich změny by se ztratily.
            params: dict[str, Any] = {}
            for raw in operation.get("parameters") or []:
                resolved = _resolve(spec, raw)
                if not isinstance(resolved, dict):
                    continue
                name = resolved.get("name")
                if not name:
                    continue
                params[str(name)] = _param_fingerprint(spec, resolved)
            ok = (operation.get("responses") or {}).get("200") or {}
            content = _resolve(spec, ok).get("content") or {}
            body = None
            for media, definition in content.items():
                if "json" in media and isinstance(definition, dict):
                    body = _schema_fields(spec, definition.get("schema"))
                    break
            paths[f"{method.upper()} {path}"] = {
                "parameters": dict(sorted(params.items())),
                "response200": body,
            }

    security = spec.get("components", {}).get("securitySchemes") or {}
    return {
        "servers": [s.get("url") for s in (spec.get("servers") or []) if isinstance(s, dict)],
        "security": {
            k: {"in": v.get("in"), "name": v.get("name")}
            for k, v in sorted(security.items())
            if isinstance(v, dict)
        },
        "operations": paths,
    }


def build() -> dict[str, Any]:
    return {name: fingerprint(name, fetch(url)) for name, url in sorted(SPECS.items())}


def _flatten(node: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(node, list):
        out[prefix] = json.dumps(node, ensure_ascii=False, sort_keys=True)
    else:
        out[prefix] = json.dumps(node, ensure_ascii=False)
    return out


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    flat_old, flat_new = _flatten(old), _flatten(new)
    lines: list[str] = []
    for key in sorted(set(flat_old) - set(flat_new)):
        lines.append(f"- ODEBRÁNO  {key} = {flat_old[key]}")
    for key in sorted(set(flat_new) - set(flat_old)):
        lines.append(f"+ PŘIBYLO   {key} = {flat_new[key]}")
    for key in sorted(set(flat_old) & set(flat_new)):
        if flat_old[key] != flat_new[key]:
            lines.append(f"~ ZMĚNĚNO   {key}: {flat_old[key]} → {flat_new[key]}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Porovná REST API Mapy.com s uloženým otiskem.")
    parser.add_argument("--update", action="store_true", help="Přepsat otisk aktuálním stavem.")
    args = parser.parse_args()

    try:
        current = build()
    except Exception as exc:  # noqa: BLE001 - v CI chceme důvod, ne traceback
        print(f"Nepodařilo se stáhnout specifikace: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.update or not FINGERPRINT.exists():
        FINGERPRINT.write_text(payload, encoding="utf-8")
        action = "aktualizován" if args.update else "vytvořen"
        print(f"Otisk {action}: {FINGERPRINT.name} ({len(current)} specifikací)")
        return 0

    stored = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    changes = diff(stored, current)
    if not changes:
        print(f"Beze změn — {len(current)} specifikací odpovídá otisku.")
        return 0

    print(f"REST API Mapy.com se změnilo ({len(changes)} rozdílů):\n")
    for line in changes:
        print(f"  {line}")
    print(
        "\nProjděte změny, upravte server a otisk obnovte příkazem:"
        "\n    python scripts/api_drift.py --update"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
