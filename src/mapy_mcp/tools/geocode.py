"""Geokódování — dopředné, našeptávání a reverzní."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ..config import Lang, get_settings
from ..http.client import MapyClient
from ..http.credits import COST_GEOCODE
from ..lib.coords import Coord, swap_warning
from ..lib.shape import Cost, GeocodeResult, ReverseGeocodeResult, shape_place

EntityType = Literal[
    "regional",
    "regional.country",
    "regional.region",
    "regional.municipality",
    "regional.municipality_part",
    "regional.street",
    "regional.address",
    "poi",
    "coordinate",
]


async def geocode(
    client: MapyClient,
    query: str,
    *,
    mode: Literal["search", "suggest"] = "search",
    limit: int = 5,
    types: list[EntityType] | None = None,
    locality: list[str] | None = None,
    near: Coord | None = None,
    near_precision_m: float | None = None,
    lang: Lang | None = None,
) -> GeocodeResult:
    settings = get_settings()
    params: dict[str, object] = {
        "query": query,
        "limit": max(1, min(limit, 15)),
        "lang": lang or settings.default_lang,
    }
    if types:
        params["type"] = list(types)
    if locality:
        params["locality"] = list(locality)
    if near is not None:
        params["preferNear"] = f"{near.lon},{near.lat}"
        if near_precision_m is not None:
            params["preferNearPrecision"] = near_precision_m

    path = "/v1/suggest" if mode == "suggest" else "/v1/geocode"
    payload = await client.get_json(
        path, params, group="geocode", operation=mode, credits=COST_GEOCODE
    )

    items = payload.get("items") if isinstance(payload, dict) else None
    places = [shape_place(item) for item in (items or []) if isinstance(item, dict)]

    warnings: list[str] = []
    if near is not None:
        w = swap_warning(near)
        if w:
            warnings.append(w)
    if not places:
        warnings.append(
            f"Pro dotaz '{query}' se nic nenašlo. Zkuste doplnit obec nebo kraj, "
            "případně mode='suggest' pro neúplné zadání."
        )

    return GeocodeResult(
        query=query,
        places=places,
        warnings=warnings,
        cost=Cost(credits=COST_GEOCODE, session_total=round(client.ledger.spent, 1)),
    )


async def reverse_geocode(
    client: MapyClient,
    lat: Annotated[float, Field(ge=-90, le=90)],
    lon: Annotated[float, Field(ge=-180, le=180)],
    *,
    lang: Lang | None = None,
) -> ReverseGeocodeResult:
    settings = get_settings()
    coord = Coord(lat=lat, lon=lon)
    payload = await client.get_json(
        "/v1/rgeocode",
        {"lon": coord.lon, "lat": coord.lat, "lang": lang or settings.default_lang},
        group="geocode",
        operation="rgeocode",
        credits=COST_GEOCODE,
    )

    items = payload.get("items") if isinstance(payload, dict) else None
    places = [shape_place(item) for item in (items or []) if isinstance(item, dict)]

    warnings: list[str] = []
    w = swap_warning(coord)
    if w:
        warnings.append(w)

    return ReverseGeocodeResult(
        lat=coord.lat,
        lon=coord.lon,
        places=places,
        warnings=warnings,
        cost=Cost(credits=COST_GEOCODE, session_total=round(client.ledger.spent, 1)),
    )
