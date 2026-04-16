"""Dashboard statistics endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.db import get_db
from sentinel.models import (
    Address,
    Alert,
    Exclusion,
    Provider,
    ProviderAddress,
    RiskScore,
)

router = APIRouter(tags=["stats"])

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get key dashboard statistics."""
    total_providers = (
        db.query(func.count(Provider.npi))
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
        .scalar()
    ) or 0

    total_addresses = (
        db.query(func.count(func.distinct(ProviderAddress.address_id)))
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
        .scalar()
    ) or 0

    # Flagged addresses (5+ target providers)
    flagged_addresses = (
        db.query(func.count())
        .select_from(
            db.query(ProviderAddress.address_id)
            .join(Provider, Provider.npi == ProviderAddress.provider_npi)
            .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
            .group_by(ProviderAddress.address_id)
            .having(func.count(ProviderAddress.provider_npi) >= 5)
            .subquery()
        )
        .scalar()
    ) or 0

    total_exclusions_tx = (
        db.query(func.count(Exclusion.id))
        .filter(Exclusion.state == "TX")
        .scalar()
    ) or 0

    active_alerts = (
        db.query(func.count(Alert.id))
        .filter(Alert.acknowledged == False)
        .scalar()
    ) or 0

    critical_alerts = (
        db.query(func.count(Alert.id))
        .filter(Alert.severity == "critical", Alert.acknowledged == False)
        .scalar()
    ) or 0

    high_risk_providers = (
        db.query(func.count(RiskScore.npi))
        .filter(RiskScore.composite_score >= 50)
        .scalar()
    ) or 0

    # Top ZIPs by provider count
    top_zips = (
        db.query(
            Provider.practice_zip,
            func.count(Provider.npi).label("count"),
        )
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
        .group_by(Provider.practice_zip)
        .order_by(func.count(Provider.npi).desc())
        .limit(10)
        .all()
    )

    return {
        "total_providers": total_providers,
        "total_addresses": total_addresses,
        "flagged_addresses": flagged_addresses,
        "total_exclusions_tx": total_exclusions_tx,
        "active_alerts": active_alerts,
        "critical_alerts": critical_alerts,
        "high_risk_providers": high_risk_providers,
        "top_zips": [
            {"zip": (z or "")[:5], "count": c} for z, c in top_zips
        ],
    }
