"""Organization directory copied from Nexus Billing."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    is_active: bool
    updated_at: datetime


class OrganizationListOut(BaseModel):
    organizations: list[OrganizationOut]
    total: int


class OrganizationSyncOut(BaseModel):
    ok: bool
    synced: int
    deactivated: int
    detail: str = ""
