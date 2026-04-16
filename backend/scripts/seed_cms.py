#!/usr/bin/env python3
"""Seed the database with CMS DMEPOS billing data."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.db import SessionLocal
from sentinel.etl.cms_billing import ingest_all_cms

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting CMS DMEPOS billing data ingestion...")
    db = SessionLocal()
    try:
        results = ingest_all_cms(db, state="TX")
        for year, counts in results.items():
            logger.info(
                f"  Year {year}: {counts['summaries']} supplier summaries, "
                f"{counts['line_items']} line items"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
