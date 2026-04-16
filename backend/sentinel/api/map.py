"""Map data endpoints — GeoJSON for Leaflet layers."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.db import get_db
from sentinel.models import Address, Provider, ProviderAddress, RiskScore

router = APIRouter(tags=["map"])

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]


@router.get("/map/heatmap")
def get_zip_heatmap(db: Session = Depends(get_db)):
    """Get ZIP-level provider density for choropleth map.

    Returns provider counts and average risk per ZIP code.
    """
    results = (
        db.query(
            Provider.practice_zip,
            func.count(Provider.npi).label("provider_count"),
            func.avg(RiskScore.composite_score).label("avg_risk"),
        )
        .outerjoin(RiskScore, RiskScore.npi == Provider.npi)
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
        .group_by(Provider.practice_zip)
        .order_by(func.count(Provider.npi).desc())
        .all()
    )

    return {
        "type": "zip_heatmap",
        "data": [
            {
                "zip": (row.practice_zip or "")[:5],
                "provider_count": row.provider_count,
                "avg_risk": round(float(row.avg_risk), 1) if row.avg_risk else 0,
            }
            for row in results
            if row.practice_zip
        ],
    }


@router.get("/map/clusters")
def get_address_clusters(
    min_providers: int = Query(3, ge=2),
    db: Session = Depends(get_db),
):
    """Get address-level cluster markers as GeoJSON.

    Returns addresses with N+ providers as point features.
    """
    results = (
        db.query(
            Address,
            func.count(ProviderAddress.provider_npi).label("provider_count"),
            func.avg(RiskScore.composite_score).label("avg_risk"),
        )
        .join(ProviderAddress, ProviderAddress.address_id == Address.id)
        .join(Provider, Provider.npi == ProviderAddress.provider_npi)
        .outerjoin(RiskScore, RiskScore.npi == Provider.npi)
        .filter(Provider.taxonomy_code.in_(TAXONOMY_CODES))
        .group_by(Address.id)
        .having(func.count(ProviderAddress.provider_npi) >= min_providers)
        .order_by(func.count(ProviderAddress.provider_npi).desc())
        .all()
    )

    features = []
    for address, count, avg_risk in results:
        if address.lat is None or address.lng is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(address.lng), float(address.lat)],
            },
            "properties": {
                "address_id": address.id,
                "address": f"{address.normalized_address}, {address.city}, {address.state} {address.zip}",
                "provider_count": count,
                "avg_risk": round(float(avg_risk), 1) if avg_risk else 0,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
