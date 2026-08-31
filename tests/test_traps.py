"""Pasti 3.2 a 3.3 — záporné kódy v matici a sentinel ve výškách."""

from __future__ import annotations

import httpx
import respx

from mapy_mcp.lib.coords import Coord
from mapy_mcp.tools.elevation import _clean_elevation, elevation
from mapy_mcp.tools.routing import route_matrix


def test_elevation_sentinel_becomes_none():
    assert _clean_elevation(-100000.0) is None
    assert _clean_elevation(325.5) == 325.5
    assert _clean_elevation(None) is None


def test_negative_elevation_below_sea_level_is_kept():
    # Mrtvé moře je pod hladinou, ale to je platná výška — sentinel je -100000.
    assert _clean_elevation(-430.5) == -430.5


@respx.mock
async def test_matrix_negative_length_becomes_unreachable(client):
    respx.get("https://api.mapy.com/v1/routing/matrix-m").mock(
        return_value=httpx.Response(
            200,
            json={
                "matrix": [
                    [{"length": 2351, "duration": 189}, {"length": -3, "duration": -3}],
                    [{"length": -2, "duration": -2}, {"length": 900, "duration": 60}],
                ]
            },
        )
    )
    result = await route_matrix(
        client,
        [Coord(lat=50.0, lon=14.0), Coord(lat=50.1, lon=14.1)],
        ends=[Coord(lat=49.0, lon=16.0), Coord(lat=49.1, lon=16.1)],
    )

    assert result.unreachable_count == 2
    bad = [c for c in result.cells if c.unreachable]
    # Záporné hodnoty se nikdy nepropíší jako délka.
    assert all(c.length_m is None for c in bad)
    assert "silniční sítě" in bad[0].reason
    assert "500 km" in bad[1].reason
    good = [c for c in result.cells if not c.unreachable]
    assert [c.length_m for c in good] == [2351, 900]


@respx.mock
async def test_elevation_gaps_are_counted_not_averaged(client):
    respx.get("https://api.mapy.com/v1/elevation").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"elevation": 300.0, "position": {"lon": 14.0, "lat": 50.0}},
                    {"elevation": -100000.0, "position": {"lon": 14.1, "lat": 50.1}},
                    {"elevation": 500.0, "position": {"lon": 14.2, "lat": 50.2}},
                ]
            },
        )
    )
    result = await elevation(
        client,
        [Coord(lat=50.0, lon=14.0), Coord(lat=50.1, lon=14.1), Coord(lat=50.2, lon=14.2)],
    )
    assert result.data_gaps == 1
    assert result.min_m == 300.0
    assert result.max_m == 500.0
    assert result.points[1].elevation_m is None
