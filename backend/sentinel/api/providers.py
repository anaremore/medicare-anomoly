"""Provider search and detail endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.db import get_db
from sentinel.models import (
    Address,
    Exclusion,
    Provider,
    ProviderAddress,
    RiskScore,
)

router = APIRouter(tags=["providers"])

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]


@router.get("/providers")
def list_providers(
    zip: str | None = None,
    taxonomy: str | None = None,
    min_risk: float | None = None,
    search: str | None = None,
    sort: str = "risk",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Search and list providers with risk scores."""
    q = (
        db.query(Provider, RiskScore)
        .outerjoin(RiskScore, RiskScore.npi == Provider.npi)
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
    )

    if zip:
        q = q.filter(Provider.practice_zip.startswith(zip))
    if taxonomy:
        q = q.filter(Provider.taxonomy_code == taxonomy)
    if min_risk is not None:
        q = q.filter(RiskScore.composite_score >= min_risk)
    if search:
        q = q.filter(
            func.coalesce(Provider.org_name, "").ilike(f"%{search}%")
            | func.coalesce(Provider.last_name, "").ilike(f"%{search}%")
            | Provider.npi.ilike(f"%{search}%")
        )

    # Sorting
    if sort == "risk":
        q = q.order_by(func.coalesce(RiskScore.composite_score, 0).desc())
    elif sort == "name":
        q = q.order_by(func.coalesce(Provider.org_name, Provider.last_name))
    elif sort == "date":
        q = q.order_by(Provider.enumeration_date.desc().nullslast())

    total = q.count()
    results = q.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [
            _serialize_provider(provider, risk)
            for provider, risk in results
        ],
    }


@router.get("/providers/{npi}")
def get_provider(npi: str, db: Session = Depends(get_db)):
    """Get detailed provider information with risk breakdown."""
    provider = db.get(Provider, npi)
    if not provider:
        return {"error": "Provider not found"}, 404

    risk = db.get(RiskScore, npi)

    # Get exclusion info
    exclusion = db.query(Exclusion).filter(Exclusion.npi == npi).first()

    # Get address with co-located providers
    link = (
        db.query(ProviderAddress)
        .filter(
            ProviderAddress.provider_npi == npi,
            ProviderAddress.address_purpose == "LOCATION",
        )
        .first()
    )

    colocated = []
    if link:
        colocated_providers = (
            db.query(Provider, RiskScore)
            .outerjoin(RiskScore, RiskScore.npi == Provider.npi)
            .join(ProviderAddress, ProviderAddress.provider_npi == Provider.npi)
            .filter(
                ProviderAddress.address_id == link.address_id,
                Provider.npi != npi,
            )
            .order_by(func.coalesce(RiskScore.composite_score, 0).desc())
            .limit(50)
            .all()
        )
        colocated = [
            _serialize_provider(p, r) for p, r in colocated_providers
        ]

    result = _serialize_provider(provider, risk)
    result["exclusion"] = (
        {
            "exclusion_type": exclusion.exclusion_type,
            "exclusion_date": str(exclusion.exclusion_date) if exclusion.exclusion_date else None,
            "reinstatement_date": str(exclusion.reinstatement_date) if exclusion.reinstatement_date else None,
        }
        if exclusion
        else None
    )
    result["colocated_providers"] = colocated
    result["signals"] = risk.signals if risk else None

    return result


def _serialize_provider(provider: Provider, risk: RiskScore | None) -> dict:
    return {
        "npi": provider.npi,
        "entity_type": provider.entity_type,
        "name": provider.org_name or f"{provider.last_name}, {provider.first_name}",
        "org_name": provider.org_name,
        "last_name": provider.last_name,
        "first_name": provider.first_name,
        "taxonomy_code": provider.taxonomy_code,
        "taxonomy_desc": provider.taxonomy_desc,
        "enumeration_date": str(provider.enumeration_date) if provider.enumeration_date else None,
        "deactivation_date": str(provider.deactivation_date) if provider.deactivation_date else None,
        "address": f"{provider.practice_address_1 or ''}, {provider.practice_city or ''}, {provider.practice_state or ''} {provider.practice_zip or ''}".strip(", "),
        "practice_zip": provider.practice_zip,
        "composite_score": float(risk.composite_score) if risk and risk.composite_score else None,
        "address_clustering_score": float(risk.address_clustering_score) if risk and risk.address_clustering_score else None,
        "entity_profile_score": float(risk.entity_profile_score) if risk and risk.entity_profile_score else None,
        "network_association_score": float(risk.network_association_score) if risk and risk.network_association_score else None,
        "geographic_risk_score": float(risk.geographic_risk_score) if risk and risk.geographic_risk_score else None,
    }
