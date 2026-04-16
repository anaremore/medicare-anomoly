"""Composite risk scoring engine.

Combines address clustering, entity profile, network association,
geographic risk, and billing velocity scores into a weighted composite.
"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import (
    Address,
    Exclusion,
    Provider,
    ProviderAddress,
    RiskScore,
)
from sentinel.analysis.clustering import compute_address_clustering_score
from sentinel.analysis.velocity import compute_entity_profile_score
from sentinel.analysis.billing import compute_billing_velocity_score

logger = logging.getLogger(__name__)

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]

# Score weights — billing velocity added as 5th component
WEIGHTS = {
    "address_clustering": 0.25,
    "entity_profile": 0.20,
    "network_association": 0.20,
    "geographic_risk": 0.15,
    "billing_velocity": 0.20,
}


def compute_network_association_score(
    db: Session, npi: str
) -> tuple[float, dict]:
    """Score based on association with excluded entities.

    Factors:
    - Shares address with excluded entity (40 points)
    - Same address has had entity deactivated (20 points)
    - Multiple taxonomy types at same address (15 points)
    """
    score = 0.0
    signals = {}

    # Find the provider's address
    link = (
        db.query(ProviderAddress)
        .filter(
            ProviderAddress.provider_npi == npi,
            ProviderAddress.address_purpose == "LOCATION",
        )
        .first()
    )
    if not link:
        return 0.0, {}

    address_id = link.address_id

    # Get all NPIs at this address
    colocated_npis = [
        row[0]
        for row in db.query(ProviderAddress.provider_npi)
        .filter(ProviderAddress.address_id == address_id)
        .all()
    ]

    # Check for excluded entities at same address
    excluded_at_address = (
        db.query(func.count(Exclusion.id))
        .filter(Exclusion.npi.in_(colocated_npis))
        .scalar()
    ) or 0

    signals["excluded_at_same_address"] = excluded_at_address
    if excluded_at_address > 0:
        score += min(40.0, excluded_at_address * 20)

    # Check for deactivated providers at same address
    deactivated_count = (
        db.query(func.count(Provider.npi))
        .filter(
            Provider.npi.in_(colocated_npis),
            Provider.deactivation_date.isnot(None),
        )
        .scalar()
    ) or 0

    signals["deactivated_at_same_address"] = deactivated_count
    if deactivated_count > 0:
        score += min(20.0, deactivated_count * 10)

    # Multiple taxonomy types at same address (diversity of fraud types)
    distinct_taxonomies = (
        db.query(func.count(func.distinct(Provider.taxonomy_code)))
        .filter(
            Provider.npi.in_(colocated_npis),
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
        )
        .scalar()
    ) or 0

    signals["distinct_risk_taxonomies_at_address"] = distinct_taxonomies
    if distinct_taxonomies > 1:
        score += 15.0

    return round(min(100.0, score), 1), signals


def compute_geographic_risk_score(
    db: Session, npi: str
) -> tuple[float, dict]:
    """Score based on geographic indicators.

    Factors:
    - ZIP-level DME density (providers per ZIP, max 50 points)
    - ZIP-level exclusion density (max 30 points)
    - Address is in a known high-risk ZIP (20 points)
    """
    provider = db.get(Provider, npi)
    if not provider or not provider.practice_zip:
        return 0.0, {}

    zip5 = provider.practice_zip[:5]

    # Count DME/HHA/hospice providers in this ZIP
    zip_provider_count = (
        db.query(func.count(Provider.npi))
        .filter(
            Provider.practice_zip.startswith(zip5),
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
        )
        .scalar()
    ) or 0

    # Count exclusions in this ZIP
    zip_exclusion_count = (
        db.query(func.count(Exclusion.id))
        .filter(Exclusion.zip.startswith(zip5))
        .scalar()
    ) or 0

    # Compute scores
    import math

    density_score = min(50.0, math.log2(max(1, zip_provider_count)) * 7)
    excl_density_score = min(30.0, math.log2(max(1, zip_exclusion_count)) * 8)

    # Known high-risk ZIPs (from our proof-of-concept findings)
    HIGH_RISK_ZIPS = {"77036", "77074", "77060", "77057", "77054"}
    in_high_risk = zip5 in HIGH_RISK_ZIPS
    geo_bonus = 20.0 if in_high_risk else 0.0

    score = density_score + excl_density_score + geo_bonus

    signals = {
        "zip": zip5,
        "zip_target_provider_count": zip_provider_count,
        "zip_exclusion_count": zip_exclusion_count,
        "in_high_risk_zip": in_high_risk,
        "density_score": round(density_score, 1),
        "excl_density_score": round(excl_density_score, 1),
        "geo_bonus": geo_bonus,
    }

    return round(min(100.0, score), 1), signals


def compute_all_risk_scores(db: Session) -> int:
    """Compute risk scores for all target-taxonomy providers."""
    providers = (
        db.query(Provider)
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
        .all()
    )

    count = 0
    for provider in providers:
        # Get address for clustering score
        link = (
            db.query(ProviderAddress)
            .filter(
                ProviderAddress.provider_npi == provider.npi,
                ProviderAddress.address_purpose == "LOCATION",
            )
            .first()
        )

        # Compute each component
        clustering_score, clustering_signals = (
            compute_address_clustering_score(db, link.address_id)
            if link
            else (0.0, {})
        )
        profile_score, profile_signals = compute_entity_profile_score(
            db, provider.npi
        )
        network_score, network_signals = compute_network_association_score(
            db, provider.npi
        )
        geo_score, geo_signals = compute_geographic_risk_score(
            db, provider.npi
        )
        billing_score, billing_signals = compute_billing_velocity_score(
            db, provider.npi
        )

        # Weighted composite
        composite = (
            clustering_score * WEIGHTS["address_clustering"]
            + profile_score * WEIGHTS["entity_profile"]
            + network_score * WEIGHTS["network_association"]
            + geo_score * WEIGHTS["geographic_risk"]
            + billing_score * WEIGHTS["billing_velocity"]
        )

        signals = {
            "address_clustering": clustering_signals,
            "entity_profile": profile_signals,
            "network_association": network_signals,
            "geographic_risk": geo_signals,
            "billing_velocity": billing_signals,
        }

        # Upsert risk score
        risk = db.get(RiskScore, provider.npi)
        if risk is None:
            risk = RiskScore(npi=provider.npi)
            db.add(risk)

        risk.address_clustering_score = clustering_score
        risk.entity_profile_score = profile_score
        risk.network_association_score = network_score
        risk.geographic_risk_score = geo_score
        risk.billing_velocity_score = billing_score
        risk.composite_score = round(composite, 1)
        risk.signals = signals
        risk.computed_at = datetime.now()
        count += 1

        if count % 100 == 0:
            db.flush()
            logger.info(f"Scored {count} providers...")

    db.commit()
    logger.info(f"Computed risk scores for {count} providers")
    return count
