"""NPPES NPI Registry API ingestion.

Queries the NPPES API for DME, HHA, and hospice providers in the Houston area,
then upserts results into the providers table.
"""

import logging
from datetime import date, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from sentinel.config import settings
from sentinel.models import Address, Provider, ProviderAddress
from sentinel.etl.geocode import normalize_address

logger = logging.getLogger(__name__)

TAXONOMY_CODES = [
    settings.dme_taxonomy,   # 332B00000X — DME supplier
    settings.hha_taxonomy,   # 251E00000X — Home health agency
    settings.hospice_taxonomy,  # 251G00000X — Hospice
]


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_nppes_page(
    taxonomy: str,
    city: str = "HOUSTON",
    state: str = "TX",
    skip: int = 0,
    limit: int = 200,
) -> dict:
    """Fetch one page of results from the NPPES API."""
    params = {
        "version": "2.1",
        "taxonomy_description": "",
        "city": city,
        "state": state,
        "limit": limit,
        "skip": skip,
    }
    # The NPPES API uses taxonomy_description for text search,
    # but we need exact code matching. Use the enumeration_type + postal_code approach
    # or just pass taxonomy_description and filter.
    # Actually, the API does not support taxonomy_code directly.
    # We'll search by city/state and filter by taxonomy in post-processing,
    # OR we can use the taxonomy_description text.
    #
    # Better approach: search by zip code + limit, which is more targeted.
    # We'll iterate over zip codes.
    response = httpx.get(
        settings.nppes_api_url,
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


TAXONOMY_DESCRIPTIONS = [
    "Suppliers/Durable Medical Equipment",
    "Home Health",
    "Hospice Care",
]


def fetch_by_zip_taxonomy(
    zip_code: str,
    taxonomy_desc: str,
    limit: int = 200,
    skip: int = 0,
) -> dict:
    """Fetch providers by ZIP code and taxonomy description."""
    params = {
        "version": "2.1",
        "postal_code": zip_code,
        "taxonomy_description": taxonomy_desc,
        "limit": limit,
        "skip": skip,
    }
    response = httpx.get(
        settings.nppes_api_url,
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def fetch_all_for_zip(zip_code: str) -> list[dict]:
    """Fetch target-taxonomy providers in a ZIP code, paginating."""
    all_results = []
    for tax_desc in TAXONOMY_DESCRIPTIONS:
        skip = 0
        while True:
            data = fetch_by_zip_taxonomy(zip_code, tax_desc, skip=skip)
            result_count = data.get("result_count", 0)
            if result_count == 0:
                break
            results = data.get("results", [])
            all_results.extend(results)
            if len(results) < 200:
                break
            skip += 200
    return all_results


def extract_taxonomy(result: dict) -> tuple[str | None, str | None]:
    """Extract primary taxonomy code and description from NPPES result."""
    taxonomies = result.get("taxonomies", [])
    # Prefer the primary taxonomy
    for t in taxonomies:
        if t.get("primary", False):
            return t.get("code"), t.get("desc")
    if taxonomies:
        return taxonomies[0].get("code"), taxonomies[0].get("desc")
    return None, None


def is_target_taxonomy(result: dict) -> bool:
    """Check if provider has a target taxonomy (DME, HHA, or Hospice)."""
    taxonomies = result.get("taxonomies", [])
    for t in taxonomies:
        if t.get("code") in TAXONOMY_CODES:
            return True
    return False


def extract_practice_address(result: dict) -> dict | None:
    """Extract the practice location address from NPPES result."""
    addresses = result.get("addresses", [])
    for addr in addresses:
        if addr.get("address_purpose") == "LOCATION":
            return addr
    # Fall back to first address
    return addresses[0] if addresses else None


def upsert_provider(db: Session, result: dict) -> Provider | None:
    """Create or update a provider record from NPPES API result."""
    npi = result.get("number")
    if not npi:
        return None

    tax_code, tax_desc = extract_taxonomy(result)
    addr = extract_practice_address(result)

    basic = result.get("basic", {})
    entity_type = 1 if result.get("enumeration_type") == "NPI-1" else 2

    provider = db.get(Provider, str(npi))
    if provider is None:
        provider = Provider(npi=str(npi))
        db.add(provider)

    provider.entity_type = entity_type
    provider.org_name = basic.get("organization_name")
    provider.last_name = basic.get("last_name")
    provider.first_name = basic.get("first_name")
    provider.taxonomy_code = tax_code
    provider.taxonomy_desc = tax_desc
    provider.enumeration_date = parse_date(basic.get("enumeration_date"))
    provider.deactivation_date = parse_date(basic.get("deactivation_date"))
    provider.reactivation_date = parse_date(basic.get("reactivation_date"))

    if addr:
        provider.practice_address_1 = addr.get("address_1")
        provider.practice_address_2 = addr.get("address_2")
        provider.practice_city = addr.get("city")
        provider.practice_state = addr.get("state")
        provider.practice_zip = addr.get("postal_code", "")[:10]

    return provider


def upsert_address_link(db: Session, provider: Provider) -> Address | None:
    """Create or update the normalized address and link it to the provider."""
    if not provider.practice_address_1 or not provider.practice_city:
        return None

    norm = normalize_address(
        provider.practice_address_1,
        provider.practice_address_2,
    )
    city = provider.practice_city.upper().strip()
    state = (provider.practice_state or "TX").upper().strip()
    zip5 = (provider.practice_zip or "")[:5]

    # Find or create address
    address = (
        db.query(Address)
        .filter(
            Address.normalized_address == norm,
            Address.city == city,
            Address.state == state,
            Address.zip == zip5,
        )
        .first()
    )
    if address is None:
        address = Address(
            raw_address=provider.practice_address_1,
            normalized_address=norm,
            city=city,
            state=state,
            zip=zip5,
        )
        db.add(address)
        db.flush()  # Get the ID

    # Create or update the link
    link = (
        db.query(ProviderAddress)
        .filter(
            ProviderAddress.provider_npi == provider.npi,
            ProviderAddress.address_id == address.id,
            ProviderAddress.address_purpose == "LOCATION",
        )
        .first()
    )
    if link is None:
        link = ProviderAddress(
            provider_npi=provider.npi,
            address_id=address.id,
            address_purpose="LOCATION",
            first_seen=date.today(),
            last_seen=date.today(),
        )
        db.add(link)
    else:
        link.last_seen = date.today()

    return address


def ingest_zip(db: Session, zip_code: str) -> int:
    """Ingest all target-taxonomy providers for a single ZIP code."""
    results = fetch_all_for_zip(zip_code)
    count = 0
    for result in results:
        if not is_target_taxonomy(result):
            continue
        provider = upsert_provider(db, result)
        if provider:
            upsert_address_link(db, provider)
            count += 1
    db.commit()
    return count


def ingest_houston(db: Session) -> int:
    """Ingest all target-taxonomy providers for the Houston metro area."""
    total = 0
    for zip_code in settings.target_zips:
        try:
            count = ingest_zip(db, zip_code)
            if count > 0:
                logger.info(f"ZIP {zip_code}: {count} providers ingested")
            total += count
        except httpx.HTTPError as e:
            logger.error(f"ZIP {zip_code}: API error: {e}")
        except Exception as e:
            logger.error(f"ZIP {zip_code}: unexpected error: {e}")
    logger.info(f"Total providers ingested: {total}")
    return total
