"""CMS Medicare billing data ingestion.

Downloads and parses:
1. DMEPOS by Supplier (aggregate billing per NPI)
2. DMEPOS by Supplier and Service (HCPCS-level detail per NPI)

Uses the CMS data.cms.gov API to filter for Texas providers,
avoiding full CSV downloads of multi-GB national files.
"""

import logging
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from sentinel.models import Billing, BillingSummary

logger = logging.getLogger(__name__)

# CMS API endpoints — most recent data years
# File naming: dy23 = data year 2023, dy22 = data year 2022, etc.
DMEPOS_SUPPLIER_API = {
    2023: "https://data.cms.gov/data-api/v1/dataset/a2d56d3f-3531-4315-9d87-e29986516b41/data",
    2022: "https://data.cms.gov/data-api/v1/dataset/7bb52a09-9eba-43f9-b7ec-57f65fbbc86c/data",
    2021: "https://data.cms.gov/data-api/v1/dataset/471f9c0d-12c4-4601-a547-559dcfa2d0e2/data",
}

DMEPOS_SUPPLIER_SERVICE_API = {
    2023: "https://data.cms.gov/data-api/v1/dataset/1746a83e-bb65-4300-8e02-21edbab77c6b/data",
    2022: "https://data.cms.gov/data-api/v1/dataset/44235fd3-6cf9-487f-928d-12998cd84071/data",
    2021: "https://data.cms.gov/data-api/v1/dataset/dad703df-2e52-4ac6-a26f-51ecbf463d77/data",
}


def _safe_decimal(val) -> Decimal | None:
    if val is None or val == "" or val == "0":
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _safe_int(val) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except Exception:
        return None


def fetch_cms_api(
    url: str,
    state: str = "TX",
    size: int = 5000,
    offset: int = 0,
) -> list[dict]:
    """Fetch records from a CMS data API endpoint, filtered by state."""
    params = {
        "size": size,
        "offset": offset,
        "filter[Suplr_Prvdr_State_Abrvtn]": state,
    }
    response = httpx.get(url, params=params, timeout=60.0)
    response.raise_for_status()
    return response.json()


def fetch_all_cms_api(url: str, state: str = "TX") -> list[dict]:
    """Fetch all records for a state, paginating through results."""
    all_records = []
    offset = 0
    size = 5000
    while True:
        batch = fetch_cms_api(url, state=state, size=size, offset=offset)
        if not batch:
            break
        all_records.extend(batch)
        logger.info(f"  Fetched {len(all_records)} records so far...")
        if len(batch) < size:
            break
        offset += size
    return all_records


def ingest_dmepos_supplier_summary(
    db: Session, data_year: int = 2023, state: str = "TX"
) -> int:
    """Ingest DMEPOS by Supplier data (aggregate billing per NPI).

    This gives us total billing, beneficiaries, claims, and services per supplier,
    broken down by DME vs POS vs Drug categories.
    """
    api_url = DMEPOS_SUPPLIER_API.get(data_year)
    if not api_url:
        logger.error(f"No API URL for data year {data_year}")
        return 0

    logger.info(f"Fetching DMEPOS Supplier summary for {state}, year {data_year}...")
    records = fetch_all_cms_api(api_url, state=state)
    logger.info(f"Downloaded {len(records)} supplier records")

    # Clear existing data for this year
    db.query(BillingSummary).filter(BillingSummary.data_year == data_year).delete()

    count = 0
    for rec in records:
        npi = rec.get("Suplr_NPI")
        if not npi:
            continue

        summary = BillingSummary(
            npi=npi,
            total_hcpcs_codes=_safe_int(rec.get("Tot_Suplr_HCPCS_Cds")),
            total_beneficiaries=_safe_int(rec.get("Tot_Suplr_Benes")),
            total_claims=_safe_int(rec.get("Tot_Suplr_Clms")),
            total_services=_safe_decimal(rec.get("Tot_Suplr_Srvcs")),
            total_submitted_charges=_safe_decimal(rec.get("Suplr_Sbmtd_Chrgs")),
            total_medicare_allowed=_safe_decimal(rec.get("Suplr_Mdcr_Alowd_Amt")),
            total_medicare_payment=_safe_decimal(rec.get("Suplr_Mdcr_Pymt_Amt")),
            dme_total_services=_safe_decimal(rec.get("DME_Tot_Suplr_Srvcs")),
            dme_submitted_charges=_safe_decimal(rec.get("DME_Suplr_Sbmtd_Chrgs")),
            dme_medicare_payment=_safe_decimal(rec.get("DME_Suplr_Mdcr_Pymt_Amt")),
            pos_total_services=_safe_decimal(rec.get("POS_Tot_Suplr_Srvcs")),
            pos_submitted_charges=_safe_decimal(rec.get("POS_Suplr_Sbmtd_Chrgs")),
            pos_medicare_payment=_safe_decimal(rec.get("POS_Suplr_Mdcr_Pymt_Amt")),
            data_year=data_year,
        )
        db.add(summary)
        count += 1

    db.commit()
    logger.info(f"Ingested {count} DMEPOS supplier summaries for {state} ({data_year})")
    return count


