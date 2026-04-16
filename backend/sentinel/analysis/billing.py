"""Billing velocity and anomaly analysis.

Detects:
- Billing ramp rates (YoY growth)
- Zero-to-high-billing patterns (new entities billing large amounts)
- Peer outliers (billing far above median for same ZIP/taxonomy)
- High-risk HCPCS code concentration
- Low code diversity (billing 95%+ from 1-2 codes)
"""

import logging
import math
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import Billing, BillingSummary, Provider

logger = logging.getLogger(__name__)

TAXONOMY_CODES = [settings.dme_taxonomy, settings.hha_taxonomy, settings.hospice_taxonomy]

# HCPCS codes historically associated with fraud schemes
# Orthotic braces, glucose monitors, genetic testing, skin substitutes
HIGH_RISK_HCPCS = {
    # Orthotic braces (Buzolin/Verisola $400M scheme)
    "L1833", "L1851", "L1843", "L1832", "L1844",
    "L0648", "L0650", "L0631", "L0637",
    # Glucose monitors
    "E0607", "E2101", "A4253", "A4256", "A4258",
    # TENS units (common DME fraud item)
    "E0720", "E0730", "A4595",
    # Skin substitutes (Jenson $90M Spring TX)
    "Q4101", "Q4116", "Q4121", "Q4131", "Q4132", "Q4133",
    # Power wheelchairs (historical Houston fraud)
    "K0823", "K0824", "K0856", "K0861",
}


