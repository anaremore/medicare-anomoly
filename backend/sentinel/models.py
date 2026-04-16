from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel.db import Base


class Provider(Base):
    __tablename__ = "providers"

    npi: Mapped[str] = mapped_column(String(10), primary_key=True)
    entity_type: Mapped[int] = mapped_column(Integer)  # 1=individual, 2=org
    org_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    taxonomy_code: Mapped[str | None] = mapped_column(String(20))
    taxonomy_desc: Mapped[str | None] = mapped_column(Text)
    enumeration_date: Mapped[date | None] = mapped_column(Date)
    deactivation_date: Mapped[date | None] = mapped_column(Date)
    reactivation_date: Mapped[date | None] = mapped_column(Date)
    practice_address_1: Mapped[str | None] = mapped_column(Text)
    practice_address_2: Mapped[str | None] = mapped_column(Text)
    practice_city: Mapped[str | None] = mapped_column(Text)
    practice_state: Mapped[str | None] = mapped_column(String(2))
    practice_zip: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    risk_score: Mapped["RiskScore | None"] = relationship(back_populates="provider")
    address_links: Mapped[list["ProviderAddress"]] = relationship(
        back_populates="provider"
    )

    __table_args__ = (
        Index("idx_providers_zip", "practice_zip"),
        Index("idx_providers_taxonomy", "taxonomy_code"),
        Index("idx_providers_enum_date", "enumeration_date"),
    )


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_address: Mapped[str | None] = mapped_column(Text)
    normalized_address: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(2))
    zip: Mapped[str] = mapped_column(String(5))
    lat: Mapped[float | None] = mapped_column(Numeric(10, 7))
    lng: Mapped[float | None] = mapped_column(Numeric(10, 7))
    geom: Mapped[str | None] = mapped_column(Geometry("POINT", srid=4326))

    provider_links: Mapped[list["ProviderAddress"]] = relationship(
        back_populates="address"
    )

    __table_args__ = (
        Index(
            "uq_address_normalized",
            "normalized_address",
            "city",
            "state",
            "zip",
            unique=True,
        ),
    )


class ProviderAddress(Base):
    __tablename__ = "provider_addresses"

    provider_npi: Mapped[str] = mapped_column(
        String(10), ForeignKey("providers.npi"), primary_key=True
    )
    address_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("addresses.id"), primary_key=True
    )
    address_purpose: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )  # LOCATION, MAILING
    first_seen: Mapped[date | None] = mapped_column(Date)
    last_seen: Mapped[date | None] = mapped_column(Date)

    provider: Mapped["Provider"] = relationship(back_populates="address_links")
    address: Mapped["Address"] = relationship(back_populates="provider_links")


class Exclusion(Base):
    __tablename__ = "exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_name: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str | None] = mapped_column(Text)
    mid_name: Mapped[str | None] = mapped_column(Text)
    bus_name: Mapped[str | None] = mapped_column(Text)
    general_type: Mapped[str | None] = mapped_column(Text)
    specialty: Mapped[str | None] = mapped_column(Text)
    npi: Mapped[str | None] = mapped_column(String(10))
    dob: Mapped[date | None] = mapped_column(Date)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(String(2))
    zip: Mapped[str | None] = mapped_column(String(10))
    exclusion_type: Mapped[str | None] = mapped_column(String(20))
    exclusion_date: Mapped[date | None] = mapped_column(Date)
    reinstatement_date: Mapped[date | None] = mapped_column(Date)
    waiver_date: Mapped[date | None] = mapped_column(Date)
    waiver_state: Mapped[str | None] = mapped_column(String(2))

    __table_args__ = (
        Index("idx_exclusions_npi", "npi"),
        Index("idx_exclusions_city_state", "city", "state"),
    )


class Billing(Base):
    __tablename__ = "billing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    npi: Mapped[str] = mapped_column(String(10), index=True)
    hcpcs_code: Mapped[str | None] = mapped_column(String(10))
    hcpcs_description: Mapped[str | None] = mapped_column(Text)
    rbcs_category: Mapped[str | None] = mapped_column(Text)
    total_beneficiaries: Mapped[int | None] = mapped_column(Integer)
    total_claims: Mapped[int | None] = mapped_column(Integer)
    total_services: Mapped[float | None] = mapped_column(Numeric(14, 2))
    avg_submitted_charge: Mapped[float | None] = mapped_column(Numeric(14, 2))
    avg_medicare_allowed: Mapped[float | None] = mapped_column(Numeric(14, 2))
    avg_medicare_payment: Mapped[float | None] = mapped_column(Numeric(14, 2))
    is_rental: Mapped[bool | None] = mapped_column(Boolean)
    data_year: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30))  # dmepos_supplier, physician

    __table_args__ = (
        Index("idx_billing_npi_year", "npi", "data_year"),
        Index("idx_billing_hcpcs", "hcpcs_code"),
    )


class BillingSummary(Base):
    """Aggregated billing per NPI per year from the 'by Supplier' dataset."""
    __tablename__ = "billing_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    npi: Mapped[str] = mapped_column(String(10), index=True)
    total_hcpcs_codes: Mapped[int | None] = mapped_column(Integer)
    total_beneficiaries: Mapped[int | None] = mapped_column(Integer)
    total_claims: Mapped[int | None] = mapped_column(Integer)
    total_services: Mapped[float | None] = mapped_column(Numeric(14, 2))
    total_submitted_charges: Mapped[float | None] = mapped_column(Numeric(14, 2))
    total_medicare_allowed: Mapped[float | None] = mapped_column(Numeric(14, 2))
    total_medicare_payment: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # DME-specific subtotals
    dme_total_services: Mapped[float | None] = mapped_column(Numeric(14, 2))
    dme_submitted_charges: Mapped[float | None] = mapped_column(Numeric(14, 2))
    dme_medicare_payment: Mapped[float | None] = mapped_column(Numeric(14, 2))
    # POS (Prosthetics/Orthotics/Supplies) subtotals
    pos_total_services: Mapped[float | None] = mapped_column(Numeric(14, 2))
    pos_submitted_charges: Mapped[float | None] = mapped_column(Numeric(14, 2))
    pos_medicare_payment: Mapped[float | None] = mapped_column(Numeric(14, 2))
    data_year: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("uq_billing_summary_npi_year", "npi", "data_year", unique=True),
    )


class RiskScore(Base):
    __tablename__ = "risk_scores"

    npi: Mapped[str] = mapped_column(
        String(10), ForeignKey("providers.npi"), primary_key=True
    )
    address_clustering_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    entity_profile_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    network_association_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    geographic_risk_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    billing_velocity_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    composite_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    signals: Mapped[dict | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    provider: Mapped["Provider"] = relationship(back_populates="risk_score")

    __table_args__ = (
        Index("idx_risk_composite", "composite_score"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(String(50))
    npi: Mapped[str | None] = mapped_column(String(10))
    address_id: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(10))  # low, medium, high, critical
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("idx_alerts_severity", "severity", "created_at"),
    )
