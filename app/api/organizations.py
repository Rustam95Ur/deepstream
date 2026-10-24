"""Read-only organization directory synced from Nexus Billing."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api import ApiAuth
from app.db import session_scope
from app.models import OrganizationRow
from app.schemas.organizations import OrganizationListOut, OrganizationOut, OrganizationSyncOut

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"], dependencies=[ApiAuth])


@router.get("", response_model=OrganizationListOut)
def list_organizations() -> OrganizationListOut:
    with session_scope() as session:
        total = session.scalar(select(func.count()).select_from(OrganizationRow)) or 0
        rows = session.scalars(select(OrganizationRow).order_by(OrganizationRow.name.asc(), OrganizationRow.id.asc())).all()
        return OrganizationListOut(
            organizations=[OrganizationOut.model_validate(row) for row in rows],
            total=int(total),
        )


@router.post("/sync", response_model=OrganizationSyncOut)
def sync_organizations_now() -> OrganizationSyncOut:
    from app.services.organization_sync import sync_organizations

    return OrganizationSyncOut.model_validate(sync_organizations())
