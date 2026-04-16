"""Fuzzy name matching engine with confidence scoring.

Matches provider/entity names against exclusion records, DOJ defendants,
and other watchlists using multiple matching strategies with a confidence
score that accounts for name commonality, geographic proximity, and
specialty alignment.

Confidence levels:
  HIGH (80-100):   Exact or near-exact match + same city/ZIP + specialty overlap
  MEDIUM (50-79):  Strong name match + geographic proximity
  LOW (30-49):     Fuzzy name match, may be coincidence
  NONE (<30):      Not reported
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import func
from sqlalchemy.orm import Session

from sentinel.models import Exclusion, Provider

logger = logging.getLogger(__name__)

# Common names that produce false positives — reduce confidence for these
# Based on US Census most common surnames
COMMON_SURNAMES = {
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER",
    "DAVIS", "RODRIGUEZ", "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ",
    "WILSON", "ANDERSON", "THOMAS", "TAYLOR", "MOORE", "JACKSON", "MARTIN",
    "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS", "SANCHEZ", "CLARK",
    "RAMIREZ", "LEWIS", "ROBINSON", "WALKER", "YOUNG", "ALLEN", "KING",
    "WRIGHT", "SCOTT", "TORRES", "NGUYEN", "HILL", "FLORES", "GREEN",
    "ADAMS", "NELSON", "BAKER", "HALL", "RIVERA", "CAMPBELL", "MITCHELL",
    "CARTER", "ROBERTS",
}

# Common first names that are ambiguous
COMMON_FIRST_NAMES = {
    "JAMES", "JOHN", "ROBERT", "MICHAEL", "DAVID", "WILLIAM", "RICHARD",
    "JOSEPH", "THOMAS", "CHARLES", "MARY", "PATRICIA", "JENNIFER", "LINDA",
    "ELIZABETH", "BARBARA", "SUSAN", "JESSICA", "SARAH", "KAREN", "MARIA",
    "JOSE", "JUAN", "CARLOS", "LUIS", "MOHAMMED", "AHMED", "MOHAMED",
}


@dataclass
class NameMatch:
    """A potential match between a provider and an exclusion/watchlist record."""
    provider_npi: str
    provider_name: str
    provider_city: str | None
    provider_zip: str | None
    matched_source: str  # "leie", "doj", "sam"
    matched_record_id: int | None
    matched_name: str
    matched_city: str | None
    matched_state: str | None
    matched_specialty: str | None
    matched_exclusion_type: str | None
    matched_exclusion_date: str | None
    confidence: float  # 0-100
    confidence_factors: dict
    match_type: str  # "exact", "fuzzy_strong", "fuzzy_weak", "org_name"


def normalize_name(name: str) -> str:
    """Normalize a name for comparison."""
    name = name.upper().strip()
    # Remove common suffixes
    name = re.sub(r"\b(JR|SR|II|III|IV|MD|DO|NP|PA|RN|LVN|LLC|INC|CORP|DBA)\b\.?", "", name)
    # Remove punctuation
    name = re.sub(r"[.,'-]", " ", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def name_similarity(name1: str, name2: str) -> float:
    """Compute similarity between two names (0.0 - 1.0)."""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    if n1 == n2:
        return 1.0

    # Length ratio penalty — if one name is much shorter, it's likely a substring match
    len_ratio = min(len(n1), len(n2)) / max(len(n1), len(n2)) if max(len(n1), len(n2)) > 0 else 0

    # If one is <50% the length of the other, it's not a real match
    if len_ratio < 0.5:
        return len_ratio * 0.5  # Heavy penalty

    # SequenceMatcher for fuzzy comparison
    return SequenceMatcher(None, n1, n2).ratio()


def compute_match_confidence(
    name_sim: float,
    same_city: bool,
    same_zip: bool,
    same_state: bool,
    is_common_name: bool,
    specialty_overlap: bool,
    is_individual: bool,
) -> tuple[float, dict]:
    """Compute confidence score for a name match.

    Returns (confidence 0-100, factor breakdown dict).
    """
    factors = {}

    # Base: name similarity (0-50 points)
    name_score = name_sim * 50
    factors["name_similarity"] = round(name_sim, 3)
    factors["name_score"] = round(name_score, 1)

    # Geographic proximity (0-25 points)
    if same_zip:
        geo_score = 25.0
        factors["geo_match"] = "same_zip"
    elif same_city:
        geo_score = 20.0
        factors["geo_match"] = "same_city"
    elif same_state:
        geo_score = 5.0
        factors["geo_match"] = "same_state"
    else:
        geo_score = 0.0
        factors["geo_match"] = "none"
    factors["geo_score"] = geo_score

    # Specialty/type overlap (0-15 points)
    specialty_score = 15.0 if specialty_overlap else 0.0
    factors["specialty_overlap"] = specialty_overlap
    factors["specialty_score"] = specialty_score

    # Penalty for common names (0 to -20 points)
    common_penalty = -20.0 if is_common_name else 0.0
    factors["is_common_name"] = is_common_name
    factors["common_penalty"] = common_penalty

    # Bonus for individual match (vs org) — individual names are more specific
    individual_bonus = 10.0 if is_individual else 0.0
    factors["individual_bonus"] = individual_bonus

    confidence = max(0.0, min(100.0,
        name_score + geo_score + specialty_score + common_penalty + individual_bonus
    ))
    factors["total"] = round(confidence, 1)

    return round(confidence, 1), factors


def is_healthcare_specialty(specialty: str | None) -> bool:
    """Check if an exclusion specialty is healthcare-related."""
    if not specialty:
        return False
    healthcare_keywords = {
        "NURSE", "PHYSICIAN", "DOCTOR", "PHARMACIST", "THERAPIST",
        "HOME HEALTH", "DME", "MEDICAL", "HEALTH", "HOSPICE",
        "AIDE", "PERSONAL CARE", "SUPPLIER",
    }
    spec = specialty.upper()
    return any(kw in spec for kw in healthcare_keywords)


def match_providers_against_leie(
    db: Session,
    min_confidence: float = 30.0,
) -> list[NameMatch]:
    """Match all providers against LEIE exclusion records by name.

    Strategy:
    1. For individual providers (entity_type=1): match last_name + first_name
    2. For org providers (entity_type=2): match org_name against bus_name
    3. Also match individual provider names against org operator names
    """
    matches = []

    # --- Strategy 1: Individual provider names vs LEIE individual names ---
    individual_providers = (
        db.query(Provider)
        .filter(
            Provider.entity_type == 1,
            Provider.last_name.isnot(None),
        )
        .all()
    )

    # Build LEIE name index by last name for fast lookup
    leie_by_lastname: dict[str, list[Exclusion]] = defaultdict(list)
    all_exclusions = db.query(Exclusion).filter(Exclusion.last_name.isnot(None)).all()
    for exc in all_exclusions:
        parts = normalize_name(exc.last_name).split() if exc.last_name else []
        key = parts[0] if parts else ""
        if key:
            leie_by_lastname[key].append(exc)

    for provider in individual_providers:
        prov_last = normalize_name(provider.last_name or "")
        prov_first = normalize_name(provider.first_name or "")
        if not prov_last:
            continue

        # Look up by last name
        last_key = prov_last.split()[0] if prov_last else ""
        candidates = leie_by_lastname.get(last_key, [])

        for exc in candidates:
            exc_last = normalize_name(exc.last_name or "")
            exc_first = normalize_name(exc.first_name or "")

            # Last name must be very similar
            last_sim = name_similarity(prov_last, exc_last)
            if last_sim < 0.9:
                continue

            # First name similarity — must be strong to avoid false positives
            if prov_first and exc_first:
                first_sim = name_similarity(prov_first, exc_first)
                # Require first name to be genuinely similar, not just fuzzy
                if first_sim < 0.75:
                    continue
            else:
                first_sim = 0.3  # Low confidence without first name match

            # Combined name similarity
            name_sim = (last_sim * 0.5 + first_sim * 0.5)

            if name_sim < 0.8:
                continue

            # Geographic check
            prov_city = (provider.practice_city or "").upper().strip()
            prov_zip = (provider.practice_zip or "")[:5]
            prov_state = (provider.practice_state or "").upper().strip()
            exc_city = (exc.city or "").upper().strip()
            exc_zip = (exc.zip or "")[:5]
            exc_state = (exc.state or "").upper().strip()

            same_zip = prov_zip and exc_zip and prov_zip == exc_zip
            same_city = prov_city and exc_city and prov_city == exc_city
            same_state = prov_state and exc_state and prov_state == exc_state

            is_common = (
                prov_last.split()[0] in COMMON_SURNAMES
                and prov_first.split()[0] in COMMON_FIRST_NAMES
            ) if prov_first else prov_last.split()[0] in COMMON_SURNAMES

            specialty_overlap = is_healthcare_specialty(exc.specialty)

            confidence, factors = compute_match_confidence(
                name_sim=name_sim,
                same_city=same_city,
                same_zip=same_zip,
                same_state=same_state,
                is_common_name=is_common,
                specialty_overlap=specialty_overlap,
                is_individual=True,
            )

            if confidence >= min_confidence:
                matches.append(NameMatch(
                    provider_npi=provider.npi,
                    provider_name=f"{provider.last_name}, {provider.first_name}",
                    provider_city=provider.practice_city,
                    provider_zip=provider.practice_zip,
                    matched_source="leie",
                    matched_record_id=exc.id,
                    matched_name=f"{exc.last_name}, {exc.first_name}",
                    matched_city=exc.city,
                    matched_state=exc.state,
                    matched_specialty=exc.specialty,
                    matched_exclusion_type=exc.exclusion_type,
                    matched_exclusion_date=str(exc.exclusion_date) if exc.exclusion_date else None,
                    confidence=confidence,
                    confidence_factors=factors,
                    match_type="exact" if name_sim > 0.95 else "fuzzy_strong" if name_sim > 0.85 else "fuzzy_weak",
                ))

    # --- Strategy 2: Org names vs LEIE business names ---
    # Index LEIE orgs by first word for fast candidate lookup
    org_providers = (
        db.query(Provider)
        .filter(
            Provider.entity_type == 2,
            Provider.org_name.isnot(None),
        )
        .all()
    )

    leie_orgs = (
        db.query(Exclusion)
        .filter(Exclusion.bus_name.isnot(None), Exclusion.bus_name != "")
        .all()
    )

    # Build index by first word of business name for O(1) candidate lookup
    leie_org_by_first_word: dict[str, list[Exclusion]] = defaultdict(list)
    for exc in leie_orgs:
        words = normalize_name(exc.bus_name or "").split()
        if words:
            leie_org_by_first_word[words[0]].append(exc)
            # Also index by second word for better recall
            if len(words) > 1:
                leie_org_by_first_word[words[1]].append(exc)

    for provider in org_providers:
        prov_name = normalize_name(provider.org_name or "")
        if not prov_name or len(prov_name) < 5:
            continue

        # Only compare against orgs sharing a keyword (not all 3,396)
        prov_words = prov_name.split()
        candidates = set()
        for word in prov_words[:3]:  # First 3 words
            if len(word) >= 3:  # Skip short words like "A", "OF"
                for exc in leie_org_by_first_word.get(word, []):
                    candidates.add(exc.id)

        for exc in leie_orgs:
            if exc.id not in candidates:
                continue
            exc_name = normalize_name(exc.bus_name or "")
            if not exc_name or len(exc_name) < 5:
                continue

            sim = name_similarity(prov_name, exc_name)
            # Require higher similarity for short names (avoid "HOMECARE" matching everything)
            min_sim = 0.9 if len(exc_name) < 15 else 0.8
            if sim < min_sim:
                continue

            prov_city = (provider.practice_city or "").upper().strip()
            prov_state = (provider.practice_state or "").upper().strip()
            exc_city = (exc.city or "").upper().strip()
            exc_state = (exc.state or "").upper().strip()

            same_city = prov_city and exc_city and prov_city == exc_city
            same_state = prov_state and exc_state and prov_state == exc_state

            confidence, factors = compute_match_confidence(
                name_sim=sim,
                same_city=same_city,
                same_zip=False,
                same_state=same_state,
                is_common_name=False,
                specialty_overlap=True,  # Both are healthcare entities
                is_individual=False,
            )

            if confidence >= min_confidence:
                matches.append(NameMatch(
                    provider_npi=provider.npi,
                    provider_name=provider.org_name,
                    provider_city=provider.practice_city,
                    provider_zip=provider.practice_zip,
                    matched_source="leie",
                    matched_record_id=exc.id,
                    matched_name=exc.bus_name,
                    matched_city=exc.city,
                    matched_state=exc.state,
                    matched_specialty=exc.specialty,
                    matched_exclusion_type=exc.exclusion_type,
                    matched_exclusion_date=str(exc.exclusion_date) if exc.exclusion_date else None,
                    confidence=confidence,
                    confidence_factors=factors,
                    match_type="org_name",
                ))

    # Sort by confidence descending
    matches.sort(key=lambda m: m.confidence, reverse=True)
    logger.info(f"Found {len(matches)} name matches (min confidence {min_confidence})")
    return matches
