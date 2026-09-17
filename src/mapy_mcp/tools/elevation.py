"""Nadmořská výška a výškový profil trasy."""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import Image

from ..config import Lang, get_settings
from ..http.client import MapyClient
from ..http.credits import COST_ELEVATION, COST_ROUTING
from ..http.errors import MapyError
from ..lib.coords import Coord, collect_warnings, to_api_coords
from ..lib.place import PlaceInput, resolve_place
from ..lib.polyline import decode_geometry
from ..lib.profile_svg import render_profile_svg
from ..lib.resample import MAX_POSITIONS_PER_CALL, chunk, cumulative_distances, resample
from ..lib.shape import (
    ATTRIBUTION,
    Cost,
    ElevationPoint,
    ElevationProfileImageResult,
    ElevationProfileResult,
    ElevationResult,
    human_duration,
    sparkline,
)

# API vrací tuhle hodnotu místo null, když pro bod nemá data.
NO_DATA_SENTINEL = -100000.0
NO_DATA_THRESHOLD = -99000.0

Accuracy = Literal["fast", "detailed"]
ImageOutput = Literal["image", "file"]


def _clean_elevation(value: object) -> float | None:
    """Sentinel -100000.0 není výška. Kdyby prošel, profil by hlásil pokles o 100 km."""
    if not isinstance(value, (int, float)):
        return None
    if float(value) <= NO_DATA_THRESHOLD:
        return None
    return float(value)


