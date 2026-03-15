"""PDF parser for OMAE_ValidNOTAM files.

Extracts ICAO NOTAM fields using pdfplumber + regex and outputs a GeoJSON
FeatureCollection. All regex patterns are compiled once at import time.
"""

import json
import logging
import math
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pdfplumber

from notam import config

logger = logging.getLogger(__name__)

# OMAE FIR centroid — used as fallback when no Q-line geometry is present.
_OMAE_LAT: float = 25.2048
_OMAE_LON: float = 55.2708

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# NOTAM block boundary: e.g. "A0001/26 NOTAMN"
_RE_NOTAM_BOUNDARY = re.compile(r"(?m)^([A-Z]\d{4}/\d{2})\s+NOTAM[NRU]?")

# Q-line: Q)FIR/SUBJECT/CONDITION/TRAFFIC/PURPOSE/LOWER/UPPER/COORD+RADIUS
_RE_Q = re.compile(
    r"Q\)\s*([^/]+)/([^/]+)/([^/]+)/([^/]+)/([^/]+)/(\d{3})/(\d{3})/"
    r"(\d{4}[NS]\d{5}[EW]\d{3})"
)

# A-line (location ICAO codes)
_RE_A = re.compile(r"A\)\s*(.+?)(?=\s+[B-Z]\)|$)", re.DOTALL)

# B-line (start datetime, 10 digits: YYMMDDHHmm)
_RE_B = re.compile(r"B\)\s*(\d{10})")

# C-line (end datetime or PERM)
_RE_C = re.compile(r"C\)\s*(\d{10}|PERM)")

# E-line (free text, may span multiple lines)
_RE_E = re.compile(r"E\)\s*(.+?)(?=\s+[A-Z]\)|$)", re.DOTALL)

# Coordinate string: DDMM[NS]DDDMM[EW]RRR
_RE_COORD = re.compile(r"(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])(\d{3})")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _parse_datetime(s: str) -> str | None:
    """Convert a YYMMDDHHmm string to an ISO-8601 UTC string.

    Args:
        s: Ten-character datetime string in ICAO format (e.g. ``2603150600``).

    Returns:
        ISO-8601 string with UTC offset, or ``None`` if *s* is not valid.
    """
    try:
        dt = datetime.strptime(s, "%y%m%d%H%M").replace(tzinfo=UTC)
        return dt.isoformat()
    except ValueError:
        return None


def _parse_coord(coord_str: str) -> tuple[float, float, float]:
    """Parse a Q-line coordinate+radius field such as ``2518N05517E025``.

    Format: ``DDMM[N/S]DDDMM[E/W]RRR``

    Args:
        coord_str: Raw coordinate string from the Q-line.

    Returns:
        Tuple of ``(latitude_dd, longitude_dd, radius_nm)``.

    Raises:
        ValueError: If the string does not match the expected format.
    """
    m = _RE_COORD.fullmatch(coord_str)
    if not m:
        raise ValueError(f"Cannot parse coord string: {coord_str!r}")
    lat_d, lat_m, lat_hem, lon_d, lon_m, lon_hem, radius = m.groups()
    lat = int(lat_d) + int(lat_m) / 60.0
    if lat_hem == "S":
        lat = -lat
    lon = int(lon_d) + int(lon_m) / 60.0
    if lon_hem == "W":
        lon = -lon
    return lat, lon, float(radius)


def _circle_polygon(
    lat: float,
    lon: float,
    radius_nm: float,
    n: int = 36,
) -> list[list[float]]:
    """Approximate a circle as a closed GeoJSON polygon ring with *n* vertices.

    Args:
        lat: Centre latitude in decimal degrees.
        lon: Centre longitude in decimal degrees.
        radius_nm: Circle radius in nautical miles.
        n: Number of vertices (default 36 → one every 10°).

    Returns:
        A list of ``[lon, lat]`` pairs forming a closed ring (first == last).
    """
    radius_m = radius_nm * 1852.0
    coords: list[list[float]] = []
    for i in range(n + 1):
        angle = math.radians(i * 360.0 / n)
        d_lat = (radius_m * math.cos(angle)) / 111_320.0
        d_lon = (radius_m * math.sin(angle)) / (111_320.0 * math.cos(math.radians(lat)))
        coords.append([round(lon + d_lon, 6), round(lat + d_lat, 6)])
    return coords


