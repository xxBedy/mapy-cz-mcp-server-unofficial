"""Sestavení řetězcové syntaxe markerů a tvarů pro statickou mapu.

API bere markery jako středníkem oddělený výčet atributů, například
``color:red;size:large;label:AB;14.42,50.08``. Markery s **různým** nastavením
ale musí jít do samostatných opakovaných parametrů ``markers`` — jeden parametr
nese jeden styl a libovolný počet pozic. Builder proto body seskupí podle stylu.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .coords import Coord, to_api_coord

MarkerSize = Literal["small", "normal", "large"]


class Marker(BaseModel):
    """Bod vykreslený na statické mapě."""

    lat: float = Field(ge=-90, le=90, description="Zeměpisná šířka")
    lon: float = Field(ge=-180, le=180, description="Zeměpisná délka")
    label: str | None = Field(
        default=None,
        max_length=2,
        description="Až dva alfanumerické znaky uvnitř značky, například 'A' nebo '12'.",
    )
    color: str | None = Field(
        default=None,
        description="Název barvy (red, blue, green…) nebo hex #RGB / #RRGGBB / #RRGGBBAA.",
    )
    size: MarkerSize | None = None

    @property
    def coord(self) -> Coord:
        return Coord(lat=self.lat, lon=self.lon)

    def _style_key(self) -> tuple[str | None, str | None]:
        return (self.color, self.size)


class Shape(BaseModel):
    """Čára nebo mnohoúhelník na statické mapě."""

    kind: Literal["path", "polygon"] = "path"
    points: list[Coord] = Field(
        min_length=2,
        description="Body tvaru. Cesta potřebuje aspoň 2, mnohoúhelník aspoň 3 (uzavře se sám).",
    )
    color: str | None = Field(default=None, description="Barva čáry, resp. obrysu.")
    fill: str | None = Field(default=None, description="Výplň mnohoúhelníku.")
    width: int | None = Field(default=None, ge=1, le=20, description="Tloušťka čáry v pixelech.")


def build_markers(markers: list[Marker]) -> list[str]:
    """Vrátí hodnoty pro opakovaný parametr ``markers``, jednu na každý styl."""
    groups: dict[tuple[str | None, str | None], list[Marker]] = {}
    order: list[tuple[str | None, str | None]] = []
    for marker in markers:
        key = marker._style_key()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(marker)

    values: list[str] = []
    for key in order:
        color, size = key
        parts: list[str] = []
        if color:
            parts.append(f"color:{color}")
        if size:
            parts.append(f"size:{size}")
        for marker in groups[key]:
            if marker.label:
                parts.append(f"label:{marker.label}")
            parts.append(to_api_coord(marker.coord))
        values.append(";".join(parts))
    return values


def build_shapes(shapes: list[Shape]) -> list[str]:
    """Vrátí hodnoty pro opakovaný parametr ``shapes``, jednu na každý tvar."""
    values: list[str] = []
    for shape in shapes:
        parts: list[str] = []
        if shape.color:
            parts.append(f"color:{shape.color}")
        if shape.fill:
            parts.append(f"fill:{shape.fill}")
        if shape.width:
            parts.append(f"width:{shape.width}")
        coords = ";".join(to_api_coord(p) for p in shape.points)
        parts.append(f"{shape.kind}:[({coords})]")
        values.append(";".join(parts))
    return values
