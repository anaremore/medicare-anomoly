"""Billing anomaly detection endpoints.

Surfaces the most suspicious billing patterns across all providers:
- Code concentration: High billing with very few HCPCS codes
- Billing spikes: Extreme YoY growth rates
- Volume outliers: Services-per-beneficiary far above normal
- High-risk code dominance: Revenue concentrated in fraud-prone L/E codes
- New entity ramp: Young entities billing large amounts quickly
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text, case, literal_column
from sqlalchemy.orm import Session

from sentinel.db import get_db
from sentinel.models import Billing, BillingSummary, Provider

router = APIRouter(tags=["anomalies"])


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

        # Get provider name from our DB or HCPCS detail
        provider = db.get(Provider, npi)

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
            "name": provider.org_name if provider else None,
            "address": (
                f"{provider.practice_address_1}, {provider.practice_city}, "
                f"{provider.practice_state} {provider.practice_zip}"
                if provider else None
            ),
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

        results.append({
            "npi": npi,
            "name": provider.org_name if provider else None,
            "address": (
                f"{provider.practice_address_1}, {provider.practice_city}, "
                f"{provider.practice_state} {provider.practice_zip}"
                if provider else None
            ),
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
