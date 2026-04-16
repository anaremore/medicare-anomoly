"""Address clustering analysis.

Identifies addresses with anomalous concentrations of DME/HHA/hospice providers.
Scores each address based on provider count, taxonomy concentration,
presence of excluded entities, and new registration velocity.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import func, case
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import (
    Address,
    Exclusion,
    Provider,
    ProviderAddress,
)

logger = logging.getLogger(__name__)

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]


def compute_address_clusters(db: Session) -> list[dict]:
    """Compute clustering statistics for all addresses.

    Returns a list of dicts with address info and clustering metrics.
    """
    # Count providers per address, with taxonomy breakdown
    results = (
        db.query(
            Address.id,
            Address.normalized_address,
            Address.city,
            Address.state,
            Address.zip,
            Address.lat,
            Address.lng,
            func.count(ProviderAddress.provider_npi).label("provider_count"),
            func.count(
                case(
                    (Provider.taxonomy_code.in_(TAXONOMY_CODES), 1),
                )
            ).label("target_taxonomy_count"),
        )
        .join(ProviderAddress, ProviderAddress.address_id == Address.id)
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .group_by(Address.id)
        .having(func.count(ProviderAddress.provider_npi) >= 2)
        .order_by(func.count(ProviderAddress.provider_npi).desc())
        .all()
    )

    clusters = []
    for row in results:
        cluster = {
            "address_id": row.id,
            "normalized_address": row.normalized_address,
            "city": row.city,
            "state": row.state,
            "zip": row.zip,
            "lat": float(row.lat) if row.lat else None,
            "lng": float(row.lng) if row.lng else None,
            "provider_count": row.provider_count,
            "target_taxonomy_count": row.target_taxonomy_count,
        }
        clusters.append(cluster)

    return clusters


def compute_address_clustering_score(
    db: Session, address_id: int
) -> tuple[float, dict]:
    """Compute a clustering score for a single address.

    Score components:
    - Provider count (log scale, max ~40 points)
    - Target taxonomy concentration (max ~30 points)
    - Excluded entities at address (max ~20 points)
    - Recent registration velocity (max ~10 points)

    Returns (score 0-100, signal breakdown dict).
    """
    import math

    # Provider count at this address
    provider_count = (
        db.query(func.count(ProviderAddress.provider_npi))
        .filter(ProviderAddress.address_id == address_id)
        .scalar()
    ) or 0

    if provider_count == 0:
        return 0.0, {"provider_count": 0}

    # Target taxonomy count
    target_count = (
        db.query(func.count(ProviderAddress.provider_npi))
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .filter(
            ProviderAddress.address_id == address_id,
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
        )
        .scalar()
    ) or 0

    # Count excluded entities at this address
    address = db.get(Address, address_id)
    excluded_count = 0
    if address:
        # Check exclusions by NPI match
        provider_npis = (
            db.query(ProviderAddress.provider_npi)
            .filter(ProviderAddress.address_id == address_id)
            .subquery()
        )
        excluded_count = (
            db.query(func.count(Exclusion.id))
            .filter(Exclusion.npi.in_(db.query(provider_npis.c.provider_npi)))
            .scalar()
        ) or 0

    # Recent registrations (last 12 months)
    one_year_ago = date.today() - timedelta(days=365)
    recent_count = (
        db.query(func.count(ProviderAddress.provider_npi))
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .filter(
            ProviderAddress.address_id == address_id,
            Provider.enumeration_date >= one_year_ago,
        )
        .scalar()
    ) or 0

    # Score computation
    # Provider count: log2 scale, more providers = higher score
    count_score = min(40.0, math.log2(max(1, provider_count)) * 10)

    # Taxonomy concentration: what % are DME/HHA/hospice?
    tax_ratio = target_count / provider_count if provider_count > 0 else 0
    tax_score = tax_ratio * 30

    # Excluded entities: each one adds significant risk
    excl_score = min(20.0, excluded_count * 10)

    # Recent velocity: new registrations in past year
    velocity_score = min(10.0, recent_count * 2.5)

    total = count_score + tax_score + excl_score + velocity_score

    signals = {
        "provider_count": provider_count,
        "target_taxonomy_count": target_count,
        "taxonomy_concentration": round(tax_ratio, 2),
        "excluded_at_address": excluded_count,
        "recent_registrations_12mo": recent_count,
        "count_score": round(count_score, 1),
        "tax_score": round(tax_score, 1),
        "excl_score": round(excl_score, 1),
        "velocity_score": round(velocity_score, 1),
    }

    return round(min(100.0, total), 1), signals