def compute_billing_velocity_score(
    db: Session, npi: str
) -> tuple[float, dict]:
    """Compute billing velocity risk score for a single provider.

    Components:
    - YoY billing growth rate (max 25 points)
    - Absolute billing volume vs. peer median (max 25 points)
    - High-risk HCPCS concentration (max 20 points)
    - Code diversity (max 15 points)
    - Services-per-beneficiary ratio (max 15 points)

    Returns (score 0-100, signal breakdown dict).
    """
    signals = {}
    score = 0.0

    # Get billing summaries across years
    summaries = (
        db.query(BillingSummary)
        .filter(BillingSummary.npi == npi)
        .order_by(BillingSummary.data_year)
        .all()
    )

    if not summaries:
        # No CMS billing data — this is itself a signal for established entities.
        # A provider registered 2+ years ago with no billing data in CMS may be
        # a phantom entity or billing under the 10-claim privacy threshold.
        provider = db.get(Provider, npi)
        if provider and provider.enumeration_date:
            from datetime import date
            age_days = (date.today() - provider.enumeration_date).days
            if age_days > 730:  # 2+ years old, no billing
                return 10.0, {
                    "has_billing_data": False,
                    "entity_age_days": age_days,
                    "note": "Registered 2+ years with no CMS billing data",
                }
        return 0.0, {"has_billing_data": False}

    signals["has_billing_data"] = True
    latest = summaries[-1]
    signals["latest_year"] = latest.data_year
    signals["total_medicare_payment"] = float(latest.total_medicare_payment or 0)
    signals["total_beneficiaries"] = latest.total_beneficiaries or 0
    signals["total_claims"] = latest.total_claims or 0

    # --- 1. YoY billing growth (max 25 points) ---
    if len(summaries) >= 2:
        prev = summaries[-2]
        prev_payment = float(prev.total_medicare_payment or 0)
        curr_payment = float(latest.total_medicare_payment or 0)

        if prev_payment > 0:
            growth_rate = (curr_payment - prev_payment) / prev_payment
            signals["yoy_growth_rate"] = round(growth_rate, 2)
            signals["prev_year_payment"] = prev_payment

            if growth_rate > 5.0:  # 500%+ growth
                growth_score = 25.0
            elif growth_rate > 3.0:  # 300%+ growth
                growth_score = 20.0
            elif growth_rate > 1.0:  # 100%+ growth
                growth_score = 10.0
            elif growth_rate > 0.5:  # 50%+ growth
                growth_score = 5.0
            else:
                growth_score = 0.0
        elif curr_payment > 100000:
            # No prior year, but high current billing (zero-to-big)
            growth_score = 25.0
            signals["zero_to_big"] = True
        else:
            growth_score = 0.0

        signals["growth_score"] = growth_score
        score += growth_score

    # --- 2. Peer comparison — billing vs. ZIP median (max 25 points) ---
    provider = db.get(Provider, npi)
    if provider and provider.practice_zip:
        zip5 = provider.practice_zip[:5]

        # Get median billing for same ZIP
        peer_payments = (
            db.query(BillingSummary.total_medicare_payment)
            .join(Provider, Provider.npi == BillingSummary.npi)
            .filter(
                Provider.practice_zip.startswith(zip5),
                BillingSummary.data_year == latest.data_year,
                BillingSummary.total_medicare_payment > 0,
            )
            .all()
        )

        if peer_payments:
            values = sorted([float(p[0]) for p in peer_payments if p[0]])
            median_idx = len(values) // 2
            median_payment = values[median_idx] if values else 0
            my_payment = float(latest.total_medicare_payment or 0)

            if median_payment > 0:
                peer_ratio = my_payment / median_payment
                signals["zip_median_payment"] = round(median_payment, 2)
                signals["peer_ratio"] = round(peer_ratio, 2)
                signals["zip_peer_count"] = len(values)

                if peer_ratio > 10:
                    peer_score = 25.0
                elif peer_ratio > 5:
                    peer_score = 20.0
                elif peer_ratio > 3:
                    peer_score = 15.0
                elif peer_ratio > 2:
                    peer_score = 5.0
                else:
                    peer_score = 0.0

                signals["peer_score"] = peer_score
                score += peer_score

    # --- 3. High-risk HCPCS concentration (max 20 points) ---
    billing_lines = (
        db.query(Billing)
        .filter(Billing.npi == npi, Billing.data_year == latest.data_year)
        .all()
    )

    if billing_lines:
        total_line_services = sum(
            float(b.total_services or 0) for b in billing_lines
        )
        high_risk_services = sum(
            float(b.total_services or 0)
            for b in billing_lines
            if b.hcpcs_code in HIGH_RISK_HCPCS
        )

        if total_line_services > 0:
            hr_ratio = high_risk_services / total_line_services
            signals["high_risk_hcpcs_ratio"] = round(hr_ratio, 3)
            signals["high_risk_hcpcs_codes"] = [
                b.hcpcs_code for b in billing_lines if b.hcpcs_code in HIGH_RISK_HCPCS
            ]

            if hr_ratio > 0.8:
                hr_score = 20.0
            elif hr_ratio > 0.5:
                hr_score = 12.0
            elif hr_ratio > 0.3:
                hr_score = 5.0
            else:
                hr_score = 0.0

            signals["hcpcs_risk_score"] = hr_score
            score += hr_score

        # --- 4. Code diversity (max 15 points) ---
        unique_codes = len(set(b.hcpcs_code for b in billing_lines if b.hcpcs_code))
        signals["unique_hcpcs_codes"] = unique_codes

        if unique_codes <= 1 and total_line_services > 100:
            diversity_score = 15.0
        elif unique_codes <= 2 and total_line_services > 100:
            diversity_score = 10.0
        elif unique_codes <= 3 and total_line_services > 50:
            diversity_score = 5.0
        else:
            diversity_score = 0.0

        signals["diversity_score"] = diversity_score
        score += diversity_score

    # --- 5. Services-per-beneficiary ratio (max 15 points) ---
    benes = latest.total_beneficiaries or 0
    services = float(latest.total_services or 0)

    if benes > 0:
        spb_ratio = services / benes
        signals["services_per_beneficiary"] = round(spb_ratio, 2)

        if spb_ratio > 20:  # 20+ services per beneficiary
            spb_score = 15.0
        elif spb_ratio > 10:
            spb_score = 10.0
        elif spb_ratio > 5:
            spb_score = 5.0
        else:
            spb_score = 0.0

        signals["spb_score"] = spb_score
        score += spb_score

    return round(min(100.0, score), 1), signals
