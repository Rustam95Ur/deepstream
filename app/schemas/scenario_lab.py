"""Scenario lab: replay clips already stored in history and MinIO."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LabHitOut(BaseModel):
    trigger_type: str = ""
    offset_s: float | None = None


class LabVideoOut(BaseModel):
    scenario: str
    event_id: str
    camera_name: str = ""
    created_at: str = ""
    size: int = 0


class LabResultOut(BaseModel):
    scenario: str
    event_id: str = ""
    camera_name: str = ""
    verdict: str = ""
    detected: list[str] = Field(default_factory=list)
    hits: list[LabHitOut] = Field(default_factory=list)
    error: str = ""
    finished_at: str = ""


class LabRunOut(BaseModel):
    status: str = "idle"
    scenario: str = ""
    started_at: str = ""
    finished_at: str = ""
    paused_live: bool = False
    current_scenario: str = ""
    current_event: str = ""
    current_file: str = ""
    error: str = ""
    results: list[LabResultOut] = Field(default_factory=list)


class LabScenarioOut(BaseModel):
    id: str
    label: str
    hint: str = ""
    ready: bool = True
    videos: list[LabVideoOut] = Field(default_factory=list)


class LabCatalogOut(BaseModel):
    root: str
    run: LabRunOut
    scenarios: list[LabScenarioOut]


class LabStartIn(BaseModel):
    scenario: str = ""
