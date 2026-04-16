"""Billing anomaly detection endpoints.

Surfaces the most suspicious billing patterns across all providers:
- Code concentration: High billing with very few HCPCS codes
- Billing spikes: Extreme YoY growth rates
- Volume outliers: Services-per-beneficiary far above normal
- High-risk code dominance: Revenue concentrated in fraud-prone L/E codes
- New entity ramp: Young entities billing large amounts quickly
"""

import logging

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text, case, literal_column
from sqlalchemy.orm import Session

from sentinel.db import get_db
from sentinel.models import Billing, BillingSummary, Provider

logger = logging.getLogger(__name__)
router = APIRouter(tags=["anomalies"])

# Cache NPPES lookups to avoid repeated API calls within a request
_nppes_cache: dict[str, dict] = {}


def lookup_npi(npi: str) -> dict:
    """Look up full provider details from NPPES API, with in-memory cache."""
    if npi in _nppes_cache:
        return _nppes_cache[npi]

    result = {
        "name": None, "address": None, "city": None, "state": None,
        "zip": None, "enumeration_date": None, "taxonomy": None,
        "entity_type": None, "deactivation_date": None,
    }
    try:
        resp = httpx.get(
            "https://npiregistry.cms.hhs.gov/api/",
            params={"version": "2.1", "number": npi},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("result_count", 0) > 0:
            r = data["results"][0]
            basic = r.get("basic", {})
            result["name"] = (
                basic.get("organization_name")
                or f"{basic.get('last_name', '')}, {basic.get('first_name', '')}"
            )
            result["enumeration_date"] = basic.get("enumeration_date")
            result["deactivation_date"] = basic.get("deactivation_date")
            result["entity_type"] = (
                "individual" if r.get("enumeration_type") == "NPI-1" else "organization"
            )
            for t in r.get("taxonomies", []):
                if t.get("primary"):
                    result["taxonomy"] = t.get("desc")
                    break
            for addr in r.get("addresses", []):
                if addr.get("address_purpose") == "LOCATION":
                    result["address"] = (
                        f"{addr.get('address_1', '')}, {addr.get('city', '')}, "
                        f"{addr.get('state', '')} {addr.get('postal_code', '')}"
                    )
                    result["city"] = addr.get("city")
                    result["state"] = addr.get("state")
                    result["zip"] = (addr.get("postal_code") or "")[:5]
                    break
    except Exception:
        pass

    _nppes_cache[npi] = result
    return result


def resolve_name(npi: str, provider: Provider | None) -> tuple[str | None, str | None]:
    """Get name and address from local DB or NPPES API fallback."""
    if provider:
        name = provider.org_name or f"{provider.last_name}, {provider.first_name}"
        address = (
            f"{provider.practice_address_1}, {provider.practice_city}, "
            f"{provider.practice_state} {provider.practice_zip}"
        )
        return name, address

    info = lookup_npi(npi)
    return info["name"], info["address"]


@router.get("/anomalies/code-concentration")
def get_code_concentration_anomalies(
    max_codes: int = Query(5, ge=1, le=20),
    min_payment: float = Query(100000, ge=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Suppliers with high billing concentrated in very few HCPCS codes.

    This is the #1 billing fraud signal — legitimate suppliers bill across
    many codes. Fraudulent suppliers bill millions from 1-5 codes.
    """
    q = db.execute(text("""
        SELECT bs.npi,
               bs.total_medicare_payment,
               bs.total_beneficiaries,
               bs.total_hcpcs_codes,
               bs.total_services,
               bs.total_submitted_charges,
               ROUND(bs.total_medicare_payment / NULLIF(bs.total_beneficiaries, 0), 0) as payment_per_bene,
               ROUND(bs.total_services / NULLIF(bs.total_beneficiaries, 0), 0) as svcs_per_bene,
               bs.data_year
        FROM billing_summary bs
        WHERE bs.data_year = (SELECT MAX(data_year) FROM billing_summary)
          AND bs.total_medicare_payment > :min_payment
          AND bs.total_hcpcs_codes <= :max_codes
        ORDER BY bs.total_medicare_payment DESC
        LIMIT :limit OFFSET :offset
    """), {
        "min_payment": min_payment,
        "max_codes": max_codes,
        "limit": per_page,
        "offset": (page - 1) * per_page,
    })

    rows = q.fetchall()

    # Get total count
    count_q = db.execute(text("""
        SELECT COUNT(*) FROM billing_summary bs
        WHERE bs.data_year = (SELECT MAX(data_year) FROM billing_summary)
          AND bs.total_medicare_payment > :min_payment
          AND bs.total_hcpcs_codes <= :max_codes
    """), {"min_payment": min_payment, "max_codes": max_codes})
    total = count_q.scalar()

    # Enrich with NPPES names and HCPCS detail
    results = []
    for row in rows:
        npi = row[0]

        provider = db.get(Provider, npi)
        name, address = resolve_name(npi, provider)

        # Get HCPCS codes for this NPI
        hcpcs = (
            db.query(Billing.hcpcs_code, Billing.hcpcs_description,
                     Billing.total_services, Billing.avg_medicare_payment,
                     Billing.rbcs_category)
            .filter(Billing.npi == npi,
                    Billing.data_year == row[8])
            .order_by(Billing.total_services.desc().nullslast())
            .all()
        )

        results.append({
            "npi": npi,
            "name": name,
            "address": address,
            "total_medicare_payment": float(row[1] or 0),
            "total_beneficiaries": row[2],
            "total_hcpcs_codes": row[3],
            "total_services": float(row[4] or 0),
            "total_submitted_charges": float(row[5] or 0),
            "payment_per_beneficiary": float(row[6] or 0),
            "services_per_beneficiary": float(row[7] or 0),
            "data_year": row[8],
            "hcpcs_detail": [
                {
                    "code": h[0],
                    "description": h[1],
                    "services": float(h[2] or 0),
                    "avg_payment": float(h[3] or 0),
                    "category": h[4],
                }
                for h in hcpcs
            ],
        })

    return {
        "anomaly_type": "code_concentration",
        "description": f"Suppliers billing >${min_payment:,.0f} with {max_codes} or fewer HCPCS codes",
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": results,
    }


@router.get("/anomalies/billing-spikes")
def get_billing_spikes(
    min_growth_pct: float = Query(200, ge=50),
    min_current_payment: float = Query(100000, ge=0),
    min_prior_payment: float = Query(10000, ge=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Suppliers with extreme YoY billing growth.

    Compares most recent year to earliest available year.
    Flags entities that went from small to large billing rapidly.
    """
    q = db.execute(text("""
        WITH years AS (
            SELECT MAX(data_year) as latest, MIN(data_year) as earliest
            FROM billing_summary
        )
        SELECT
            curr.npi,
            prev.total_medicare_payment as prev_payment,
            curr.total_medicare_payment as curr_payment,
            ROUND(((curr.total_medicare_payment - prev.total_medicare_payment)
                   / NULLIF(prev.total_medicare_payment, 0)) * 100) as growth_pct,
            curr.total_hcpcs_codes,
            curr.total_beneficiaries,
            curr.total_services,
            prev.data_year as prev_year,
            curr.data_year as curr_year
        FROM billing_summary curr
        JOIN billing_summary prev ON curr.npi = prev.npi
        CROSS JOIN years
        WHERE curr.data_year = years.latest
          AND prev.data_year = years.earliest
          AND prev.total_medicare_payment > :min_prior
          AND curr.total_medicare_payment > :min_current
          AND ((curr.total_medicare_payment - prev.total_medicare_payment)
               / NULLIF(prev.total_medicare_payment, 0)) > :min_growth
        ORDER BY ((curr.total_medicare_payment - prev.total_medicare_payment)
                  / NULLIF(prev.total_medicare_payment, 0)) DESC
        LIMIT :limit OFFSET :offset
    """), {
        "min_growth": min_growth_pct / 100,
        "min_current": min_current_payment,
        "min_prior": min_prior_payment,
        "limit": per_page,
        "offset": (page - 1) * per_page,
    })

    rows = q.fetchall()

    results = []
    for row in rows:
        npi = row[0]
        provider = db.get(Provider, npi)
        name, address = resolve_name(npi, provider)

        results.append({
            "npi": npi,
            "name": name,
            "address": address,
            "prev_year": row[7],
            "curr_year": row[8],
            "prev_payment": float(row[1] or 0),
            "curr_payment": float(row[2] or 0),
            "growth_pct": float(row[3] or 0),
            "total_hcpcs_codes": row[4],
            "total_beneficiaries": row[5],
            "total_services": float(row[6] or 0),
        })

    return {
        "anomaly_type": "billing_spikes",
        "description": f"Suppliers with >{min_growth_pct:.0f}% billing growth",
        "total": len(results),
        "results": results,
    }


@router.get("/anomalies/volume-outliers")
def get_volume_outliers(
    min_svcs_per_bene: float = Query(50, ge=5),
    min_payment: float = Query(50000, ge=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Suppliers with abnormally high services-per-beneficiary ratios.

    A legitimate DME supplier might deliver 2-10 services per patient per year.
    Ratios of 50+ suggest phantom billing, upcoding, or unbundling.
    """
    q = db.execute(text("""
        SELECT bs.npi,
               bs.total_medicare_payment,
               bs.total_beneficiaries,
               bs.total_services,
               bs.total_hcpcs_codes,
               ROUND(bs.total_services / NULLIF(bs.total_beneficiaries, 0), 1) as svcs_per_bene,
               ROUND(bs.total_medicare_payment / NULLIF(bs.total_beneficiaries, 0), 0) as payment_per_bene,
               bs.data_year
        FROM billing_summary bs
        WHERE bs.data_year = (SELECT MAX(data_year) FROM billing_summary)
          AND bs.total_medicare_payment > :min_payment
          AND bs.total_beneficiaries > 0
          AND (bs.total_services / NULLIF(bs.total_beneficiaries, 0)) > :min_svcs
        ORDER BY (bs.total_services / NULLIF(bs.total_beneficiaries, 0)) DESC
        LIMIT :limit OFFSET :offset
    """), {
        "min_payment": min_payment,
        "min_svcs": min_svcs_per_bene,
        "limit": per_page,
        "offset": (page - 1) * per_page,
    })

    rows = q.fetchall()

    results = []
    for row in rows:
        npi = row[0]
        provider = db.get(Provider, npi)
        results.append({
            "npi": npi,
            "name": provider.org_name if provider else None,
            "total_medicare_payment": float(row[1] or 0),
            "total_beneficiaries": row[2],
            "total_services": float(row[3] or 0),
            "total_hcpcs_codes": row[4],
            "services_per_beneficiary": float(row[5] or 0),
            "payment_per_beneficiary": float(row[6] or 0),
            "data_year": row[7],
        })

    return {
        "anomaly_type": "volume_outliers",
        "description": f"Suppliers with >{min_svcs_per_bene:.0f} services per beneficiary",
        "total": len(results),
        "results": results,
    }


@router.get("/anomalies/high-risk-codes")
def get_high_risk_code_billing(
    min_payment: float = Query(100000, ge=0),
    min_risk_ratio: float = Query(0.5, ge=0, le=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Suppliers with revenue concentrated in historically fraud-prone HCPCS codes.

    L-codes (orthotics/braces) and certain E-codes (glucose monitors, TENS units)
    are disproportionately represented in DOJ healthcare fraud prosecutions.
    """
    # High-risk codes from recent Houston fraud cases
    high_risk = (
        "L1833", "L1851", "L1843", "L1832", "L1844", "L1852",
        "L0648", "L0650", "L0651", "L0631", "L0637",
        "L3761", "L3808", "L3916",
        "E0607", "E2101", "A4253", "A4256", "A4258",
        "E0720", "E0730", "A4595",
        "Q4101", "Q4116", "Q4121", "Q4131", "Q4132", "Q4133",
        "K0823", "K0824", "K0856", "K0861",
    )
    hr_list = ",".join(f"'{c}'" for c in high_risk)

    q = db.execute(text(f"""
        WITH latest AS (
            SELECT MAX(data_year) as yr FROM billing
        ),
        npi_totals AS (
            SELECT npi,
                   SUM(total_services) as total_svcs,
                   SUM(total_services * avg_medicare_payment) as total_revenue
            FROM billing, latest
            WHERE data_year = latest.yr
            GROUP BY npi
        ),
        npi_risk AS (
            SELECT b.npi,
                   SUM(b.total_services) as risk_svcs,
                   SUM(b.total_services * b.avg_medicare_payment) as risk_revenue
            FROM billing b, latest
            WHERE b.data_year = latest.yr
              AND b.hcpcs_code IN ({hr_list})
            GROUP BY b.npi
        )
        SELECT t.npi,
               t.total_revenue,
               COALESCE(r.risk_revenue, 0) as risk_revenue,
               ROUND((COALESCE(r.risk_revenue, 0) / NULLIF(t.total_revenue, 0))::numeric, 3) as risk_ratio,
               t.total_svcs,
               COALESCE(r.risk_svcs, 0) as risk_svcs,
               bs.total_beneficiaries,
               bs.total_hcpcs_codes
        FROM npi_totals t
        JOIN billing_summary bs ON bs.npi = t.npi AND bs.data_year = (SELECT yr FROM latest)
        LEFT JOIN npi_risk r ON r.npi = t.npi
        WHERE t.total_revenue > :min_payment
          AND (COALESCE(r.risk_revenue, 0) / NULLIF(t.total_revenue, 0)) > :min_ratio
        ORDER BY risk_revenue DESC
        LIMIT :limit OFFSET :offset
    """), {
        "min_payment": min_payment,
        "min_ratio": min_risk_ratio,
        "limit": per_page,
        "offset": (page - 1) * per_page,
    })

    rows = q.fetchall()

    results = []
    for row in rows:
        npi = row[0]
        provider = db.get(Provider, npi)

        # Get the specific high-risk codes they're billing
        risk_codes = (
            db.query(Billing.hcpcs_code, Billing.hcpcs_description,
                     Billing.total_services, Billing.avg_medicare_payment)
            .filter(
                Billing.npi == npi,
                Billing.hcpcs_code.in_(high_risk),
                Billing.data_year == db.execute(
                    text("SELECT MAX(data_year) FROM billing")
                ).scalar(),
            )
            .order_by(Billing.total_services.desc().nullslast())
            .all()
        )

        results.append({
            "npi": npi,
            "name": provider.org_name if provider else None,
            "address": (
                f"{provider.practice_address_1}, {provider.practice_city}, "
                f"{provider.practice_state} {provider.practice_zip}"
                if provider else None
            ),
            "total_revenue": float(row[1] or 0),
            "high_risk_revenue": float(row[2] or 0),
            "risk_ratio": float(row[3] or 0),
            "total_services": float(row[4] or 0),
            "high_risk_services": float(row[5] or 0),
            "total_beneficiaries": row[6],
            "total_hcpcs_codes": row[7],
            "high_risk_codes": [
                {
                    "code": c[0],
                    "description": c[1],
                    "services": float(c[2] or 0),
                    "avg_payment": float(c[3] or 0),
                }
                for c in risk_codes
            ],
        })

    return {
        "anomaly_type": "high_risk_codes",
        "description": f"Suppliers with >{min_risk_ratio*100:.0f}% revenue from fraud-prone HCPCS codes",
        "total": len(results),
        "results": results,
    }


@router.get("/anomalies/summary")
def get_anomaly_summary(db: Session = Depends(get_db)):
    """Overview counts of each anomaly type for the dashboard."""
    latest_year = db.execute(
        text("SELECT MAX(data_year) FROM billing_summary")
    ).scalar()

    if not latest_year:
        return {"latest_year": None, "anomaly_counts": {}}

    code_conc = db.execute(text("""
        SELECT COUNT(*) FROM billing_summary
        WHERE data_year = :yr AND total_medicare_payment > 100000
          AND total_hcpcs_codes <= 5
    """), {"yr": latest_year}).scalar()

    vol_outliers = db.execute(text("""
        SELECT COUNT(*) FROM billing_summary
        WHERE data_year = :yr AND total_medicare_payment > 50000
          AND total_beneficiaries > 0
          AND (total_services / NULLIF(total_beneficiaries, 0)) > 50
    """), {"yr": latest_year}).scalar()

    spikes = db.execute(text("""
        WITH years AS (
            SELECT MAX(data_year) as latest, MIN(data_year) as earliest
            FROM billing_summary
        )
        SELECT COUNT(*) FROM billing_summary curr
        JOIN billing_summary prev ON curr.npi = prev.npi
        CROSS JOIN years
        WHERE curr.data_year = years.latest AND prev.data_year = years.earliest
          AND prev.total_medicare_payment > 10000
          AND curr.total_medicare_payment > 100000
          AND ((curr.total_medicare_payment - prev.total_medicare_payment)
               / NULLIF(prev.total_medicare_payment, 0)) > 2
    """)).scalar()

    total_billing = db.execute(text("""
        SELECT COUNT(DISTINCT npi), SUM(total_medicare_payment)
        FROM billing_summary WHERE data_year = :yr
    """), {"yr": latest_year}).fetchone()

    return {
        "latest_year": latest_year,
        "total_suppliers": total_billing[0],
        "total_medicare_payment": float(total_billing[1] or 0),
        "anomaly_counts": {
            "code_concentration": code_conc,
            "volume_outliers": vol_outliers,
            "billing_spikes": spikes,
        },
    }


@router.get("/anomalies/investigate/{npi}")
def investigate_entity(npi: str, db: Session = Depends(get_db)):
    """Full investigative case file for a single entity.

    Assembles everything we know into one view:
    - Entity identity (name, address, registration date, taxonomy)
    - Billing history across all years with YoY changes
    - HCPCS code breakdown with fraud-risk flags
    - Peer comparison (vs same ZIP and statewide medians)
    - Red flags summary (plain English)
    - Co-located entities at same address (if in our provider DB)
    """
    # 1. Entity identity — local DB first, NPPES API fallback
    provider = db.get(Provider, npi)
    if provider:
        identity = {
            "npi": npi,
            "name": provider.org_name or f"{provider.last_name}, {provider.first_name}",
            "address": f"{provider.practice_address_1}, {provider.practice_city}, {provider.practice_state} {provider.practice_zip}",
            "city": provider.practice_city,
            "state": provider.practice_state,
            "zip": (provider.practice_zip or "")[:5],
            "enumeration_date": str(provider.enumeration_date) if provider.enumeration_date else None,
            "deactivation_date": str(provider.deactivation_date) if provider.deactivation_date else None,
            "taxonomy": provider.taxonomy_desc,
            "entity_type": "individual" if provider.entity_type == 1 else "organization",
            "source": "local_db",
        }
    else:
        info = lookup_npi(npi)
        identity = {
            "npi": npi,
            "name": info["name"],
            "address": info["address"],
            "city": info["city"],
            "state": info["state"],
            "zip": info["zip"],
            "enumeration_date": info["enumeration_date"],
            "deactivation_date": info["deactivation_date"],
            "taxonomy": info["taxonomy"],
            "entity_type": info["entity_type"],
            "source": "nppes_api",
        }

    # 2. Billing history
    summaries = (
        db.query(BillingSummary)
        .filter(BillingSummary.npi == npi)
        .order_by(BillingSummary.data_year)
        .all()
    )

    billing_history = []
    for s in summaries:
        billing_history.append({
            "year": s.data_year,
            "total_medicare_payment": float(s.total_medicare_payment or 0),
            "total_submitted_charges": float(s.total_submitted_charges or 0),
            "total_beneficiaries": s.total_beneficiaries,
            "total_claims": s.total_claims,
            "total_services": float(s.total_services or 0),
            "total_hcpcs_codes": s.total_hcpcs_codes,
            "dme_medicare_payment": float(s.dme_medicare_payment or 0),
            "pos_medicare_payment": float(s.pos_medicare_payment or 0),
        })

    # YoY growth
    yoy_growth = None
    if len(summaries) >= 2:
        prev = float(summaries[0].total_medicare_payment or 0)
        curr = float(summaries[-1].total_medicare_payment or 0)
        if prev > 0:
            yoy_growth = {
                "from_year": summaries[0].data_year,
                "to_year": summaries[-1].data_year,
                "from_amount": prev,
                "to_amount": curr,
                "growth_pct": round(((curr - prev) / prev) * 100, 1),
            }

    # 3. HCPCS detail (latest year)
    latest_year = summaries[-1].data_year if summaries else None
    hcpcs_detail = []
    high_risk_hcpcs = set()
    FRAUD_CODES = {
        "L1833", "L1851", "L1843", "L1832", "L1844", "L1852",
        "L0648", "L0650", "L0651", "L0631", "L0637",
        "L3761", "L3808", "L3916",
        "E0607", "E2101", "A4253", "A4256", "A4258",
        "E0720", "E0730", "A4595",
        "Q4101", "Q4116", "Q4121", "Q4131", "Q4132", "Q4133",
        "K0823", "K0824", "K0856", "K0861",
    }

    if latest_year:
        lines = (
            db.query(Billing)
            .filter(Billing.npi == npi, Billing.data_year == latest_year)
            .order_by(Billing.total_services.desc().nullslast())
            .all()
        )
        for b in lines:
            is_fraud_code = b.hcpcs_code in FRAUD_CODES
            if is_fraud_code:
                high_risk_hcpcs.add(b.hcpcs_code)
            hcpcs_detail.append({
                "code": b.hcpcs_code,
                "description": b.hcpcs_description,
                "category": b.rbcs_category,
                "beneficiaries": b.total_beneficiaries,
                "claims": b.total_claims,
                "services": float(b.total_services or 0),
                "avg_charge": float(b.avg_submitted_charge or 0),
                "avg_payment": float(b.avg_medicare_payment or 0),
                "is_rental": b.is_rental,
                "fraud_risk_code": is_fraud_code,
            })

    # 4. Peer comparison
    peer_comparison = None
    if summaries and identity.get("zip"):
        zip5 = identity["zip"]
        latest = summaries[-1]
        my_payment = float(latest.total_medicare_payment or 0)

        # ZIP-level peers
        zip_payments = db.execute(text("""
            SELECT total_medicare_payment FROM billing_summary bs
            JOIN providers p ON p.npi = bs.npi
            WHERE p.practice_zip LIKE :zip_prefix
            AND bs.data_year = :yr AND bs.total_medicare_payment > 0
            ORDER BY bs.total_medicare_payment
        """), {"zip_prefix": f"{zip5}%", "yr": latest.data_year}).fetchall()

        # Statewide peers
        state_payments = db.execute(text("""
            SELECT total_medicare_payment FROM billing_summary
            WHERE data_year = :yr AND total_medicare_payment > 0
            ORDER BY total_medicare_payment
        """), {"yr": latest.data_year}).fetchall()

        zip_vals = [float(r[0]) for r in zip_payments] if zip_payments else []
        state_vals = [float(r[0]) for r in state_payments] if state_payments else []

        zip_median = zip_vals[len(zip_vals)//2] if zip_vals else None
        state_median = state_vals[len(state_vals)//2] if state_vals else None

        peer_comparison = {
            "entity_payment": my_payment,
            "zip_median": zip_median,
            "zip_ratio": round(my_payment / zip_median, 1) if zip_median else None,
            "zip_peer_count": len(zip_vals),
            "state_median": state_median,
            "state_ratio": round(my_payment / state_median, 1) if state_median else None,
            "state_peer_count": len(state_vals),
            "state_percentile": round(
                sum(1 for v in state_vals if v <= my_payment) / len(state_vals) * 100, 1
            ) if state_vals else None,
        }

    # 5. Red flags — plain English summary
    red_flags = []

    if summaries:
        latest = summaries[-1]
        payment = float(latest.total_medicare_payment or 0)
        codes = latest.total_hcpcs_codes or 0
        benes = latest.total_beneficiaries or 0
        services = float(latest.total_services or 0)

        if codes <= 3 and payment > 100000:
            red_flags.append({
                "severity": "critical",
                "flag": f"Billing ${payment:,.0f} from only {codes} HCPCS code{'s' if codes != 1 else ''}",
                "detail": "Legitimate suppliers typically bill across many codes. Extreme concentration suggests scheme billing.",
            })
        elif codes <= 5 and payment > 100000:
            red_flags.append({
                "severity": "high",
                "flag": f"Billing ${payment:,.0f} from only {codes} HCPCS codes",
                "detail": "Low code diversity relative to billing volume.",
            })

        if benes > 0 and services / benes > 100:
            red_flags.append({
                "severity": "critical",
                "flag": f"{services/benes:.0f} services per beneficiary",
                "detail": "Normal DME is 2-10 services per patient. This ratio suggests phantom billing or unbundling.",
            })
        elif benes > 0 and services / benes > 50:
            red_flags.append({
                "severity": "high",
                "flag": f"{services/benes:.0f} services per beneficiary",
                "detail": "Significantly above normal service volume per patient.",
            })

        if yoy_growth and yoy_growth["growth_pct"] > 500:
            red_flags.append({
                "severity": "critical",
                "flag": f"{yoy_growth['growth_pct']:,.0f}% billing growth ({yoy_growth['from_year']}-{yoy_growth['to_year']})",
                "detail": f"From ${yoy_growth['from_amount']:,.0f} to ${yoy_growth['to_amount']:,.0f}. Rapid ramp is a hallmark of fraud schemes.",
            })
        elif yoy_growth and yoy_growth["growth_pct"] > 200:
            red_flags.append({
                "severity": "high",
                "flag": f"{yoy_growth['growth_pct']:,.0f}% billing growth ({yoy_growth['from_year']}-{yoy_growth['to_year']})",
                "detail": f"From ${yoy_growth['from_amount']:,.0f} to ${yoy_growth['to_amount']:,.0f}.",
            })

    if high_risk_hcpcs:
        red_flags.append({
            "severity": "high",
            "flag": f"Billing fraud-associated HCPCS codes: {', '.join(sorted(high_risk_hcpcs))}",
            "detail": "These codes appear disproportionately in DOJ healthcare fraud prosecutions (orthotic braces, glucose monitors, etc.).",
        })

    if identity.get("enumeration_date"):
        from datetime import datetime
        try:
            enum_date = datetime.strptime(identity["enumeration_date"], "%m/%d/%Y")
            age_days = (datetime.now() - enum_date).days
            if age_days < 730 and summaries and float(summaries[-1].total_medicare_payment or 0) > 500000:
                red_flags.append({
                    "severity": "high",
                    "flag": f"Entity registered {identity['enumeration_date']} — less than 2 years old with ${float(summaries[-1].total_medicare_payment or 0):,.0f} in billing",
                    "detail": "New entities billing large amounts quickly is a common fraud pattern.",
                })
        except ValueError:
            pass

    if identity.get("name") and identity["entity_type"] == "organization":
        name_upper = identity["name"].upper()
        medical_keywords = {"MEDICAL", "HEALTH", "DME", "DURABLE", "SUPPLY", "HOSPICE", "HOME", "CARE", "PHARMACY", "ORTHO"}
        if not any(kw in name_upper for kw in medical_keywords):
            red_flags.append({
                "severity": "medium",
                "flag": f"Non-medical entity name: \"{identity['name']}\"",
                "detail": "Entity name does not contain healthcare-related keywords but is registered as a medical supplier.",
            })

    if peer_comparison and peer_comparison.get("state_percentile") and peer_comparison["state_percentile"] > 99:
        red_flags.append({
            "severity": "high",
            "flag": f"Top {100 - peer_comparison['state_percentile']:.1f}% of all TX DMEPOS suppliers by billing",
            "detail": f"${peer_comparison['entity_payment']:,.0f} vs state median of ${peer_comparison['state_median']:,.0f} ({peer_comparison['state_ratio']}x).",
        })

    red_flags.sort(key=lambda f: {"critical": 0, "high": 1, "medium": 2}.get(f["severity"], 3))

    return {
        "identity": identity,
        "billing_history": billing_history,
        "yoy_growth": yoy_growth,
        "hcpcs_detail": hcpcs_detail,
        "peer_comparison": peer_comparison,
        "red_flags": red_flags,
        "red_flag_count": {
            "critical": sum(1 for f in red_flags if f["severity"] == "critical"),
            "high": sum(1 for f in red_flags if f["severity"] == "high"),
            "medium": sum(1 for f in red_flags if f["severity"] == "medium"),
        },
    }
