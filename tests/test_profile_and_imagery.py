"""§4.2 kompozitní výškový profil a §5.2/5.3 obrázkové nástroje."""

from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.mcpserver import Image

from mapy_mcp.http.errors import MapyError
from mapy_mcp.lib.coords import Coord
from mapy_mcp.lib.polyline import decode
from mapy_mcp.lib.resample import resample
from mapy_mcp.tools.elevation import elevation_profile, elevation_profile_image
from mapy_mcp.tools.imagery import static_map


# Trasa se stoupáním a klesáním, zakódovaná stejně jako ji vrací API.
def _encode(points, precision=6):
    factor = 10**precision
    out, prev_lat, prev_lon = [], 0, 0
    for lat, lon in points:
        lat_i, lon_i = round(lat * factor), round(lon * factor)
        for delta in (lat_i - prev_lat, lon_i - prev_lon):
            v = ~(delta << 1) if delta < 0 else (delta << 1)
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lon = lat_i, lon_i
    return "".join(out)


def test_polyline_roundtrip():
    pts = [(50.0, 14.0), (50.5, 14.5), (51.0, 14.2)]
    decoded = decode(_encode(pts), 6)
    for (a, b), (c, d) in zip(pts, decoded, strict=True):
        assert abs(a - c) < 1e-5 and abs(b - d) < 1e-5


def test_resample_respects_api_limit():
    pts = [(50.0 + i / 1000, 14.0) for i in range(5000)]
    out = resample(pts, 256)
    assert len(out) == 256
    # Krajní body musí zůstat, jinak profil nezačíná na startu.
    assert abs(out[0].lat - 50.0) < 1e-6
    assert abs(out[-1].lat - pts[-1][0]) < 1e-6


@respx.mock
async def test_elevation_profile_computes_ascent_and_descent(client):
    track = [(50.0 + i / 1000, 14.0) for i in range(300)]
    respx.get("https://api.mapy.com/v1/routing/route").mock(
        return_value=httpx.Response(
            200, json={"length": 33000, "duration": 28800, "geometry": _encode(track)}
        )
    )
    # Profil: 300 → 500 → 400. Stoupání 200, klesání 100.
    elevations = [300.0, 500.0, 400.0]
    respx.get("https://api.mapy.com/v1/elevation").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"elevation": e, "position": {"lon": 14.0, "lat": 50.0}} for e in elevations
                ]
            },
        )
    )
    result = await elevation_profile(client, Coord(lat=50.0, lon=14.0), Coord(lat=50.3, lon=14.0))

    assert result.ascent_m == 200
    assert result.descent_m == 100
    assert result.min_m == 300.0 and result.max_m == 500.0
    assert result.sparkline
    # Výhrada o podhodnocení musí být v odpovědi, ne jen v dokumentaci.
    assert "vyšší" in result.accuracy_note


@respx.mock
async def test_static_map_autofits_to_markers(client):
    api = respx.get("https://api.mapy.com/v1/static/map").mock(
        return_value=httpx.Response(
            200, content=b"\x89PNG_fake", headers={"Content-Type": "image/png"}
        )
    )
    from mapy_mcp.lib.markers import Marker

    out = await static_map(
        client,
        markers=[Marker(lat=50.09, lon=14.42, label="A"), Marker(lat=49.19, lon=16.6, label="B")],
    )

    params = api.calls[0].request.url.params
    # Bez center/zoom si výřez dopočítá API — model nemusí počítat nic.
    assert "zoom" not in params
    assert params["markers"] == "label:A;14.42,50.09;label:B;16.6,49.19"
    assert isinstance(out[0], Image)


@respx.mock
async def test_static_map_url_output_costs_nothing(client):
    api = respx.get("https://api.mapy.com/v1/static/map")
    from mapy_mcp.lib.markers import Marker

    out = await static_map(client, markers=[Marker(lat=50.0, lon=14.0)], output="url")

    assert not api.called
    assert client.ledger.spent == 0.0
    assert "https://api.mapy.com/v1/static/map" in out[0]
    # Klíč se do sestaveného URL nesmí dostat.
    assert "test-key" not in out[0]


def _mock_profile(elevations):
    """Namockuje route (stoupavou trasu) i elevation s danými výškami."""
    track = [(50.0 + i / 1000, 14.0) for i in range(300)]
    respx.get("https://api.mapy.com/v1/routing/route").mock(
        return_value=httpx.Response(
            200, json={"length": 33000, "duration": 28800, "geometry": _encode(track)}
        )
    )
    respx.get("https://api.mapy.com/v1/elevation").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"elevation": e, "position": {"lon": 14.0, "lat": 50.0}} for e in elevations
                ]
            },
        )
    )


@respx.mock
async def test_elevation_profile_image_file_output(client, tmp_path, monkeypatch):
    # Obrázek ať padne do tmp_path, ať ho jde přečíst a ověřit obsah SVG.
    from pathlib import Path

    from mapy_mcp.config import reset_settings

    monkeypatch.setenv("MAPY_IMAGE_DIR", str(tmp_path))
    reset_settings()
    _mock_profile([300.0, 520.0, 410.0])

    try:
        out = await elevation_profile_image(
            client,
            Coord(lat=50.0, lon=14.0),
            Coord(lat=50.3, lon=14.0),
            output="file",
            width=900,
            height=280,
        )

        summary = out[0]
        assert "Uloženo:" in summary
        # Cena = routing (4) + 1× elevation (4), start i cíl jsou souřadnice → bez geokódování.
        assert "Cena: 8.0 kreditů" in summary
        assert "Mapy.com © Seznam.cz a.s. a další" in summary

        path = summary.split("Uloženo:", 1)[1].split("\n", 1)[0].strip()
        assert str(tmp_path) in path
        svg = Path(path).read_text(encoding="utf-8")
        assert "<svg" in svg
        assert "polyline" in svg and "polygon" in svg
        assert 'width="900"' in svg and 'height="280"' in svg
        # Vypálená atribuce a popisek nejvyššího bodu (520 m).
        assert "Mapy.com © Seznam.cz a.s. a další" in svg
        assert "520 m" in svg
    finally:
        reset_settings()


@respx.mock
async def test_elevation_profile_image_returns_image_content(client):
    _mock_profile([300.0, 500.0, 400.0])

    out = await elevation_profile_image(
        client, Coord(lat=50.0, lon=14.0), Coord(lat=50.3, lon=14.0), title="Trek"
    )

    assert isinstance(out[0], Image)
    assert out[0]._mime_type == "image/svg+xml"
    assert "Cena: 8.0 kreditů" in out[1]
    assert "Mapy.com © Seznam.cz a.s. a další" in out[1]


@respx.mock
async def test_elevation_profile_image_no_data_raises(client):
    # Samá výška „no data" (sentinel) → není z čeho profil vykreslit.
    _mock_profile([-100000.0, -100000.0, -100000.0])

    with pytest.raises(MapyError, match="výškových dat"):
        await elevation_profile_image(client, Coord(lat=50.0, lon=14.0), Coord(lat=50.3, lon=14.0))


@respx.mock
async def test_elevation_profile_image_empty_geometry_raises(client):
    respx.get("https://api.mapy.com/v1/routing/route").mock(
        return_value=httpx.Response(200, json={"length": 0, "duration": 0, "geometry": ""})
    )

    with pytest.raises(MapyError, match="geometrii"):
        await elevation_profile_image(client, Coord(lat=50.0, lon=14.0), Coord(lat=50.3, lon=14.0))
