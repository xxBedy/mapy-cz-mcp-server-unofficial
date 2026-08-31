"""Převzorkování trasy na body, na které se dá zeptat výškového API.

Endpoint /v1/elevation bere maximálně 256 pozic na volání, zatímco geometrie trasy
má běžně tisíce bodů. Vzorkuje se proto ekvidistantně podle ujeté vzdálenosti —
ne každý n-tý bod, protože geometrie je v zatáčkách hustší než na rovině a prostý
krok by je nadvážil.
"""

from __future__ import annotations

from .coords import Coord, haversine_m

MAX_POSITIONS_PER_CALL = 256


def cumulative_distances(points: list[tuple[float, float]]) -> list[float]:
    """Kumulativní vzdálenost podél lomené čáry v metrech."""
    out = [0.0]
    for prev, cur in zip(points, points[1:], strict=False):
        out.append(out[-1] + haversine_m(prev, cur))
    return out


def resample(points: list[tuple[float, float]], count: int) -> list[Coord]:
    """Vybere ``count`` ekvidistantních bodů podél trasy (včetně začátku a konce)."""
    if not points:
        return []
    if count <= 0:
        return []
    if len(points) == 1 or count == 1:
        return [Coord(lat=points[0][0], lon=points[0][1])]
    if len(points) <= count:
        return [Coord(lat=lat, lon=lon) for lat, lon in points]

    dists = cumulative_distances(points)
    total = dists[-1]
    if total <= 0:
        return [Coord(lat=points[0][0], lon=points[0][1])]

    step = total / (count - 1)
    out: list[Coord] = []
    idx = 0
    for i in range(count):
        target = min(step * i, total)
        while idx < len(dists) - 2 and dists[idx + 1] < target:
            idx += 1
        span = dists[idx + 1] - dists[idx]
        t = 0.0 if span <= 0 else (target - dists[idx]) / span
        lat = points[idx][0] + (points[idx + 1][0] - points[idx][0]) * t
        lon = points[idx][1] + (points[idx + 1][1] - points[idx][1]) * t
        out.append(Coord(lat=lat, lon=lon))
    return out


def chunk(items: list[Coord], size: int = MAX_POSITIONS_PER_CALL) -> list[list[Coord]]:
    """Rozdělí body na dávky, které projdou jedním voláním API."""
    return [items[i : i + size] for i in range(0, len(items), size)]
