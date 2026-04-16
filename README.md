# Sentinel

Medicare anomaly detection tool that cross-references public federal datasets to surface leading indicators of billing anomalies in the Houston, TX metro area.

## What It Does

Sentinel stitches together data from multiple free federal registries that nobody is currently connecting:

- **NPPES NPI Registry** — provider registrations, addresses, taxonomy codes
- **OIG LEIE Exclusion Database** — individuals/entities excluded from federal healthcare programs

It identifies patterns that are visible in public data before enforcement catches up:
- Extreme address clustering (20+ DME suppliers at a single small office building)
- Registration bursts (multiple entities registered days apart at the same address)
- Active entities at addresses where excluded providers operated
- Template-style naming patterns common in fraudulent entity formation

## Quick Start

```bash
# Start the database
docker compose up -d

# Set up the backend
cd backend
pip install -r requirements.txt
alembic upgrade head

# Load data
python scripts/seed_leie.py      # ~83k exclusion records
python scripts/seed_nppes.py     # Houston-area DME/HHA/Hospice providers
python scripts/run_analysis.py   # Compute risk scores + generate alerts

# Start the API
uvicorn sentinel.main:app --reload

# In another terminal, start the frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 to view the dashboard.

## Important

This is a **civic/journalistic tool**. All data comes from public federal registries. The tool surfaces **anomaly signals**, not accusations. An entity at a suspicious address may have a perfectly legitimate reason to be there.

## License

MIT
