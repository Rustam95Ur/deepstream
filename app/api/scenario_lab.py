"""Console API: replay history clips through the scenario detector."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api import ApiAuth, LicenseAuth
from app.scenario_lab import LabError, catalog
from app.schemas.scenario_lab import LabCatalogOut, LabStartIn
from app.video_client import VideoRequestError, lab_cancel, lab_start

router = APIRouter(
    prefix="/api/v1/scenario-lab",
    tags=["scenario-lab"],
    dependencies=[ApiAuth, LicenseAuth],
)


def _catalog() -> LabCatalogOut:
    return LabCatalogOut.model_validate(catalog())


def _offline(exc: Exception) -> HTTPException:
    if isinstance(exc, VideoRequestError):
        status = exc.status if exc.status in {400, 403, 409} else 503
        return HTTPException(
            status_code=status, detail=exc.detail or "видео-сервис недоступен"
        )
    return HTTPException(status_code=503, detail=f"видео-сервис недоступен: {exc}")


@router.get("", response_model=LabCatalogOut)
def get_lab() -> LabCatalogOut:
    return _catalog()


@router.post("/run", response_model=LabCatalogOut)
def run_lab(body: LabStartIn) -> LabCatalogOut:
    try:
        lab_start(body.scenario or "")
    except LabError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    except Exception as exc:
        raise _offline(exc) from exc
    return _catalog()


@router.post("/cancel", response_model=LabCatalogOut)
def cancel_lab() -> LabCatalogOut:
    try:
        lab_cancel()
    except Exception as exc:
        raise _offline(exc) from exc
    return _catalog()