def ingest_dmepos_supplier_service(
    db: Session, data_year: int = 2023, state: str = "TX"
) -> int:
    """Ingest DMEPOS by Supplier and Service data (HCPCS-level detail).

    This gives us per-HCPCS-code billing for each supplier NPI —
    critical for detecting high-risk code concentration.
    """
    api_url = DMEPOS_SUPPLIER_SERVICE_API.get(data_year)
    if not api_url:
        logger.error(f"No API URL for data year {data_year}")
        return 0

    logger.info(f"Fetching DMEPOS Supplier+Service detail for {state}, year {data_year}...")
    records = fetch_all_cms_api(api_url, state=state)
    logger.info(f"Downloaded {len(records)} service records")

    # Clear existing data for this year + source
    db.query(Billing).filter(
        Billing.data_year == data_year,
        Billing.source == "dmepos_supplier",
    ).delete()

    count = 0
    for rec in records:
        npi = rec.get("Suplr_NPI")
        if not npi:
            continue

        billing = Billing(
            npi=npi,
            hcpcs_code=rec.get("HCPCS_Cd"),
            hcpcs_description=rec.get("HCPCS_Desc"),
            rbcs_category=rec.get("RBCS_Lvl"),
            total_beneficiaries=_safe_int(rec.get("Tot_Suplr_Benes")),
            total_claims=_safe_int(rec.get("Tot_Suplr_Clms")),
            total_services=_safe_decimal(rec.get("Tot_Suplr_Srvcs")),
            avg_submitted_charge=_safe_decimal(rec.get("Avg_Suplr_Sbmtd_Chrg")),
            avg_medicare_allowed=_safe_decimal(rec.get("Avg_Suplr_Mdcr_Alowd_Amt")),
            avg_medicare_payment=_safe_decimal(rec.get("Avg_Suplr_Mdcr_Pymt_Amt")),
            is_rental=rec.get("Suplr_Rentl_Ind") == "Y",
            data_year=data_year,
            source="dmepos_supplier",
        )
        db.add(billing)
        count += 1

        if count % 5000 == 0:
            db.flush()

    db.commit()
    logger.info(f"Ingested {count} DMEPOS billing line items for {state} ({data_year})")
    return count


def ingest_all_cms(db: Session, state: str = "TX") -> dict:
    """Ingest all available CMS DMEPOS data for multiple years."""
    results = {}
    for year in [2023, 2022, 2021]:
        logger.info(f"=== Processing data year {year} ===")
        summary_count = ingest_dmepos_supplier_summary(db, data_year=year, state=state)
        detail_count = ingest_dmepos_supplier_service(db, data_year=year, state=state)
        results[year] = {"summaries": summary_count, "line_items": detail_count}
    return results
