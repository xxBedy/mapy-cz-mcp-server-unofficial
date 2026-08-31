"""Návratové modely a tvarování odpovědí.

Syrové odpovědi API jsou pro kontextové okno příliš velké — geometrie trasy
Praha–Brno má v GeoJSONu přes sto kilobajtů. Pravidlo je proto: default je souhrn,
detail na vyžádání přes ``raw=True``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

ATTRIBUTION = "Mapy.com © Seznam.cz a.s. a další — https://api.mapy.com/copyright"

SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


class Cost(BaseModel):
    """Odhad ceny volání v kreditech."""

    credits: float = Field(description="Odhad kreditů spotřebovaných tímto voláním.")
    session_total: float = Field(description="Kredity spotřebované v této session celkem.")


class Place(BaseModel):
    """Nalezené místo."""

    name: str
    label: str | None = Field(default=None, description="Typ místa slovy, např. 'Ulice'.")
    lat: float
    lon: float
    type: str | None = None
    location: str | None = Field(default=None, description="Kde to je, krátce.")
    region: str | None = Field(default=None, description="Nadřazené celky od nejmenšího.")
    zip: str | None = None


class GeocodeResult(BaseModel):
    query: str
    places: list[Place]
    warnings: list[str] = Field(default_factory=list)
    attribution: str = ATTRIBUTION
    cost: Cost


class ReverseGeocodeResult(BaseModel):
    lat: float
    lon: float
    places: list[Place]
    warnings: list[str] = Field(default_factory=list)
    attribution: str = ATTRIBUTION
    cost: Cost


class RouteLeg(BaseModel):
    length_m: int
    duration_s: int


class RouteResult(BaseModel):
    start: str = Field(description="Výchozí bod, jak byl rozpoznán.")
    end: str = Field(description="Cílový bod, jak byl rozpoznán.")
    route_type: str
    length_m: int
    duration_s: int
    length_km: float
    duration_human: str
    legs: list[RouteLeg] = Field(default_factory=list)
    geometry: str | dict[str, Any] | None = Field(
        default=None,
        description="Geometrie trasy, jen pokud byla vyžádána parametrem geometry.",
    )
    geometry_format: str | None = None
    warnings: list[str] = Field(default_factory=list)
    attribution: str = ATTRIBUTION
    cost: Cost


class MatrixCell(BaseModel):
    from_index: int
    to_index: int
    length_m: int | None = None
    duration_s: int | None = None
    unreachable: bool = False
    reason: str | None = Field(
        default=None,
        description="Proč je buňka nedostupná — API sem posílá záporné kódy místo délek.",
    )


class MatrixResult(BaseModel):
    starts: list[str]
    ends: list[str]
    route_type: str
    cells: list[MatrixCell]
    unreachable_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    attribution: str = ATTRIBUTION
    cost: Cost


class ElevationPoint(BaseModel):
    lat: float
    lon: float
    elevation_m: float | None = Field(
        default=None, description="Nadmořská výška v metrech, null pokud data chybí."
    )


class ElevationResult(BaseModel):
    points: list[ElevationPoint]
    min_m: float | None = None
    max_m: float | None = None
    data_gaps: int = Field(default=0, description="Kolik bodů nemá výšková data.")
    warnings: list[str] = Field(default_factory=list)
    attribution: str = ATTRIBUTION
    cost: Cost


class ElevationProfileResult(BaseModel):
    start: str
    end: str
    route_type: str
    length_m: int
    duration_s: int
    length_km: float
    duration_human: str
    samples: int = Field(description="Kolik bodů trasy bylo změřeno.")
    min_m: float | None = None
    max_m: float | None = None
    ascent_m: int | None = Field(default=None, description="Součet stoupání ze vzorků.")
    descent_m: int | None = Field(default=None, description="Součet klesání ze vzorků.")
    sparkline: str | None = Field(default=None, description="Hrubý tvar profilu.")
    data_gaps: int = 0
    accuracy_note: str
    warnings: list[str] = Field(default_factory=list)
    attribution: str = ATTRIBUTION
    cost: Cost


class TimezoneResult(BaseModel):
    timezone: str
    local_time: str
    utc_time: str
    utc_offset_s: int
    abbreviation: str
    standard_abbreviation: str | None = None
    has_dst: bool = False
    dst_active: bool = False
    warnings: list[str] = Field(default_factory=list)
    attribution: str = ATTRIBUTION
    cost: Cost


def human_duration(seconds: int) -> str:
    """Trvání v podobě, kterou jde rovnou přečíst uživateli."""
    if seconds < 60:
        return f"{seconds} s"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min" if not sec else f"{minutes} min {sec} s"


def flatten_region(structure: object) -> str | None:
    """Z regionální struktury udělá jednu čitelnou řádku místo pole objektů."""
    if not isinstance(structure, list):
        return None
    names = [
        item["name"]
        for item in structure
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    return ", ".join(names) if names else None


def shape_place(item: dict[str, Any]) -> Place:
    """Ořeže položku geokódování na to, co má cenu posílat modelu (bbox ven)."""
    position = item.get("position") or {}
    return Place(
        name=item.get("name") or "",
        label=item.get("label"),
        lat=float(position.get("lat", 0.0)),
        lon=float(position.get("lon", 0.0)),
        type=item.get("type"),
        location=item.get("location"),
        region=flatten_region(item.get("regionalStructure")),
        zip=item.get("zip"),
    )


SPARKLINE_MAX_WIDTH = 64


def sparkline(values: list[float], width: int = SPARKLINE_MAX_WIDTH) -> str:
    """Osmiúrovňový profil, aby šel tvar trasy přečíst bez posílání stovek čísel.

    Vzorků bývá až 256, ale tvar je čitelný i z šedesáti znaků — a zbylých 200
    by byl jen šum v kontextu. Přebytek se proto slučuje průměrem.
    """
    if not values:
        return ""
    if len(values) > width:
        bucket = len(values) / width
        values = [
            sum(values[int(i * bucket) : max(int(i * bucket) + 1, int((i + 1) * bucket))])
            / max(1, max(int(i * bucket) + 1, int((i + 1) * bucket)) - int(i * bucket))
            for i in range(width)
        ]
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return SPARKLINE_CHARS[0] * len(values)
    span = hi - lo
    out = []
    for v in values:
        idx = int((v - lo) / span * (len(SPARKLINE_CHARS) - 1))
        out.append(SPARKLINE_CHARS[idx])
    return "".join(out)