def _geometry(lat: float, lon: float, radius_nm: float) -> dict[str, Any]:
    """Return a GeoJSON geometry dict.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        radius_nm: Radius in nautical miles.

    Returns:
        ``Polygon`` when *radius_nm* > 0, ``Point`` otherwise.
    """
    if radius_nm > 0:
        return {"type": "Polygon", "coordinates": [_circle_polygon(lat, lon, radius_nm)]}
    return {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------


def _extract_text(pdf_path: Path) -> str:
    """Extract full text from all pages of a PDF.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Concatenated text content of all pages.
    """
    with pdfplumber.open(pdf_path) as pdf:
        pages = [
            text
            for page in pdf.pages
            if (text := page.extract_text(x_tolerance=2, y_tolerance=2))
        ]
    return "\n".join(pages)


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """Split raw PDF text into ``(notam_id, block_text)`` tuples.

    Args:
        text: Full text extracted from the NOTAM PDF.

    Returns:
        List of ``(notam_id, block_text)`` pairs, one per NOTAM.
    """
    matches = list(_RE_NOTAM_BOUNDARY.finditer(text))
    if not matches:
        logger.warning("No NOTAM boundaries found in text")
        return []

    return [
        (m.group(1), text[m.start() : (matches[i + 1].start() if i + 1 < len(matches) else len(text))])
        for i, m in enumerate(matches)
    ]


def _parse_block(notam_id: str, block: str) -> dict[str, Any]:
    """Parse a single NOTAM block into geometry and properties.

    Args:
        notam_id: The NOTAM identifier (e.g. ``A0001/26``).
        block: Raw text of the NOTAM block.

    Returns:
        Dict with ``geometry`` (GeoJSON) and ``properties`` keys.
    """
    props: dict[str, Any] = {"notam_id": notam_id}
    lat, lon, radius = _OMAE_LAT, _OMAE_LON, 0.0
    geometry_fallback = True

    q = _RE_Q.search(block)
    if q:
        fir, subj, cond, traffic, purpose, lower, upper, coord = q.groups()
        props.update(
            fir=fir.strip(),
            subject_code=subj.strip(),
            condition=cond.strip(),
            traffic=traffic.strip(),
            purpose=purpose.strip(),
            lower_fl=int(lower),
            upper_fl=int(upper),
        )
        try:
            lat, lon, radius = _parse_coord(coord.strip())
            geometry_fallback = False
        except ValueError as exc:
            logger.warning("NOTAM %s: coord parse error: %s", notam_id, exc)
    else:
        logger.debug("NOTAM %s: no Q-line found", notam_id)

    if geometry_fallback:
        props["geometry_fallback"] = True

    if a := _RE_A.search(block):
        props["area_icao"] = " ".join(a.group(1).split())

    if b := _RE_B.search(block):
        props["start_datetime"] = _parse_datetime(b.group(1))

    if c := _RE_C.search(block):
        val = c.group(1)
        props["end_datetime"] = val if val == "PERM" else _parse_datetime(val)

    if e := _RE_E.search(block):
        props["free_text"] = " ".join(e.group(1).split())

    return {"geometry": _geometry(lat, lon, radius), "properties": props}


def parse_notam_pdf(pdf_path: Path) -> dict[str, Any]:
    """Parse an OMAE_ValidNOTAM PDF and return a GeoJSON FeatureCollection.

    Args:
        pdf_path: Path to the NOTAM PDF file.

    Returns:
        GeoJSON FeatureCollection dict with one Feature per NOTAM.
    """
    logger.info("Parsing PDF: %s", pdf_path)
    text = _extract_text(pdf_path)
    blocks = _split_blocks(text)
    logger.info("Found %d NOTAM blocks", len(blocks))

    features: list[dict[str, Any]] = []
    for notam_id, block in blocks:
        try:
            parsed = _parse_block(notam_id, block)
            features.append({
                "type": "Feature",
                "geometry": parsed["geometry"],
                "properties": parsed["properties"],
            })
        except (ValueError, KeyError) as exc:
            logger.error("Failed to parse NOTAM %s: %s", notam_id, exc)

    return {"type": "FeatureCollection", "features": features}


def save_geojson(
    feature_collection: dict[str, Any],
    for_date: date,
    output_dir: Path | None = None,
) -> Path:
    """Save a FeatureCollection to ``<output_dir>/YYYYMMDD_notam.geojson``.

    Args:
        feature_collection: GeoJSON FeatureCollection dict.
        for_date: Date used to build the output filename.
        output_dir: Override for the output directory (default: config.OUTPUT_DIR).

    Returns:
        Path to the written GeoJSON file.
    """
    d = output_dir or config.OUTPUT_DIR
    d.mkdir(exist_ok=True)
    out_path = d / f"{for_date:%Y%m%d}_notam.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(feature_collection, f, ensure_ascii=False, indent=2)
    logger.info(
        "Saved GeoJSON: %s (%d features)", out_path, len(feature_collection["features"])
    )
    return out_path


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python -m notam.parser <path-to-pdf>")
        sys.exit(1)
    pdf = Path(sys.argv[1])
    fc = parse_notam_pdf(pdf)
    out = save_geojson(fc, date.today())
    print(f"Saved: {out}  ({len(fc['features'])} features)")
