"""Address clustering endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.db import get_db
from sentinel.models import Address, Provider, ProviderAddress, RiskScore

router = APIRouter(tags=["addresses"])

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]


@router.get("/addresses")
def list_clustered_addresses(
    min_providers: int = Query(2, ge=1),
    zip: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List addresses ranked by provider clustering density."""
    q = (
        db.query(
            Address,
            func.count(ProviderAddress.provider_npi).label("total_providers"),
            func.count(
                func.nullif(
                    Provider.taxonomy_code.in_(TAXONOMY_CODES), False
                )
            ).label("target_providers"),
        )
        .join(ProviderAddress, ProviderAddress.address_id == Address.id)
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .group_by(Address.id)
        .having(func.count(ProviderAddress.provider_npi) >= min_providers)
    )

    if zip:
        q = q.filter(Address.zip == zip)

    q = q.order_by(func.count(ProviderAddress.provider_npi).desc())
    total = q.count()
    results = q.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [
            {
                "address_id": address.id,
                "normalized_address": address.normalized_address,
                "city": address.city,
                "state": address.state,
                "zip": address.zip,
                "lat": float(address.lat) if address.lat else None,
                "lng": float(address.lng) if address.lng else None,
                "total_providers": total_providers,
                "target_providers": target_providers,
            }
            for address, total_providers, target_providers in results
        ],
    }


@router.get("/addresses/{address_id}")
def get_address_detail(address_id: int, db: Session = Depends(get_db)):
    """Get all providers at an address with timeline."""
    address = db.get(Address, address_id)
    if not address:
        return {"error": "Address not found"}, 404

    providers = (
        db.query(Provider, RiskScore, ProviderAddress)
        .outerjoin(RiskScore, RiskScore.npi == Provider.npi)
        .join(ProviderAddress, ProviderAddress.provider_npi == Provider.npi)
        .filter(ProviderAddress.address_id == address_id)
        .order_by(Provider.enumeration_date.desc().nullslast())
        .all()
    )

    return {
        "address_id": address.id,
        "normalized_address": address.normalized_address,
        "city": address.city,
        "state": address.state,
        "zip": address.zip,
        "lat": float(address.lat) if address.lat else None,
        "lng": float(address.lng) if address.lng else None,
        "provider_count": len(providers),
        "providers": [
            {
                "npi": provider.npi,
                "name": provider.org_name or f"{provider.last_name}, {provider.first_name}",
                "taxonomy_desc": provider.taxonomy_desc,
                "enumeration_date": str(provider.enumeration_date) if provider.enumeration_date else None,
                "deactivation_date": str(provider.deactivation_date) if provider.deactivation_date else None,
                "composite_score": float(risk.composite_score) if risk and risk.composite_score else None,
                "first_seen": str(pa.first_seen) if pa.first_seen else None,
                "last_seen": str(pa.last_seen) if pa.last_seen else None,
            }
            for provider, risk, pa in providers
        ],
    }