async def _fetch_elevations(
    client: MapyClient, coords: list[Coord], *, lang: str
) -> list[float | None]:
    values: list[float | None] = []
    for batch in chunk(coords, MAX_POSITIONS_PER_CALL):
        payload = await client.get_json(
            "/v1/elevation",
            {"positions": to_api_coords(batch), "lang": lang},
            group="elevation",
            operation="elevation",
            credits=COST_ELEVATION,
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        for item in items or []:
            raw = item.get("elevation") if isinstance(item, dict) else None
            values.append(_clean_elevation(raw))
    return values


async def elevation(
    client: MapyClient,
    points: list[Coord],
    *,
    lang: Lang | None = None,
) -> ElevationResult:
    if not points:
        raise MapyError("Zadejte aspoň jeden bod.")
    if len(points) > MAX_POSITIONS_PER_CALL:
        raise MapyError(
            f"Jedno volání zvládne {MAX_POSITIONS_PER_CALL} bodů, dostalo {len(points)}. "
            "Pro profil trasy použijte mapy_elevation_profile, který si vzorkování řeší sám."
        )

    settings = get_settings()
    values = await _fetch_elevations(client, points, lang=lang or settings.default_lang)

    shaped = [
        ElevationPoint(lat=c.lat, lon=c.lon, elevation_m=v)
        for c, v in zip(points, values, strict=False)
    ]
    known = [v for v in values if v is not None]

    return ElevationResult(
        points=shaped,
        min_m=min(known) if known else None,
        max_m=max(known) if known else None,
        data_gaps=sum(1 for v in values if v is None),
        warnings=collect_warnings(points),
        cost=Cost(credits=COST_ELEVATION, session_total=round(client.ledger.spent, 1)),
    )


@dataclass
class _ProfileData:
    """Společný výstup pipeline route → resample → výšky, než se z něj cokoli vykreslí."""

    start_label: str
    end_label: str
    route_type: str
    length_m: int
    duration_s: int
    n_points: int  # délka celé geometrie — pro poznámku o přesnosti
    accuracy: Accuracy
    samples: list[Coord]
    values: list[float | None]
    ascent_m: float | None
    descent_m: float | None
    min_m: float | None
    max_m: float | None
    data_gaps: int
    calls: int
    credits: float
    warnings: list[str]


async def _gather_profile(
    client: MapyClient,
    start: PlaceInput,
    end: PlaceInput,
    *,
    route_type: str,
    accuracy: Accuracy,
    lang: Lang | None,
) -> _ProfileData:
    """Naplánuje trasu, navzorkuje ji a změří výšky. Sdílí ``elevation_profile`` i obrázek."""
    settings = get_settings()
    language = lang or settings.default_lang

    start_place = await resolve_place(client, start, lang=lang)
    end_place = await resolve_place(client, end, lang=lang)

    payload = await client.get_json(
        "/v1/routing/route",
        {
            "start": f"{start_place.coord.lon},{start_place.coord.lat}",
            "end": f"{end_place.coord.lon},{end_place.coord.lat}",
            "routeType": route_type,
            "lang": language,
            "format": "polyline6",
        },
        group="routing",
        operation="route",
        credits=COST_ROUTING,
    )

    length = int(payload.get("length") or 0)
    duration = int(payload.get("duration") or 0)
    points = decode_geometry(payload.get("geometry"), "polyline6")
    if not points:
        raise MapyError("Trasa se naplánovala, ale nevrátila geometrii — profil nelze spočítat.")

    # 'fast' vystačí s jedním voláním, 'detailed' vzorkuje hustěji za cenu dalších volání.
    if accuracy == "detailed":
        target = min(len(points), MAX_POSITIONS_PER_CALL * 4)
    else:
        target = min(len(points), MAX_POSITIONS_PER_CALL)

    samples = resample(points, target)
    values = await _fetch_elevations(client, samples, lang=language)
    known = [v for v in values if v is not None]

    ascent = descent = None
    if len(known) >= 2:
        ascent = descent = 0.0
        previous: float | None = None
        for value in values:
            if value is None:
                continue
            if previous is not None:
                delta = value - previous
                if delta > 0:
                    ascent += delta
                else:
                    descent -= delta
            previous = value

    calls = len(chunk(samples, MAX_POSITIONS_PER_CALL))
    credits = COST_ROUTING + calls * COST_ELEVATION + start_place.credits + end_place.credits
    warnings = [w for w in (start_place.warning, end_place.warning) if w]

    return _ProfileData(
        start_label=start_place.label,
        end_label=end_place.label,
        route_type=route_type,
        length_m=length,
        duration_s=duration,
        n_points=len(points),
        accuracy=accuracy,
        samples=samples,
        values=values,
        ascent_m=ascent,
        descent_m=descent,
        min_m=min(known) if known else None,
        max_m=max(known) if known else None,
        data_gaps=sum(1 for v in values if v is None),
        calls=calls,
        credits=credits,
        warnings=warnings,
    )


def _save_svg(svg: str) -> Path:
    """Uloží SVG na disk stejným vzorem jako statická mapa (settings.image_dir / temp)."""
    settings = get_settings()
    directory = settings.image_dir or Path(tempfile.gettempdir()) / "mapy-mcp"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"mapy-profil-{uuid.uuid4().hex[:12]}.svg"
    path.write_text(svg, encoding="utf-8")
    return path


async def elevation_profile(
    client: MapyClient,
    start: PlaceInput,
    end: PlaceInput,
    *,
    route_type: str = "foot_hiking",
    accuracy: Accuracy = "fast",
    lang: Lang | None = None,
) -> ElevationProfileResult:
    data = await _gather_profile(
        client, start, end, route_type=route_type, accuracy=accuracy, lang=lang
    )
    known = [v for v in data.values if v is not None]

    note = (
        f"Převýšení je součet rozdílů mezi {len(known)} vzorky "
        f"na {round(data.length_m / 1000, 1)} km. "
        "Vzorkování zahladí lokální vlny, takže skutečné převýšení je spíš vyšší."
    )
    if data.accuracy == "fast" and data.n_points > MAX_POSITIONS_PER_CALL:
        note += " Pro přesnější odhad použijte accuracy='detailed' (víc volání, víc kreditů)."

    return ElevationProfileResult(
        start=data.start_label,
        end=data.end_label,
        route_type=data.route_type,
        length_m=data.length_m,
        duration_s=data.duration_s,
        length_km=round(data.length_m / 1000, 1),
        duration_human=human_duration(data.duration_s),
        samples=len(data.samples),
        min_m=data.min_m,
        max_m=data.max_m,
        ascent_m=int(round(data.ascent_m)) if data.ascent_m is not None else None,
        descent_m=int(round(data.descent_m)) if data.descent_m is not None else None,
        sparkline=sparkline(known) if known else None,
        data_gaps=data.data_gaps,
        accuracy_note=note,
        warnings=data.warnings,
        cost=Cost(credits=data.credits, session_total=round(client.ledger.spent, 1)),
    )


async def elevation_profile_image(
    client: MapyClient,
    start: PlaceInput,
    end: PlaceInput,
    *,
    route_type: str = "foot_hiking",
    accuracy: Accuracy = "fast",
    output: ImageOutput = "image",
    width: int = 1000,
    height: int = 300,
    title: str | None = None,
    lang: Lang | None = None,
) -> list[Image | str]:
    """Vykreslí výškový profil trasy jako SVG obrázek s vypálenou atribucí."""
    data = await _gather_profile(
        client, start, end, route_type=route_type, accuracy=accuracy, lang=lang
    )

    # Vzdálenost po trase z navzorkovaných souřadnic; párujeme jen body s výškou.
    coords = [(c.lat, c.lon) for c in data.samples]
    cumulative = cumulative_distances(coords)
    pairs = [(cumulative[i] / 1000, v) for i, v in enumerate(data.values) if v is not None]
    if len(pairs) < 2:
        raise MapyError(
            "Trasa nemá dost výškových dat (většina vzorků je bez měření) — profil nelze vykreslit."
        )
    distances_km = [d for d, _ in pairs]
    elevations = [e for _, e in pairs]

    svg = render_profile_svg(distances_km, elevations, width=width, height=height, title=title)

    result = ElevationProfileImageResult(
        start=data.start_label,
        end=data.end_label,
        route_type=data.route_type,
        width=width,
        height=height,
        length_m=data.length_m,
        length_km=round(data.length_m / 1000, 1),
        samples=len(data.samples),
        min_m=data.min_m,
        max_m=data.max_m,
        ascent_m=int(round(data.ascent_m)) if data.ascent_m is not None else None,
        descent_m=int(round(data.descent_m)) if data.descent_m is not None else None,
        data_gaps=data.data_gaps,
        warnings=data.warnings,
        cost=Cost(credits=data.credits, session_total=round(client.ledger.spent, 1)),
    )

    summary = (
        f"Výškový profil {width}×{height}: {result.start} → {result.end}, "
        f"{result.length_km} km, ↑{result.ascent_m} ↓{result.descent_m} m, "
        f"min {result.min_m} / max {result.max_m} m n.m."
    )
    if data.warnings:
        summary += "\nUpozornění: " + " ".join(data.warnings)
    summary += f"\nCena: {result.cost.credits} kreditů (session celkem {client.ledger.spent:.1f})."

    if output == "file":
        path = _save_svg(svg)
        result.path = str(path)
        return [f"{summary}\nUloženo: {path}\n{ATTRIBUTION}"]

    kb = round(len(svg.encode("utf-8")) / 1024)
    return [
        Image(data=svg.encode("utf-8"), format="svg+xml"),
        f"{summary}\nVelikost v kontextu: ~{kb} kB SVG.\n{ATTRIBUTION}",
    ]
