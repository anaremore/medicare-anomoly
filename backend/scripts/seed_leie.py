#!/usr/bin/env python3
"""Seed the database with OIG LEIE exclusion data."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.db import SessionLocal
from sentinel.etl.leie import ingest_leie

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting LEIE ingestion...")
    db = SessionLocal()
    try:
        # Load all exclusions (not just TX) for NPI cross-matching
        count = ingest_leie(db, state_filter=None)
        logger.info(f"Ingested {count} exclusion records")
    finally:
        db.close()


if __name__ == "__main__":
    main()
