"""§5.1 místo místo souřadnic a §6.4 účtování kreditů."""

from __future__ import annotations

import httpx
import pytest
import respx

from mapy_mcp.config import Settings
from mapy_mcp.http.client import MapyClient
from mapy_mcp.http.credits import COST_GEOCODE, COST_ROUTING, CreditLedger
from mapy_mcp.http.errors import CreditBudgetExceeded, MapyError
from mapy_mcp.http.ratelimit import RateLimiter
from mapy_mcp.lib.coords import Coord
from mapy_mcp.lib.place import resolve_place
from mapy_mcp.tools.routing import route

PRAHA = {"items": [{"name": "Praha", "location": "Hlavní město Praha",
                    "position": {"lon": 14.4213, "lat": 50.0874}}]}


@respx.mock
async def test_coordinates_pass_through_without_geocoding(client):
    geocode_route = respx.get("https://api.mapy.com/v1/geocode")
    resolved = await resolve_place(client, Coord(lat=50.0, lon=14.0))

    assert resolved.credits == 0.0
    assert not geocode_route.called


@respx.mock
async def test_text_is_geocoded_and_billed(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(200, json=PRAHA)
    )
    resolved = await resolve_place(client, "Praha")

    assert resolved.credits == COST_GEOCODE
    assert resolved.coord.lat == 50.0874
    assert resolved.coord.lon == 14.4213
    assert "Praha" in resolved.label


@respx.mock
async def test_unfound_place_says_what_to_do(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    with pytest.raises(MapyError) as exc:
        await resolve_place(client, "Xyzzy")
    assert "souřadnice" in str(exc.value)


@respx.mock
async def test_route_by_name_reports_full_cost(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(200, json=PRAHA)
    )
    respx.get("https://api.mapy.com/v1/routing/route").mock(
        return_value=httpx.Response(200, json={"length": 205000, "duration": 7200})
    )
    result = await route(client, "Praha", "Brno")

    # 4 za trasu + 2x4 za geokódování obou názvů
    assert result.cost.credits == COST_ROUTING + 2 * COST_GEOCODE


@respx.mock
async def test_budget_stops_the_call_before_it_happens():
    settings = Settings(api_key="k", credit_budget=5)
    http = httpx.AsyncClient(base_url=settings.base_url)
    c = MapyClient(settings, ledger=CreditLedger(budget=5), limiter=RateLimiter(), client=http)
    api = respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(200, json=PRAHA)
    )
    await resolve_place(c, "Praha")  # 4 kredity, projde
    with pytest.raises(CreditBudgetExceeded):
        await resolve_place(c, "Brno")  # 8 > 5, neprojde

    assert api.call_count == 1  # druhé volání se vůbec neodeslalo
    await http.aclose()


def test_ledger_snapshot_admits_it_is_an_estimate():
    ledger = CreditLedger(budget=100)
    ledger.record("geocode", 4)
    snap = ledger.snapshot()
    assert snap["spentCredits"] == 4.0
    assert snap["remaining"] == 96.0
    assert "odhad" in snap["note"]


@respx.mock
async def test_bare_city_name_beats_similarly_named_poi(client):
    """Geokodér vrací na dotaz 'Brno' jako první přehradu, ne město.

    Pro plánování trasy je to špatně, proto přesná shoda názvu vyhrává
    a mezi shodami má přednost územní celek.
    """
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"name": "Brněnská přehrada", "type": "poi", "location": "Brno, Česko",
                     "position": {"lon": 16.5, "lat": 49.23}},
                    {"name": "Brno", "type": "regional.municipality", "location": "Česko",
                     "position": {"lon": 16.6068, "lat": 49.1951}},
                ]
            },
        )
    )
    resolved = await resolve_place(client, "Brno")
    assert resolved.coord.lon == 16.6068
    assert resolved.label.startswith("Brno")


@respx.mock
async def test_poi_query_still_resolves_to_the_poi(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"name": "Brněnská přehrada", "type": "poi", "location": "Brno, Česko",
                     "position": {"lon": 16.5, "lat": 49.23}},
                    {"name": "Brno", "type": "regional.municipality", "location": "Česko",
                     "position": {"lon": 16.6068, "lat": 49.1951}},
                ]
            },
        )
    )
    resolved = await resolve_place(client, "Brněnská přehrada")
    assert resolved.coord.lon == 16.5


@respx.mock
async def test_no_exact_match_keeps_api_ranking(client):
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(
            200,
            json={"items": [
                {"name": "Sněžka (1603 m)", "type": "poi",
                 "position": {"lon": 15.7396, "lat": 50.736}},
                {"name": "Sněžník", "type": "poi", "position": {"lon": 14.0, "lat": 50.8}},
            ]},
        )
    )
    resolved = await resolve_place(client, "Sněžka")
    assert resolved.coord.lat == 50.736


@respx.mock
async def test_exact_poi_match_does_not_beat_api_ranking(client):
    """Skutečná data pro dotaz 'Sněžka'.

    Přesná shoda je POI v Hradci Králové, ale hora se jmenuje 'Sněžka (1603 m)'
    a API ji řadí první. Povyšovat každou přesnou shodu by tu horu shodilo,
    proto se povyšují jen územní celky.
    """
    respx.get("https://api.mapy.com/v1/geocode").mock(
        return_value=httpx.Response(
            200,
            json={"items": [
                {"name": "Sněžka (1603 m)", "type": "poi", "location": "Pec pod Sněžkou, Česko",
                 "position": {"lon": 15.7396, "lat": 50.73602}},
                {"name": "Sněžka", "type": "poi", "location": "Hradec Králové, Česko",
                 "position": {"lon": 15.83, "lat": 50.21}},
            ]},
        )
    )
    resolved = await resolve_place(client, "Sněžka")
    assert resolved.coord.lat == 50.73602, "vybrala se restaurace místo hory"
