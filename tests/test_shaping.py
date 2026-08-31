"""Past 3.7 a §7 — ekonomika tokenů."""

from __future__ import annotations

import httpx
import pytest
import respx

from mapy_mcp.http.errors import MapyError
from mapy_mcp.lib.coords import Coord
from mapy_mcp.lib.shape import human_duration, sparkline
from mapy_mcp.tools.geocode import geocode
from mapy_mcp.tools.routing import route

GEOCODE_ITEM = {
    "name": "Praha",
    "label": "Obec",
    "position": {"lon": 14.4213, "lat": 50.0874},
    "bbox": [14.2, 49.9, 14.7, 50.2],
    "type": "regional.municipality",
    "location": "Hlavní město Praha",
    "regionalStructure": [
        {"name": "Praha", "type": "regional.municipality"},
        {"name": "Hlavní město Praha", "type": "regional.region"},
        {"name": "Česko", "type": "regional.country", "isoCode": "CZ"},
    ],
}


@respx.mock
async def test_geocode_drops_bbox_and_flattens_region(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(200, json={"items": [GEOCODE_ITEM]})
    )
    result = await geocode(client, "Praha")
    place = result.places[0]

    assert place.region == "Praha, Hlavní město Praha, Česko"
    # bbox je největší část syrové odpovědi a model ho nepotřebuje
    assert "bbox" not in place.model_dump()


@respx.mock
async def test_route_omits_geometry_by_default(client):
    respx.get("https://api.mapy.com/v1/routing/route").mock(
        return_value=httpx.Response(
            200,
            json={
                "length": 205000,
                "duration": 7200,
                "geometry": "a" * 50000,
                "parts": [{"length": 205000, "duration": 7200}],
            },
        )
    )
    result = await route(client, Coord(lat=50.0, lon=14.4), Coord(lat=49.2, lon=16.6))

    assert result.geometry is None
    assert result.length_km == 205.0
    assert result.duration_human == "2 h 0 min"
    # Souhrn musí být řádově menší než syrová odpověď.
    assert len(result.model_dump_json()) < 1000


@respx.mock
async def test_route_returns_geometry_when_asked(client):
    respx.get("https://api.mapy.com/v1/routing/route").mock(
        return_value=httpx.Response(200, json={"length": 100, "duration": 60, "geometry": "abc"})
    )
    result = await route(
        client, Coord(lat=50.0, lon=14.4), Coord(lat=49.2, lon=16.6), geometry="polyline"
    )
    assert result.geometry == "abc"
    assert result.geometry_format == "polyline6"


@respx.mock
async def test_route_rejects_too_many_waypoints(client):
    via = [Coord(lat=50.0 + i / 100, lon=14.0) for i in range(16)]
    with pytest.raises(MapyError) as exc:
        await route(client, Coord(lat=50.0, lon=14.0), Coord(lat=49.0, lon=16.0), via=via)
    assert "15" in str(exc.value)


@respx.mock
async def test_departure_without_traffic_warns(client):
    respx.get("https://api.mapy.com/v1/routing/route").mock(
        return_value=httpx.Response(200, json={"length": 100, "duration": 60})
    )
    result = await route(
        client,
        Coord(lat=50.0, lon=14.4),
        Coord(lat=49.2, lon=16.6),
        route_type="car_fast",
        departure="2026-09-01T08:00:00",
    )
    assert any("car_fast_traffic" in w for w in result.warnings)


def test_human_duration_reads_naturally():
    assert human_duration(45) == "45 s"
    assert human_duration(600) == "10 min"
    assert human_duration(3900) == "1 h 5 min"


def test_sparkline_shows_shape_not_numbers():
    assert sparkline([100, 200, 300]) == "▁▄█"
    assert sparkline([]) == ""
    assert sparkline([5, 5, 5]) == "▁▁▁"


def test_sparkline_is_capped_so_it_does_not_flood_context():
    from mapy_mcp.lib.shape import SPARKLINE_MAX_WIDTH

    long_profile = [float(i) for i in range(256)]
    out = sparkline(long_profile)
    assert len(out) == SPARKLINE_MAX_WIDTH
    # Stoupající profil musí po zhuštění pořád stoupat.
    assert out[0] == "▁" and out[-1] == "█"
