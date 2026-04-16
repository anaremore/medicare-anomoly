"""Person/entity match endpoints — LEIE and watchlist correlation."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from sentinel.db import get_db
from sentinel.models import PersonMatch

router = APIRouter(tags=["matches"])


@router.get("/matches")
def list_matches(
    min_confidence: float = Query(30, ge=0, le=100),
    source: str | None = None,
    match_type: str | None = None,
    reviewed: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List person/entity matches ranked by confidence."""
    q = db.query(PersonMatch).filter(PersonMatch.confidence >= min_confidence)

    if source:
        q = q.filter(PersonMatch.matched_source == source)
    if match_type:
        q = q.filter(PersonMatch.match_type == match_type)
    if reviewed is not None:
        q = q.filter(PersonMatch.reviewed == reviewed)

    q = q.order_by(desc(PersonMatch.confidence))
    total = q.count()
    results = q.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [
            {
                "id": m.id,
                "provider_npi": m.provider_npi,
                "provider_name": m.provider_name,
                "matched_source": m.matched_source,
                "matched_name": m.matched_name,
                "matched_city": m.matched_city,
                "matched_state": m.matched_state,
                "matched_specialty": m.matched_specialty,
                "matched_exclusion_type": m.matched_exclusion_type,
                "matched_exclusion_date": m.matched_exclusion_date,
                "confidence": float(m.confidence),
                "confidence_level": (
                    "HIGH" if m.confidence >= 80 else
                    "MEDIUM" if m.confidence >= 50 else
                    "LOW"
                ),
                "confidence_factors": m.confidence_factors,
                "match_type": m.match_type,
                "reviewed": m.reviewed,
                "is_true_match": m.is_true_match,
            }
            for m in results
        ],
    }


@router.get("/matches/summary")
def match_summary(db: Session = Depends(get_db)):
    """Summary stats for person/entity matches."""
    from sqlalchemy import func

    total = db.query(func.count(PersonMatch.id)).scalar() or 0
    high = db.query(func.count(PersonMatch.id)).filter(PersonMatch.confidence >= 80).scalar() or 0
    medium = db.query(func.count(PersonMatch.id)).filter(
        PersonMatch.confidence >= 50, PersonMatch.confidence < 80
    ).scalar() or 0
    low = db.query(func.count(PersonMatch.id)).filter(
        PersonMatch.confidence >= 30, PersonMatch.confidence < 50
    ).scalar() or 0
    reviewed_count = db.query(func.count(PersonMatch.id)).filter(PersonMatch.reviewed == True).scalar() or 0

    return {
        "total": total,
        "high_confidence": high,
        "medium_confidence": medium,
        "low_confidence": low,
        "reviewed": reviewed_count,
        "unreviewed": total - reviewed_count,
    }


@router.patch("/matches/{match_id}/review")
def review_match(
    match_id: int,
    is_true_match: bool,
    db: Session = Depends(get_db),
):
    """Mark a match as reviewed (true positive or false positive)."""
    match = db.get(PersonMatch, match_id)
    if not match:
        return {"error": "Match not found"}, 404

    match.reviewed = True
    match.is_true_match = is_true_match
    db.commit()

    return {"status": "reviewed", "id": match_id, "is_true_match": is_true_match}
