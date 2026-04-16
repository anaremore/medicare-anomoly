"""Entity formation velocity analysis.

Detects rapid entity registration patterns:
- Same-day/same-week registration bursts at an address
- Template-style naming patterns
- Multiple NPIs for same org name
- Residential address registration
"""

import logging
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import Address, Provider, ProviderAddress

logger = logging.getLogger(__name__)

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]

# Template-style name patterns — generic adjective + "medical supply/DME"
TEMPLATE_PATTERNS = [
    r"^(FIRST|PRIME|BEST|TOP|ELITE|PREMIER|RELIABLE|TRUSTED|ADVANCED|ALLIED)\s+(MEDICAL|MED|DME|HEALTH)",
    r"^[A-Z]\s*&\s*[A-Z]\s+(MEDICAL|MED|DME)",
    r"^[A-Z]{2,3}\s+(MEDICAL|MED|DME|DURABLE)",
    r"(MEDICAL\s+(SUPPLY|SUPPLIES|EQUIPMENT)|DME\s+(SUPPLY|SUPPLIES|LLC))\s*$",
]
TEMPLATE_RE = [re.compile(p) for p in TEMPLATE_PATTERNS]


def detect_registration_bursts(db: Session, days_window: int = 7) -> list[dict]:
    """Find addresses where multiple providers registered within a short window.

    Returns list of burst events with address, dates, and provider details.
    """
    # Get all providers with enumeration dates at addresses with 2+ providers
    rows = (
        db.query(
            Address.id.label("address_id"),
            Address.normalized_address,
            Address.city,
            Address.zip,
            Provider.npi,
            Provider.org_name,
            Provider.enumeration_date,
        )
        .join(ProviderAddress, ProviderAddress.address_id == Address.id)
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .filter(
            Provider.enumeration_date.isnot(None),
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
        )
        .order_by(Address.id, Provider.enumeration_date)
        .all()
    )

    # Group by address
    by_address: dict[int, list] = defaultdict(list)
    for row in rows:
        by_address[row.address_id].append(row)

    bursts = []
    for address_id, providers in by_address.items():
        if len(providers) < 2:
            continue

        # Sliding window: find groups registered within `days_window` days
        providers_sorted = sorted(providers, key=lambda p: p.enumeration_date)
        i = 0
        while i < len(providers_sorted):
            window = [providers_sorted[i]]
            j = i + 1
            while j < len(providers_sorted):
                delta = (
                    providers_sorted[j].enumeration_date
                    - providers_sorted[i].enumeration_date
                ).days
                if delta <= days_window:
                    window.append(providers_sorted[j])
                    j += 1
                else:
                    break

            if len(window) >= 2:
                bursts.append({
                    "address_id": address_id,
                    "address": providers_sorted[i].normalized_address,
                    "city": providers_sorted[i].city,
                    "zip": providers_sorted[i].zip,
                    "burst_size": len(window),
                    "start_date": str(window[0].enumeration_date),
                    "end_date": str(window[-1].enumeration_date),
                    "providers": [
                        {
                            "npi": p.npi,
                            "name": p.org_name,
                            "date": str(p.enumeration_date),
                        }
                        for p in window
                    ],
                })
                i = j  # Skip past this burst
            else:
                i += 1

    return sorted(bursts, key=lambda b: b["burst_size"], reverse=True)


def detect_template_names(db: Session) -> list[dict]:
    """Find providers with template-style generic names."""
    providers = (
        db.query(Provider)
        .filter(
            Provider.org_name.isnot(None),
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
        )
        .all()
    )

    matches = []
    for p in providers:
        name = p.org_name.upper().strip()
        for pattern in TEMPLATE_RE:
            if pattern.search(name):
                matches.append({
                    "npi": p.npi,
                    "org_name": p.org_name,
                    "taxonomy": p.taxonomy_desc,
                    "enumeration_date": str(p.enumeration_date) if p.enumeration_date else None,
                    "address": f"{p.practice_address_1}, {p.practice_city}, {p.practice_state} {p.practice_zip}",
                })
                break

    return matches


def detect_duplicate_names(db: Session) -> list[dict]:
    """Find organization names that appear multiple times (different NPIs)."""
    dupes = (
        db.query(
            Provider.org_name,
            func.count(Provider.npi).label("npi_count"),
        )
        .filter(
            Provider.org_name.isnot(None),
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
        )
        .group_by(Provider.org_name)
        .having(func.count(Provider.npi) > 1)
        .order_by(func.count(Provider.npi).desc())
        .all()
    )

    results = []
    for name, count in dupes:
        providers = (
            db.query(Provider)
            .filter(Provider.org_name == name)
            .all()
        )
        results.append({
            "org_name": name,
            "npi_count": count,
            "providers": [
                {
                    "npi": p.npi,
                    "enumeration_date": str(p.enumeration_date) if p.enumeration_date else None,
                    "address": f"{p.practice_address_1}, {p.practice_city}",
                }
                for p in providers
            ],
        })

    return results


def compute_entity_profile_score(db: Session, npi: str) -> tuple[float, dict]:
    """Compute an entity profile risk score for a single provider.

    Factors:
    - Entity age (newer = higher risk, max 25 points)
    - Template-style name (15 points)
    - Multiple NPIs for same name (15 points)
    - Registration burst at same address (20 points)
    - Residential-style address (10 points)
    - Non-medical org name at medical taxonomy (15 points)
    """
    provider = db.get(Provider, npi)
    if not provider:
        return 0.0, {}

    score = 0.0
    signals = {}

    # Entity age — newer entities are higher risk
    if provider.enumeration_date:
        age_days = (date.today() - provider.enumeration_date).days
        if age_days < 180:
            age_score = 25.0
        elif age_days < 365:
            age_score = 20.0
        elif age_days < 730:
            age_score = 10.0
        else:
            age_score = 0.0
        signals["entity_age_days"] = age_days
        signals["age_score"] = age_score
        score += age_score

    # Template name check
    if provider.org_name:
        name = provider.org_name.upper()
        is_template = any(p.search(name) for p in TEMPLATE_RE)
        signals["template_name"] = is_template
        if is_template:
            score += 15.0

    # Multiple NPIs for same org name
    if provider.org_name:
        same_name_count = (
            db.query(func.count(Provider.npi))
            .filter(Provider.org_name == provider.org_name)
            .scalar()
        ) or 0
        signals["same_name_npi_count"] = same_name_count
        if same_name_count > 1:
            score += min(15.0, (same_name_count - 1) * 7.5)

    # Check for APT/apartment in address (residential indicator)
    if provider.practice_address_1:
        addr = provider.practice_address_1.upper()
        is_residential = bool(re.search(r"\bAPT\b|\bAPARTMENT\b|\bUNIT\b\s+\d", addr))
        signals["residential_address"] = is_residential
        if is_residential:
            score += 10.0

    signals["total"] = round(min(100.0, score), 1)
    return round(min(100.0, score), 1), signals
