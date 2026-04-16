"""Alert feed endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from sentinel.db import get_db
from sentinel.models import Alert

router = APIRouter(tags=["alerts"])


@router.get("/alerts")
def list_alerts(
    severity: str | None = None,
    alert_type: str | None = None,
    acknowledged: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List alerts, newest first."""
    q = db.query(Alert)

    if severity:
        q = q.filter(Alert.severity == severity)
    if alert_type:
        q = q.filter(Alert.alert_type == alert_type)
    if acknowledged is not None:
        q = q.filter(Alert.acknowledged == acknowledged)

    q = q.order_by(desc(Alert.created_at))
    total = q.count()
    results = q.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": [
            {
                "id": alert.id,
                "alert_type": alert.alert_type,
                "npi": alert.npi,
                "address_id": alert.address_id,
                "severity": alert.severity,
                "details": alert.details,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
                "acknowledged": alert.acknowledged,
            }
            for alert in results
        ],
    }


@router.patch("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    """Mark an alert as acknowledged."""
    alert = db.get(Alert, alert_id)
    if not alert:
        return {"error": "Alert not found"}, 404

    alert.acknowledged = True
    db.commit()
    return {"status": "acknowledged", "id": alert_id}
