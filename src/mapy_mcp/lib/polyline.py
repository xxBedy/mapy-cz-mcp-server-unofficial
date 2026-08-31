"""Dekódování Google polyline.

Mapy.com vrací geometrii tras ve formátech ``polyline`` (přesnost 5) a ``polyline6``
(přesnost 6). Google formát kóduje **latitude první**, na rozdíl od zbytku API —
dekodér proto vrací dvojice (lat, lon).
"""

from __future__ import annotations


def decode(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    """Rozbalí zakódovanou polyline na seznam bodů (lat, lon)."""
    factor = float(10**precision)
    points: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lon = 0
    length = len(encoded)

    while index < length:
        for target in ("lat", "lon"):
            shift = 0
            result = 0
            while True:
                if index >= length:
                    return points
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if target == "lat":
                lat += delta
            else:
                lon += delta
        points.append((lat / factor, lon / factor))

    return points


def decode_geometry(geometry: object, fmt: str) -> list[tuple[float, float]]:
    """Vytáhne body z geometrie trasy bez ohledu na zvolený formát.

    GeoJSON má souřadnice v pořadí [lon, lat], polyline naopak. Sjednocuje se na (lat, lon).
    """
    if fmt in ("polyline", "polyline6") and isinstance(geometry, str):
        return decode(geometry, 6 if fmt == "polyline6" else 5)

    if isinstance(geometry, dict):
        geom = geometry.get("geometry", geometry)
        if isinstance(geom, dict):
            coords = geom.get("coordinates")
            if isinstance(coords, list):
                out: list[tuple[float, float]] = []
                for pair in coords:
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                        out.append((float(pair[1]), float(pair[0])))
                    elif isinstance(pair, dict) and "lat" in pair and "lon" in pair:
                        out.append((float(pair["lat"]), float(pair["lon"])))
                return out
    return []
