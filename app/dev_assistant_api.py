from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .dev_assistant import (
    create_pr_plan,
    create_workspace,
    list_source_files,
    list_workspaces,
    quarantine_workspace,
    read_source_file,
    save_patch,
    validate_workspace,
    workspace_status,
)

router = APIRouter(prefix="/api/development", tags=["development-assistant"])


class WorkspaceRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    problem: str = Field(min_length=10, max_length=5000)


class PatchRequest(BaseModel):
    patch: str = Field(min_length=20, max_length=512000)
    reason: str = Field(min_length=3, max_length=3000)


class PullRequestPlan(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=10, max_length=10000)


class QuarantineRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


@router.get("/workspaces")
def workspaces(limit: int = Query(50, ge=1, le=200)):
    return {"ok": True, "items": list_workspaces(limit)}


@router.post("/workspaces")
def new_workspace(payload: WorkspaceRequest):
    try:
        return {"ok": True, "workspace": create_workspace(payload.title, payload.problem)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/workspaces/{workspace_id}")
def status(workspace_id: str):
    try:
        return {"ok": True, **workspace_status(workspace_id)}
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/workspaces/{workspace_id}/files")
def files(workspace_id: str, q: str = Query("", max_length=200)):
    try:
        return {"ok": True, "items": list_source_files(workspace_id, q)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/workspaces/{workspace_id}/file")
def file_content(workspace_id: str, path: str = Query(..., min_length=1, max_length=500)):
    try:
        return {"ok": True, **read_source_file(workspace_id, path)}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/workspaces/{workspace_id}/patch")
def patch(workspace_id: str, payload: PatchRequest):
    try:
        return {"ok": True, "proposal": save_patch(workspace_id, payload.patch, payload.reason)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/workspaces/{workspace_id}/validate")
def validate(workspace_id: str):
    try:
        return {"ok": True, "validation": validate_workspace(workspace_id)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/workspaces/{workspace_id}/pr-plan")
def pr_plan(workspace_id: str, payload: PullRequestPlan):
    try:
        return {"ok": True, "plan": create_pr_plan(workspace_id, payload.title, payload.body)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/workspaces/{workspace_id}/quarantine")
def quarantine(workspace_id: str, payload: QuarantineRequest):
    try:
        return {"ok": True, "quarantine": quarantine_workspace(workspace_id, payload.reason)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
