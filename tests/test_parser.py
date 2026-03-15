"""Tests for notam.parser — pure functions only, no mocks, no network."""

import json
from datetime import date

import pytest

from notam.parser import (
    _circle_polygon,
    _geometry,
    _parse_block,
    _parse_coord,
    _parse_datetime,
    _split_blocks,
    parse_notam_pdf,
    save_geojson,
)

# ---------------------------------------------------------------------------
# Minimal NOTAM text used throughout these tests
# ---------------------------------------------------------------------------

_NOTAM_FULL = """\
A0001/26 NOTAMN
Q) OMAE/QRTCA/IV/NBO/AE/000/045/2518N05517E025
A) OMAE
B) 2603150600
C) 2603200000
E) RESTRICTED AREA ACTIVATED. RADIUS 25NM CENTRED ON 2518N 05517E.
"""

_NOTAM_PERM = """\
A0002/26 NOTAMN
Q) OMAE/QOBCE/IV/BO/AE/000/999/2518N05517E000
A) OMDB
B) 2601010000
C) PERM
E) OBSTACLE ERECTED.
"""

_NOTAM_NO_Q = """\
A0003/26 NOTAMN
A) OMDB
B) 2603150600
C) 2603200000
E) FREE TEXT ONLY.
"""

_TWO_NOTAMS = _NOTAM_FULL + "\n" + _NOTAM_PERM


# ---------------------------------------------------------------------------
# _parse_coord
# ---------------------------------------------------------------------------


def test_parse_coord_basic():
    lat, lon, r = _parse_coord("2518N05517E025")
    assert abs(lat - (25 + 18 / 60)) < 1e-9
    assert abs(lon - (55 + 17 / 60)) < 1e-9
    assert r == 25.0


def test_parse_coord_zero_radius():
    lat, lon, r = _parse_coord("2518N05517E000")
    assert r == 0.0


def test_parse_coord_south_west():
    lat, lon, r = _parse_coord("1030S04500W010")
    assert lat < 0
    assert lon < 0


def test_parse_coord_invalid():
    with pytest.raises(ValueError, match="Cannot parse coord string"):
        _parse_coord("BADVALUE")


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------


def test_parse_datetime_valid():
    result = _parse_datetime("2603150600")
    assert result == "2026-03-15T06:00:00+00:00"


def test_parse_datetime_invalid():
    assert _parse_datetime("NOTADATE") is None


def test_parse_datetime_invalid_month():
    assert _parse_datetime("2699990000") is None


# ---------------------------------------------------------------------------
# _circle_polygon
# ---------------------------------------------------------------------------


def test_circle_polygon_is_closed():
    ring = _circle_polygon(25.3, 55.28, 25.0)
    assert ring[0] == ring[-1], "GeoJSON polygon ring must be closed"


def test_circle_polygon_vertex_count():
    ring = _circle_polygon(25.3, 55.28, 25.0, n=36)
    assert len(ring) == 37  # n vertices + closing duplicate


def test_circle_polygon_approx_radius():
    """First vertex should be ~radius_nm nautical miles north of centre."""
    lat, lon, r_nm = 25.3, 55.28, 10.0
    ring = _circle_polygon(lat, lon, r_nm, n=36)
    # At i=0, angle=0 → purely northward offset
    north_vertex_lat = ring[0][1]
    expected_lat = lat + (r_nm * 1852.0) / 111_320.0
    assert abs(north_vertex_lat - expected_lat) < 1e-4


# ---------------------------------------------------------------------------
# _geometry
# ---------------------------------------------------------------------------


def test_geometry_point_when_zero_radius():
    g = _geometry(25.3, 55.28, 0.0)
    assert g["type"] == "Point"
    assert g["coordinates"] == [55.28, 25.3]


def test_geometry_polygon_when_nonzero_radius():
    g = _geometry(25.3, 55.28, 10.0)
    assert g["type"] == "Polygon"
    assert len(g["coordinates"]) == 1  # single ring


