#!/usr/bin/env python3
"""Seed the database with NPPES provider data for the Houston area."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.db import SessionLocal
from sentinel.etl.nppes import ingest_houston
from sentinel.etl.geocode import geocode_ungeocodeded

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting NPPES ingestion for Houston metro area...")
    db = SessionLocal()
    try:
        count = ingest_houston(db)
        logger.info(f"Ingested {count} providers")

        logger.info("Geocoding addresses...")
        geocoded = geocode_ungeocodeded(db)
        logger.info(f"Geocoded {geocoded} addresses")
    finally:
        db.close()


if __name__ == "__main__":
    main()
