"""Past 3.1 — pořadí souřadnic."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mapy_mcp.lib.coords import Coord, swap_warning, to_api_coord, to_api_coords


def test_api_order_is_lon_first():
    assert to_api_coord(Coord(lat=50.087, lon=14.421)) == "14.421,50.087"


def test_api_coords_joined_by_semicolon():
    coords = [Coord(lat=50.0, lon=14.0), Coord(lat=49.0, lon=16.0)]
    assert to_api_coords(coords) == "14.0,50.0;16.0,49.0"


def test_swapped_prague_is_flagged():
    warning = swap_warning(Coord(lat=14.42, lon=50.09))
    assert warning is not None
    assert "prohození" in warning


def test_correct_prague_is_not_flagged():
    assert swap_warning(Coord(lat=50.09, lon=14.42)) is None


def test_legitimate_foreign_point_is_not_flagged():
    # Reykjavík — mimo ČR/SR a po prohození taky, takže se nevaruje.
    assert swap_warning(Coord(lat=64.15, lon=-21.94)) is None


def test_out_of_range_latitude_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        Coord(lat=100.0, lon=14.0)