# ---------------------------------------------------------------------------
# _split_blocks
# ---------------------------------------------------------------------------


def test_split_blocks_empty_text():
    assert _split_blocks("") == []


def test_split_blocks_no_boundary():
    assert _split_blocks("some random text without NOTAM headers") == []


def test_split_blocks_single():
    blocks = _split_blocks(_NOTAM_FULL)
    assert len(blocks) == 1
    assert blocks[0][0] == "A0001/26"


def test_split_blocks_multiple():
    blocks = _split_blocks(_TWO_NOTAMS)
    assert len(blocks) == 2
    ids = [b[0] for b in blocks]
    assert "A0001/26" in ids
    assert "A0002/26" in ids


# ---------------------------------------------------------------------------
# _parse_block
# ---------------------------------------------------------------------------


def test_parse_block_full_fields():
    parsed = _parse_block("A0001/26", _NOTAM_FULL)
    props = parsed["properties"]

    assert props["notam_id"] == "A0001/26"
    assert props["fir"] == "OMAE"
    assert props["subject_code"] == "QRTCA"
    assert props["lower_fl"] == 0
    assert props["upper_fl"] == 45
    assert props["area_icao"] == "OMAE"
    assert props["start_datetime"] == "2026-03-15T06:00:00+00:00"
    assert props["end_datetime"] == "2026-03-20T00:00:00+00:00"
    assert "RESTRICTED AREA" in props["free_text"]
    assert "geometry_fallback" not in props


def test_parse_block_perm_end_date():
    parsed = _parse_block("A0002/26", _NOTAM_PERM)
    assert parsed["properties"]["end_datetime"] == "PERM"


def test_parse_block_no_qline_uses_fallback_geometry():
    parsed = _parse_block("A0003/26", _NOTAM_NO_Q)
    props = parsed["properties"]
    assert props.get("geometry_fallback") is True
    # Fallback geometry must be a Point at the OMAE FIR centroid
    geom = parsed["geometry"]
    assert geom["type"] == "Point"
    lon, lat = geom["coordinates"]
    assert abs(lat - 25.2048) < 1e-4
    assert abs(lon - 55.2708) < 1e-4


def test_parse_block_polygon_geometry():
    parsed = _parse_block("A0001/26", _NOTAM_FULL)
    assert parsed["geometry"]["type"] == "Polygon"


# ---------------------------------------------------------------------------
# save_geojson
# ---------------------------------------------------------------------------


def test_save_geojson_creates_file(tmp_path):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [55.28, 25.3]},
                "properties": {"notam_id": "A0001/26"},
            }
        ],
    }
    out = save_geojson(fc, date(2026, 3, 15), output_dir=tmp_path)
    assert out.exists()
    assert out.name == "20260315_notam.geojson"


def test_save_geojson_valid_json(tmp_path):
    fc = {"type": "FeatureCollection", "features": []}
    out = save_geojson(fc, date(2026, 3, 15), output_dir=tmp_path)
    loaded = json.loads(out.read_text())
    assert loaded["type"] == "FeatureCollection"


# ---------------------------------------------------------------------------
# parse_notam_pdf — integration test against a real minimal PDF
# ---------------------------------------------------------------------------


def test_parse_notam_pdf_real_pdf(tmp_path):
    """Build a minimal PDF with two NOTAMs and verify the FeatureCollection."""
    pytest.importorskip(
        "reportlab", reason="reportlab not installed; skipping PDF integration test"
    )
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "test.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    # Write NOTAM text line by line
    y = 800
    for line in (_NOTAM_FULL + "\n" + _NOTAM_PERM).splitlines():
        c.drawString(40, y, line)
        y -= 14
        if y < 40:
            c.showPage()
            y = 800
    c.save()

    fc = parse_notam_pdf(pdf_path)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    ids = {f["properties"]["notam_id"] for f in fc["features"]}
    assert ids == {"A0001/26", "A0002/26"}
