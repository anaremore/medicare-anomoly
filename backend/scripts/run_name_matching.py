#!/usr/bin/env python3
"""Run name matching between providers and LEIE exclusion records."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.db import SessionLocal
from sentinel.models import PersonMatch
from sentinel.analysis.name_matching import match_providers_against_leie

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    db = SessionLocal()
    try:
        logger.info("Running name matching: providers vs LEIE exclusions...")
        matches = match_providers_against_leie(db, min_confidence=30.0)

        # Clear old matches and save new ones
        db.query(PersonMatch).filter(PersonMatch.matched_source == "leie").delete()

        for m in matches:
            pm = PersonMatch(
                provider_npi=m.provider_npi,
                provider_name=m.provider_name,
                matched_source=m.matched_source,
                matched_record_id=m.matched_record_id,
                matched_name=m.matched_name,
                matched_city=m.matched_city,
                matched_state=m.matched_state,
                matched_specialty=m.matched_specialty,
                matched_exclusion_type=m.matched_exclusion_type,
                matched_exclusion_date=m.matched_exclusion_date,
                confidence=m.confidence,
                confidence_factors=m.confidence_factors,
                match_type=m.match_type,
            )
            db.add(pm)

        db.commit()

        # Report
        high = sum(1 for m in matches if m.confidence >= 80)
        medium = sum(1 for m in matches if 50 <= m.confidence < 80)
        low = sum(1 for m in matches if 30 <= m.confidence < 50)
        logger.info(f"Saved {len(matches)} matches: {high} HIGH, {medium} MEDIUM, {low} LOW confidence")

        # Show top matches
        for m in matches[:15]:
            level = "HIGH" if m.confidence >= 80 else "MEDIUM" if m.confidence >= 50 else "LOW"
            logger.info(
                f"  [{level} {m.confidence}] {m.provider_name} (NPI {m.provider_npi}) "
                f"<-> {m.matched_name} ({m.matched_source}, {m.matched_city} {m.matched_state}) "
                f"[{m.match_type}]"
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()
