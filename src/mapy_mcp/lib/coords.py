"""Souřadnice a jediné místo, kde se řeší jejich pořadí.

REST API Mapy.com používá všude pořadí ``lon,lat`` — longitude první. Jazykový model
ale téměř vždy píše „lat, lon“, protože tak se to říká. Když se to zamění, trasa
Praha–Brno skončí v Indickém oceánu a odpověď přitom vypadá naprosto validně.

Obrana je dvojí:

1. Nástroje nikdy nepřijímají pole ``[x, y]``, jen pojmenovaná pole ``lat`` a ``lon``.
   Pydantic navíc do JSON schématu propíše minimum/maximum, takže model vidí rozsahy
   ještě než zavolá. Hodnota mimo rozsah je tím pádem hlasitá chyba.
2. Zbývá tichý případ: obě hodnoty jsou v platném rozsahu, ale prohozené. Na to je
   ``swap_warning()`` — vrací varování, nikdy neopravuje. Tichá autokorekce by byla
   horší než chyba, protože by zamaskovala skutečný záměr volajícího.

Převod do pořadí API je jen v ``to_api_coord()``. Jinde v projektu se pořadí neřeší.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel, Field

EARTH_RADIUS_M = 6_371_008.8

# Hrubý obalový obdélník ČR a SR. Slouží jen k detekci prohození, ne k filtrování —
# server funguje celosvětově.
CZSK_BBOX = (11.9, 47.6, 22.7, 51.2)  # minLon, minLat, maxLon, maxLat


class Coord(BaseModel):
    """Bod na mapě. Pozor: API chce lon,lat — převod dělá to_api_coord()."""

    lat: float = Field(
        ge=-90,
        le=90,
        description="Zeměpisná šířka ve stupních. Kladná na sever, záporná na jih.",
    )
    lon: float = Field(
        ge=-180,
        le=180,
        description="Zeměpisná délka ve stupních. Kladná na východ, záporná na západ.",
    )

    def __str__(self) -> str:
        return f"{self.lat:.5f},{self.lon:.5f}"


def to_api_coord(coord: Coord) -> str:
    """Jediný převod do pořadí, které chce API: longitude první."""
    return f"{coord.lon},{coord.lat}"


def to_api_coords(coords: list[Coord]) -> str:
    """Seznam bodů ve tvaru, který API přijímá jako středníkem oddělený výčet."""
    return ";".join(to_api_coord(c) for c in coords)


def _in_bbox(lon: float, lat: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = CZSK_BBOX
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def swap_warning(coord: Coord) -> str | None:
    """Varuje, když bod vypadá jako prohozené lat/lon.

    Vrací varování jen v jednoznačném případě: takto zadaný bod v ČR/SR neleží,
    ale po prohození ano. Nikdy neopravuje — jen upozorní.
    """
    if _in_bbox(coord.lon, coord.lat):
        return None
    if abs(coord.lat) <= 90 and _in_bbox(coord.lat, coord.lon):
        return (
            f"Bod lat={coord.lat}, lon={coord.lon} leží mimo ČR/SR, ale po prohození "
            f"hodnot by padl do ČR/SR (lat={coord.lon}, lon={coord.lat}). "
            "Zkontrolujte, že jste nezaměnili šířku a délku."
        )
    return None


def collect_warnings(coords: list[Coord]) -> list[str]:
    seen: list[str] = []
    for c in coords:
        w = swap_warning(c)
        if w and w not in seen:
            seen.append(w)
    return seen


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Vzdálenost dvou bodů (lat, lon) ve metrech."""
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(h)))
