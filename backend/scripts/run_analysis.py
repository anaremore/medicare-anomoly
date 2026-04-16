#!/usr/bin/env python3
"""Run all analysis passes: scoring and alert generation."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.db import SessionLocal
from sentinel.analysis.scoring import compute_all_risk_scores
from sentinel.analysis.alerts import generate_all_alerts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    db = SessionLocal()
    try:
        logger.info("Computing risk scores...")
        scored = compute_all_risk_scores(db)
        logger.info(f"Scored {scored} providers")

        logger.info("Generating alerts...")
        alerts = generate_all_alerts(db)
        logger.info(f"Generated {alerts} alerts")
    finally:
        db.close()


if __name__ == "__main__":
    main()
