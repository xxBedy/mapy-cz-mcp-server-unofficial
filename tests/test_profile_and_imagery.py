"""§4.2 kompozitní výškový profil a §5.2/5.3 obrázkové nástroje."""

from __future__ import annotations

import httpx
import respx
from mcp.server.mcpserver import Image

from mapy_mcp.lib.coords import Coord
from mapy_mcp.lib.polyline import decode
from mapy_mcp.lib.resample import resample
from mapy_mcp.tools.elevation import elevation_profile
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
            json={"items": [{"elevation": e, "position": {"lon": 14.0, "lat": 50.0}}
                            for e in elevations]},
        )
    )
    result = await elevation_profile(
        client, Coord(lat=50.0, lon=14.0), Coord(lat=50.3, lon=14.0)
    )

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
