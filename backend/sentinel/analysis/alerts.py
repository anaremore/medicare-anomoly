"""Alert generation engine.

Generates alerts for anomalous events:
- New NPI registrations at flagged addresses
- Entities sharing address with excluded providers
- Registration bursts (multiple entities same day/week)
"""

import logging
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import (
    Address,
    Alert,
    Exclusion,
    Provider,
    ProviderAddress,
    RiskScore,
)
from sentinel.analysis.velocity import detect_registration_bursts

logger = logging.getLogger(__name__)

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]

# Thresholds
CLUSTER_THRESHOLD = 5  # Addresses with 5+ target providers are "flagged"
HIGH_RISK_SCORE_THRESHOLD = 50.0


def generate_new_registration_alerts(
    db: Session, lookback_days: int = 30
) -> int:
    """Generate alerts for new registrations at flagged addresses."""
    cutoff = date.today() - timedelta(days=lookback_days)

    # Find flagged addresses (5+ target-taxonomy providers)
    flagged_addresses = (
        db.query(ProviderAddress.address_id)
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
        .group_by(ProviderAddress.address_id)
        .having(func.count(ProviderAddress.provider_npi) >= CLUSTER_THRESHOLD)
        .subquery()
    )

    # Find new providers at flagged addresses
    new_at_flagged = (
        db.query(Provider, Address)
        .join(ProviderAddress, ProviderAddress.provider_npi == Provider.npi)
        .join(Address, Address.id == ProviderAddress.address_id)
        .filter(
            ProviderAddress.address_id.in_(db.query(flagged_addresses.c.address_id)),
            Provider.enumeration_date >= cutoff,
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
        )
        .all()
    )

    count = 0
    for provider, address in new_at_flagged:
        # Check if alert already exists
        existing = (
            db.query(Alert)
            .filter(
                Alert.alert_type == "new_registration_at_flagged",
                Alert.npi == provider.npi,
            )
            .first()
        )
        if existing:
            continue

        # Check if address has excluded entities
        has_excluded = (
            db.query(Exclusion)
            .join(Provider, Provider.npi == Exclusion.npi)
            .join(ProviderAddress, ProviderAddress.provider_npi == Provider.npi)
            .filter(ProviderAddress.address_id == address.id)
            .first()
        ) is not None

        severity = "critical" if has_excluded else "high"

        alert = Alert(
            alert_type="new_registration_at_flagged",
            npi=provider.npi,
            address_id=address.id,
            severity=severity,
            details={
                "org_name": provider.org_name,
                "enumeration_date": str(provider.enumeration_date),
                "address": f"{address.normalized_address}, {address.city}, {address.state} {address.zip}",
                "has_excluded_at_address": has_excluded,
                "taxonomy": provider.taxonomy_desc,
            },
        )
        db.add(alert)
        count += 1

    db.commit()
    logger.info(f"Generated {count} new registration alerts")
    return count


def generate_burst_alerts(db: Session) -> int:
    """Generate alerts for registration bursts."""
    bursts = detect_registration_bursts(db, days_window=7)

    count = 0
    for burst in bursts:
        if burst["burst_size"] < 2:
            continue

        # Check if alert already exists for this burst
        existing = (
            db.query(Alert)
            .filter(
                Alert.alert_type == "registration_burst",
                Alert.address_id == burst["address_id"],
                Alert.details["start_date"].astext == burst["start_date"],
            )
            .first()
        )
        if existing:
            continue

        severity = "critical" if burst["burst_size"] >= 3 else "high"

        alert = Alert(
            alert_type="registration_burst",
            address_id=burst["address_id"],
            severity=severity,
            details=burst,
        )
        db.add(alert)
        count += 1

    db.commit()
    logger.info(f"Generated {count} registration burst alerts")
    return count


def generate_exclusion_proximity_alerts(db: Session) -> int:
    """Generate alerts for active providers sharing address with excluded entities."""
    # Find addresses that have both active providers and excluded entities
    excluded_npis = db.query(Exclusion.npi).filter(Exclusion.npi.isnot(None)).subquery()

    # Get addresses where excluded entities are registered
    excluded_addresses = (
        db.query(ProviderAddress.address_id)
        .filter(ProviderAddress.provider_npi.in_(db.query(excluded_npis.c.npi)))
        .distinct()
        .subquery()
    )

    # Find active providers at those addresses
    active_at_excluded = (
        db.query(Provider, Address)
        .join(ProviderAddress, ProviderAddress.provider_npi == Provider.npi)
        .join(Address, Address.id == ProviderAddress.address_id)
        .filter(
            ProviderAddress.address_id.in_(db.query(excluded_addresses.c.address_id)),
            Provider.deactivation_date.is_(None),
            Provider.taxonomy_code.in_(TAXONOMY_CODES),
            ~Provider.npi.in_(db.query(excluded_npis.c.npi)),  # Exclude the excluded ones
        )
        .all()
    )

    count = 0
    for provider, address in active_at_excluded:
        existing = (
            db.query(Alert)
            .filter(
                Alert.alert_type == "exclusion_proximity",
                Alert.npi == provider.npi,
            )
            .first()
        )
        if existing:
            continue

        alert = Alert(
            alert_type="exclusion_proximity",
            npi=provider.npi,
            address_id=address.id,
            severity="critical",
            details={
                "org_name": provider.org_name,
                "address": f"{address.normalized_address}, {address.city}, {address.state} {address.zip}",
                "taxonomy": provider.taxonomy_desc,
                "note": "Active provider shares address with OIG-excluded entity",
            },
        )
        db.add(alert)
        count += 1

    db.commit()
    logger.info(f"Generated {count} exclusion proximity alerts")
    return count


def generate_all_alerts(db: Session) -> int:
    """Run all alert generators."""
    total = 0
    total += generate_new_registration_alerts(db)
    total += generate_burst_alerts(db)
    total += generate_exclusion_proximity_alerts(db)
    return total
