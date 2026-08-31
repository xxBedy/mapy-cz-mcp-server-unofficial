"""Statická mapa a panorama — jediné nástroje, jejichž výstup model doopravdy vidí.

Defaulty jsou schválně nižší než maxima API. Obrázek jde do kontextu jako base64,
takže 1024x1024 @2x v PNG by spolykalo řádově víc tokenů než celý zbytek odpovědi.
640x480 v JPEG je čitelné a levné; kdo chce víc, řekne si o to.
"""

from __future__ import annotations

import base64
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import Image

from ..config import Lang, get_settings
from ..http.client import MapyClient
from ..http.credits import COST_STATIC
from ..http.errors import MapyError
from ..lib.coords import Coord, collect_warnings
from ..lib.markers import Marker, Shape, build_markers, build_shapes
from ..lib.shape import ATTRIBUTION

MapSet = Literal["basic", "outdoor", "aerial", "aerial-names-overlay", "winter"]
ImageFormat = Literal["png", "jpg", "webp", "gif"]
Output = Literal["image", "file", "url"]

MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _save(data: bytes, mime: str) -> Path:
    settings = get_settings()
    directory = settings.image_dir or Path(tempfile.gettempdir()) / "mapy-mcp"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = MIME_EXTENSIONS.get(mime, "png")
    path = directory / f"mapy-{uuid.uuid4().hex[:12]}.{suffix}"
    path.write_bytes(data)
    return path


def _deliver(
    data: bytes, mime: str, output: Output, summary: str, url: str | None
) -> list[Image | str]:
    if output == "file":
        path = _save(data, mime)
        return [f"{summary}\nUloženo: {path}\n{ATTRIBUTION}"]
    if output == "url":
        return [f"{summary}\nURL: {url}\n{ATTRIBUTION}"]
    fmt = MIME_EXTENSIONS.get(mime, "png")
    kb = round(len(base64.b64encode(data)) / 1024)
    return [
        Image(data=data, format="jpeg" if fmt == "jpg" else fmt),
        f"{summary}\nVelikost v kontextu: ~{kb} kB base64.\n{ATTRIBUTION}",
    ]


async def static_map(
    client: MapyClient,
    *,
    center: Coord | None = None,
    zoom: int | None = None,
    bbox: list[Coord] | None = None,
    markers: list[Marker] | None = None,
    shapes: list[Shape] | None = None,
    width: int = 640,
    height: int = 480,
    mapset: MapSet = "basic",
    scale: int = 1,
    image_format: ImageFormat = "jpg",
    padding: int | None = None,
    output: Output = "image",
    lang: Lang | None = None,
) -> list[Image | str]:
    settings = get_settings()
    markers = markers or []
    shapes = shapes or []

    if center is None and not bbox and not markers:
        raise MapyError(
            "Zadejte střed mapy (center + zoom), výřez (bbox), nebo aspoň jeden marker — "
            "podle markerů si API výřez dopočítá samo."
        )
    if center is not None and zoom is None:
        raise MapyError("Se středem mapy je potřeba i zoom (1–19).")
    if bbox is not None and len(bbox) != 2:
        raise MapyError("bbox musí mít přesně dva rohy.")

    params: dict[str, object] = {
        "width": width,
        "height": height,
        "mapset": mapset,
        "scale": scale,
        "format": image_format,
        "lang": lang or settings.default_lang,
    }
    if padding is not None:
        params["padding"] = padding
    if center is not None:
        params["lon"] = center.lon
        params["lat"] = center.lat
        params["zoom"] = zoom
    elif bbox:
        params["lon"] = [c.lon for c in bbox]
        params["lat"] = [c.lat for c in bbox]
        if zoom is not None:
            params["zoom"] = zoom
    elif zoom is not None:
        params["zoom"] = zoom

    if markers:
        params["markers"] = build_markers(markers)
    if shapes:
        params["shapes"] = build_shapes(shapes)

    url = client.build_url("/v1/static/map", params) if output == "url" else None
    if output == "url":
        # URL se jen sestaví, API se nevolá — nula kreditů, nula tokenů.
        return [f"Mapa {width}×{height}, sada {mapset}.\nURL: {url}\n{ATTRIBUTION}"]

    data, mime = await client.get_bytes(
        "/v1/static/map", params, group="static", operation="static_map", credits=COST_STATIC
    )

    checked = [c for c in ([center] if center else []) + (bbox or [])]
    checked += [m.coord for m in markers]
    warnings = collect_warnings(checked)

    summary = f"Mapa {width}×{height}, sada {mapset}, {len(markers)} markerů."
    if warnings:
        summary += "\nUpozornění: " + " ".join(warnings)
    summary += f"\nCena: {COST_STATIC} kreditů (session celkem {client.ledger.spent:.1f})."
    return _deliver(data, mime, output, summary, url)


async def panorama(
    client: MapyClient,
    *,
    place: Coord,
    width: int = 640,
    height: int = 360,
    radius_m: float = 50.0,
    yaw: str = "point",
    pitch: float | None = None,
    fov: float | None = None,
    output: Output = "image",
    lang: Lang | None = None,
) -> list[Image | str]:
    settings = get_settings()
    params: dict[str, object] = {
        "width": width,
        "height": height,
        "lon": place.lon,
        "lat": place.lat,
        "radius": radius_m,
        "yaw": yaw,
        "lang": lang or settings.default_lang,
    }
    if pitch is not None:
        params["pitch"] = pitch
    if fov is not None:
        params["fov"] = fov

    url = client.build_url("/v1/static/pano", params) if output == "url" else None
    if output == "url":
        return [f"Panorama {width}×{height} u {place}.\nURL: {url}\n{ATTRIBUTION}"]

    data, mime = await client.get_bytes(
        "/v1/static/pano", params, group="static", operation="panorama", credits=COST_STATIC
    )

    summary = f"Panorama {width}×{height} v okolí {place} (do {radius_m:.0f} m)."
    warning = collect_warnings([place])
    if warning:
        summary += "\nUpozornění: " + " ".join(warning)
    summary += f"\nCena: {COST_STATIC} kreditů (session celkem {client.ledger.spent:.1f})."
    return _deliver(data, mime, output, summary, url)
