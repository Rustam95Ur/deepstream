"""Read-only organization directory synced from Nexus Billing."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api import ApiAuth
from app.db import session_scope
from app.models import OrganizationRow
from app.schemas.organizations import OrganizationIn, OrganizationListOut, OrganizationOut, OrganizationSyncOut

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


@router.post("", response_model=OrganizationOut, status_code=201)
def create_organization(body: OrganizationIn) -> OrganizationOut:
    from uuid import uuid4

    from app.sso import configured as sso_configured
    from app.timeutil import utcnow

    if sso_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Организации создаются в биллинге и приходят сюда сами",
        )
    with session_scope(write=True) as session:
        row = OrganizationRow(
            id=str(uuid4()),
            name=body.name.strip(),
            description=(body.description or "").strip(),
            is_active=True,
            updated_at=utcnow(),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        return OrganizationOut.model_validate(row)


@router.post("/sync", response_model=OrganizationSyncOut)
def sync_organizations_now() -> OrganizationSyncOut:
    from app.services.organization_sync import sync_organizations

    return OrganizationSyncOut.model_validate(sync_organizations())
