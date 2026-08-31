"""Plánování tras a maticové plánování."""

from __future__ import annotations

from typing import Literal

from ..config import Lang, get_settings
from ..http.client import MapyClient
from ..http.credits import COST_MATRIX_CELL, COST_ROUTING
from ..http.errors import MATRIX_ERROR_LABELS, MATRIX_ERRORS, MapyError
from ..lib.coords import to_api_coord
from ..lib.place import PlaceInput, resolve_all, resolve_place
from ..lib.shape import (
    Cost,
    MatrixCell,
    MatrixResult,
    RouteLeg,
    RouteResult,
    human_duration,
)

RouteType = Literal[
    "car_fast",
    "car_fast_traffic",
    "car_short",
    "foot_fast",
    "foot_hiking",
    "bike_road",
    "bike_mountain",
]

GeometryChoice = Literal["none", "polyline", "polyline6", "geojson"]

MAX_WAYPOINTS = 15
MAX_MATRIX_CELLS = 100


async def route(
    client: MapyClient,
    start: PlaceInput,
    end: PlaceInput,
    *,
    route_type: RouteType = "car_fast",
    via: list[PlaceInput] | None = None,
    avoid_toll: bool = False,
    avoid_highways: bool = False,
    departure: str | None = None,
    geometry: GeometryChoice = "none",
    lang: Lang | None = None,
) -> RouteResult:
    settings = get_settings()
    via = via or []
    if len(via) > MAX_WAYPOINTS:
        raise MapyError(
            f"API zvládne nejvýš {MAX_WAYPOINTS} průjezdních bodů, dostalo {len(via)}. "
            "Rozdělte trasu na víc úseků."
        )

    start_place = await resolve_place(client, start, lang=lang)
    end_place = await resolve_place(client, end, lang=lang)
    via_places, via_credits, via_warnings = await resolve_all(client, via, lang=lang)

    # Geometrie se stahuje vždy v polyline6 a do odpovědi jde jen na vyžádání —
    # GeoJSON stejné trasy je řádově větší a zaplní kontext.
    api_format = "geojson" if geometry == "geojson" else "polyline6"

    params: dict[str, object] = {
        "start": to_api_coord(start_place.coord),
        "end": to_api_coord(end_place.coord),
        "routeType": route_type,
        "lang": lang or settings.default_lang,
        "format": api_format,
    }
    if avoid_toll:
        params["avoidToll"] = "true"
    if avoid_highways:
        params["avoidHighways"] = "true"
    if departure:
        params["departure"] = departure
    if via_places:
        params["waypoints"] = ";".join(to_api_coord(p.coord) for p in via_places)

    payload = await client.get_json(
        "/v1/routing/route",
        params,
        group="routing",
        operation="route",
        credits=COST_ROUTING,
    )

    length = int(payload.get("length") or 0)
    duration = int(payload.get("duration") or 0)
    legs = [
        RouteLeg(length_m=int(p.get("length") or 0), duration_s=int(p.get("duration") or 0))
        for p in (payload.get("parts") or [])
        if isinstance(p, dict)
    ]

    warnings = list(via_warnings)
    for place in (start_place, end_place):
        if place.warning and place.warning not in warnings:
            warnings.append(place.warning)
    if departure and route_type != "car_fast_traffic":
        warnings.append(
            "Parametr departure ovlivní výsledek jen u routeType='car_fast_traffic'; "
            f"pro '{route_type}' se ignoruje."
        )

    credits = COST_ROUTING + start_place.credits + end_place.credits + via_credits
    return RouteResult(
        start=start_place.label,
        end=end_place.label,
        route_type=route_type,
        length_m=length,
        duration_s=duration,
        length_km=round(length / 1000, 1),
        duration_human=human_duration(duration),
        legs=legs,
        geometry=payload.get("geometry") if geometry != "none" else None,
        geometry_format=api_format if geometry != "none" else None,
        warnings=warnings,
        cost=Cost(credits=credits, session_total=round(client.ledger.spent, 1)),
    )


async def route_matrix(
    client: MapyClient,
    starts: list[PlaceInput],
    *,
    ends: list[PlaceInput] | None = None,
    route_type: RouteType = "car_fast",
    avoid_toll: bool = False,
    lang: Lang | None = None,
) -> MatrixResult:
    if not starts:
        raise MapyError("Zadejte aspoň jeden výchozí bod.")

    start_places, start_credits, warnings = await resolve_all(client, starts, lang=lang)
    if ends:
        end_places, end_credits, end_warnings = await resolve_all(client, ends, lang=lang)
        for w in end_warnings:
            if w not in warnings:
                warnings.append(w)
    else:
        # Bez `ends` počítá API plnou matici výchozích bodů proti sobě.
        end_places, end_credits = start_places, 0.0

    cells = len(start_places) * len(end_places)
    if cells > MAX_MATRIX_CELLS:
        raise MapyError(
            f"Matice {len(start_places)}×{len(end_places)} má {cells} buněk, "
            f"API zvládne nejvýš {MAX_MATRIX_CELLS}. Zmenšete zadání "
            f"(např. {MAX_MATRIX_CELLS // max(1, len(end_places))} výchozích bodů) "
            "nebo ho rozdělte na víc volání."
        )

    settings = get_settings()
    params: dict[str, object] = {
        "starts": ";".join(to_api_coord(p.coord) for p in start_places),
        "routeType": route_type,
        "lang": lang or settings.default_lang,
    }
    if ends:
        params["ends"] = ";".join(to_api_coord(p.coord) for p in end_places)
    if avoid_toll:
        params["avoidToll"] = "true"

    matrix_credits = round(cells * COST_MATRIX_CELL, 1)
    payload = await client.get_json(
        "/v1/routing/matrix-m",
        params,
        group="routing",
        operation="matrix",
        credits=matrix_credits,
    )

    rows = payload.get("matrix") if isinstance(payload, dict) else None
    out_cells: list[MatrixCell] = []
    unreachable = 0
    for i, row in enumerate(rows or []):
        for j, cell in enumerate(row or []):
            if not isinstance(cell, dict):
                continue
            length = cell.get("length")
            duration = cell.get("duration")
            # API sem místo délky posílá záporné kódy. Sečíst je jako vzdálenost
            # by dalo tiše špatný výsledek, proto se překládají na příznak.
            if isinstance(length, int) and length < 0:
                reason = MATRIX_ERRORS.get(length, "general_error")
                unreachable += 1
                out_cells.append(
                    MatrixCell(
                        from_index=i,
                        to_index=j,
                        unreachable=True,
                        reason=MATRIX_ERROR_LABELS.get(reason, reason),
                    )
                )
            else:
                out_cells.append(
                    MatrixCell(
                        from_index=i,
                        to_index=j,
                        length_m=int(length) if length is not None else None,
                        duration_s=int(duration) if duration is not None else None,
                    )
                )

    credits = matrix_credits + start_credits + end_credits
    return MatrixResult(
        starts=[p.label for p in start_places],
        ends=[p.label for p in end_places],
        route_type=route_type,
        cells=out_cells,
        unreachable_count=unreachable,
        warnings=warnings,
        cost=Cost(credits=credits, session_total=round(client.ledger.spent, 1)),
    )
