# Sentinel — Medicare Anomaly Detection

## Project Overview
Civic tool that cross-references public federal datasets to surface leading indicators of Medicare/Medicaid billing anomalies. Focus: Houston, TX (Harris County).

## Tech Stack
- Backend: Python 3.12+ / FastAPI / SQLAlchemy / Alembic
- Database: PostgreSQL 16 + PostGIS (Docker Compose)
- Frontend: React 18 + Leaflet + Vite
- Geocoding: US Census Geocoder

## Development
```bash
# Start database
docker compose up -d

# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn sentinel.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Key Commands
```bash
# Run ETL
python backend/scripts/seed_nppes.py
python backend/scripts/seed_leie.py
python backend/scripts/run_analysis.py

# Run migrations
cd backend && alembic upgrade head
cd backend && alembic revision --autogenerate -m "description"
```

## Architecture
- `backend/sentinel/etl/` — Data ingestion from NPPES, LEIE, etc.
- `backend/sentinel/analysis/` — Clustering, velocity, scoring, alerts
- `backend/sentinel/api/` — FastAPI route modules
- `frontend/src/components/` — React UI components

## Important Notes
- All language uses "anomaly" not "fraud" — this is a civic tool, not law enforcement
- All data sources are public federal registries
- NPPES API limit: 200 results per query, paginate with `skip` parameter
- Target taxonomy codes: 332B00000X (DME), 251E00000X (HHA), 251G00000X (Hospice)
