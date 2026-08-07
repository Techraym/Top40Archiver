from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .download_db import (
    cancel_job,
    jobs,
    provider_dashboard,
    retry_job,
    update_provider_config,
)

router = APIRouter()


class ProviderConfigIn(BaseModel):
    priority: int | None = Field(default=None, ge=1, le=500)
    max_concurrent: int | None = Field(default=None, ge=1, le=4)
    requests_per_minute: int | None = Field(default=None, ge=1, le=600)
    min_delay_seconds: float | None = Field(default=None, ge=0, le=600)
    error_backoff_seconds: int | None = Field(default=None, ge=10, le=7200)

    def values(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


@router.get("/api/download/status")
def download_status():
    return provider_dashboard()


@router.get("/api/download/jobs")
def download_jobs(limit: int = Query(default=100, ge=1, le=500)):
    return {"ok": True, "items": jobs(limit)}


@router.get("/api/download/providers")
def download_providers():
    return provider_dashboard()


@router.post("/api/download/retry/{track_id}")
def retry_download(track_id: int):
    if not retry_job(track_id):
        raise HTTPException(status_code=404, detail="track niet gevonden of al gedownload")
    return {"ok": True, "track_id": track_id, "status": "queued"}


@router.post("/api/download/cancel/{track_id}")
def cancel_download(track_id: int):
    if not cancel_job(track_id):
        raise HTTPException(status_code=404, detail="actieve downloadjob niet gevonden")
    return {"ok": True, "track_id": track_id, "status": "cancelled"}


@router.post("/api/download/provider/{provider}/enable")
def enable_provider(provider: str):
    try:
        item = update_provider_config(provider, {"enabled": True})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="onbekende provider") from exc
    return {"ok": True, "provider": item}


@router.post("/api/download/provider/{provider}/disable")
def disable_provider(provider: str):
    try:
        item = update_provider_config(provider, {"enabled": False})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="onbekende provider") from exc
    return {"ok": True, "provider": item}


@router.post("/api/download/provider/{provider}/config")
def configure_provider(provider: str, payload: ProviderConfigIn):
    values = payload.values()
    if not values:
        raise HTTPException(status_code=400, detail="geen providerinstellingen opgegeven")
    try:
        item = update_provider_config(provider, values)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="onbekende provider") from exc
    return {"ok": True, "provider": item}
