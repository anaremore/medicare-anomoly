"""OIG LEIE Exclusion Database ingestion.

Downloads the UPDATED.csv from OIG and upserts into the exclusions table.
"""

import csv
import io
import logging
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import Exclusion

logger = logging.getLogger(__name__)


def parse_date(s: str | None) -> datetime | None:
    if not s or s.strip() == "":
        return None
    for fmt in ("%Y%m%d", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def download_leie() -> str:
    """Download the LEIE CSV file and return its content."""
    logger.info(f"Downloading LEIE from {settings.leie_csv_url}")
    response = httpx.get(settings.leie_csv_url, timeout=120.0, follow_redirects=True)
    response.raise_for_status()
    return response.text


def parse_leie_csv(content: str) -> list[dict]:
    """Parse the LEIE CSV into a list of dicts."""
    records = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        records.append({
            "last_name": (row.get("LASTNAME") or "").strip(),
            "first_name": (row.get("FIRSTNAME") or "").strip(),
            "mid_name": (row.get("MIDNAME") or "").strip(),
            "bus_name": (row.get("BUSNAME") or "").strip(),
            "general_type": (row.get("GENERAL") or "").strip(),
            "specialty": (row.get("SPECIALTY") or "").strip(),
            "npi": (row.get("NPI") or "").strip() or None,
            "dob": parse_date(row.get("DOB")),
            "address": (row.get("ADDRESS") or "").strip(),
            "city": (row.get("CITY") or "").strip(),
            "state": (row.get("STATE") or "").strip(),
            "zip": (row.get("ZIP") or "").strip(),
            "exclusion_type": (row.get("EXCLTYPE") or "").strip(),
            "exclusion_date": parse_date(row.get("EXCLDATE")),
            "reinstatement_date": parse_date(row.get("REINDATE")),
            "waiver_date": parse_date(row.get("WAIVERDATE")),
            "waiver_state": (row.get("WVRSTATE") or "").strip() or None,
        })
    return records


def ingest_leie(db: Session, state_filter: str | None = None) -> int:
    """Download and ingest the LEIE exclusion database.

    Args:
        db: Database session.
        state_filter: If provided, only ingest records for this state (e.g., "TX").
    """
    content = download_leie()
    records = parse_leie_csv(content)

    if state_filter:
        records = [r for r in records if r["state"].upper() == state_filter.upper()]

    # Clear existing exclusions (full reload each time)
    if state_filter:
        db.query(Exclusion).filter(Exclusion.state == state_filter.upper()).delete()
    else:
        db.query(Exclusion).delete()

    count = 0
    for rec in records:
        exclusion = Exclusion(**rec)
        db.add(exclusion)
        count += 1

    db.commit()
    logger.info(f"Ingested {count} LEIE exclusion records")
    return count
