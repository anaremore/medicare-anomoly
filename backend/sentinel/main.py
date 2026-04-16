"""Sentinel — Medicare Anomaly Detection API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel.api import addresses, alerts, anomalies, map, providers, stats

app = FastAPI(
    title="Sentinel",
    description="Medicare anomaly detection tool — public data analysis for civic use",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(providers.router, prefix="/api")
app.include_router(addresses.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(map.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(anomalies.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
