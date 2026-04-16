"""Address normalization and geocoding.

Uses the US Census Geocoder for batch geocoding (free, no API key).
Normalizes addresses for clustering analysis.
"""

import csv
import io
import logging
import re

import httpx
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import Address

logger = logging.getLogger(__name__)

# Common abbreviation standardization
ABBREVIATIONS = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "DRIVE": "DR",
    "ROAD": "RD",
    "LANE": "LN",
    "COURT": "CT",
    "PLACE": "PL",
    "CIRCLE": "CIR",
    "HIGHWAY": "HWY",
    "FREEWAY": "FWY",
    "PARKWAY": "PKWY",
    "SUITE": "STE",
    "APARTMENT": "APT",
    "BUILDING": "BLDG",
    "FLOOR": "FL",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}


def normalize_address(address_1: str, address_2: str | None = None) -> str:
    """Normalize an address for consistent clustering.

    Strips suite/unit numbers, standardizes abbreviations, uppercases.
    The goal is to group providers at the same physical building.
    """
    addr = address_1.upper().strip()

    # Remove suite/unit/apt/room designators for building-level clustering
    # Keep this as separate logic — we want "9898 BISSONNET ST STE 200"
    # and "9898 BISSONNET ST STE 300" to cluster together.
    addr = re.sub(
        r"\s*(STE|SUITE|APT|APARTMENT|UNIT|RM|ROOM|#|FL|FLOOR|BLDG|BUILDING)\s*\.?\s*\S+\s*$",
        "",
        addr,
    )

    # Also strip address_2 content (usually suite info)
    # We don't append it — it's suite-level detail we want to ignore.

    # Standardize abbreviations
    words = addr.split()
    normalized_words = []
    for word in words:
        clean = word.rstrip(".,")
        normalized_words.append(ABBREVIATIONS.get(clean, clean))

    addr = " ".join(normalized_words)

    # Remove trailing periods and extra whitespace
    addr = re.sub(r"\s+", " ", addr).strip().rstrip(".")

    return addr


def batch_geocode(addresses: list[tuple[int, str, str, str, str]]) -> dict[int, tuple[float, float]]:
    """Geocode a batch of addresses using the Census Geocoder.

    Args:
        addresses: List of (id, street, city, state, zip) tuples.

    Returns:
        Dict mapping address ID to (lat, lng) tuples.
    """
    if not addresses:
        return {}

    # Census geocoder accepts CSV: unique_id, street, city, state, zip
    buf = io.StringIO()
    writer = csv.writer(buf)
    for addr_id, street, city, state, zip_code in addresses:
        writer.writerow([addr_id, street, city, state, zip_code])

    try:
        response = httpx.post(
            settings.census_geocoder_url,
            data={
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
            },
            files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
            timeout=120.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Census geocoder error: {e}")
        return {}

    results = {}
    reader = csv.reader(io.StringIO(response.text))
    for row in reader:
        if len(row) >= 6 and row[2] == "Match":
            try:
                addr_id = int(row[0])
                # Coordinates are in lon,lat format
                coords = row[5].split(",")
                lng = float(coords[0])
                lat = float(coords[1])
                results[addr_id] = (lat, lng)
            except (ValueError, IndexError):
                continue

    return results


def geocode_ungeocodeded(db: Session, batch_size: int = 1000) -> int:
    """Geocode all addresses that don't have coordinates yet."""
    ungeo = (
        db.query(Address)
        .filter(Address.lat.is_(None))
        .limit(batch_size)
        .all()
    )

    if not ungeo:
        logger.info("No addresses to geocode")
        return 0

    # Prepare batch
    batch = [
        (a.id, a.normalized_address, a.city, a.state, a.zip)
        for a in ungeo
    ]

    # Census geocoder handles max ~10k at a time; we batch at 1000
    results = batch_geocode(batch)

    count = 0
    for address in ungeo:
        if address.id in results:
            lat, lng = results[address.id]
            address.lat = lat
            address.lng = lng
            # Set PostGIS geometry
            address.geom = f"SRID=4326;POINT({lng} {lat})"
            count += 1

    db.commit()
    logger.info(f"Geocoded {count}/{len(ungeo)} addresses")
    return count
