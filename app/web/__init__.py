"""Minimal web UI for settings + cameras."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.schemas import CameraIn
from app.storage import get_store
from app.web.session import (
    clear_session_cookie,
    is_authed,
    set_session_cookie,
    tokens_match,
)
from app.worker import get_manager

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web"])


def _login_page(
    request: Request,
    *,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    settings = get_store().get_settings()
    setup = not bool((settings.api_token or "").strip())
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "settings": settings,
            "setup": setup,
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_get(request: Request):
    if is_authed(request):
        return RedirectResponse("/", status_code=303)
    return _login_page(request)


@router.post("/ui/login", response_model=None)
def ui_login(
    request: Request,
    token: str = Form(...),
    token_confirm: str = Form(""),
):
    store = get_store()
    settings = store.get_settings()
    expected = (settings.api_token or "").strip()
    submitted = token.strip()

    if not expected:
        confirm = token_confirm.strip()
        if len(submitted) < 4:
            return _login_page(
                request,
                error="Минимум 4 символа",
                status_code=400,
            )
        if not tokens_match(submitted, confirm):
            return _login_page(
                request,
                error="Токены не совпадают",
                status_code=400,
            )
        store.update_settings({"api_token": submitted})
        resp = RedirectResponse("/", status_code=303)
        set_session_cookie(resp, submitted)
        return resp

    if not tokens_match(submitted, expected):
        return _login_page(
            request,
            error="Неверный токен",
            status_code=401,
        )

    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, expected)
    return resp


@router.post("/ui/logout")
def ui_logout() -> RedirectResponse:
    resp = RedirectResponse("/login", status_code=303)
    clear_session_cookie(resp)
    return resp


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    store = get_store()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "settings": store.get_settings(),
            "cameras": store.list_cameras(),
            "worker": get_manager().status(),
            "message": request.query_params.get("msg") or "",
        },
    )


@router.post("/ui/settings")
def ui_save_settings(
    node_id: str = Form(...),
    node_name: str = Form(""),
    api_token: str = Form(""),
    cameras_url: str = Form(""),
    cameras_poll_sec: int = Form(60),
    triggers_url: str = Form(""),
    enable_http_sink: str = Form(""),
    enable_celery_sink: str = Form(""),
    celery_broker_url: str = Form(""),
    cooldown_s: float = Form(30.0),
    presence_min_people: int = Form(1),
    presence_sustain_s: float = Form(2.0),
    min_tracks: int = Form(2),
    converge_dist_bh: float = Form(1.5),
    sustain_s: float = Form(0.4),
    vif_iou_thresh: float = Form(0.25),
    vif_sustain_s: float = Form(0.3),
    clip_pre_s: float = Form(5.0),
    clip_post_s: float = Form(15.0),
    conf_threshold: float = Form(0.25),
    max_streams: int = Form(16),
    auto_start_pipeline: str = Form(""),
) -> RedirectResponse:
    get_store().update_settings(
        {
            "node_id": node_id.strip(),
            "node_name": node_name.strip() or node_id.strip(),
            "api_token": api_token.strip(),
            "cameras_url": cameras_url.strip(),
            "cameras_poll_sec": cameras_poll_sec,
            "triggers_url": triggers_url.strip(),
            "enable_http_sink": enable_http_sink == "on",
            "enable_celery_sink": enable_celery_sink == "on",
            "celery_broker_url": celery_broker_url.strip(),
            "cooldown_s": cooldown_s,
            "presence_min_people": presence_min_people,
            "presence_sustain_s": presence_sustain_s,
            "min_tracks": min_tracks,
            "converge_dist_bh": converge_dist_bh,
            "sustain_s": sustain_s,
            "vif_iou_thresh": vif_iou_thresh,
            "vif_sustain_s": vif_sustain_s,
            "clip_pre_s": clip_pre_s,
            "clip_post_s": clip_post_s,
            "conf_threshold": conf_threshold,
            "max_streams": max_streams,
            "auto_start_pipeline": auto_start_pipeline == "on",
        }
    )
    get_manager().request_reload()
    resp = RedirectResponse("/?msg=settings_saved", status_code=303)
    token = api_token.strip()
    if token:
        set_session_cookie(resp, token)
    else:
        clear_session_cookie(resp)
    return resp


@router.post("/ui/cameras/add")
def ui_add_camera(
    camera_id: str = Form(""),
    name: str = Form(""),
    main_uri: str = Form(...),
    enabled: str = Form("on"),
) -> RedirectResponse:
    store = get_store()
    cid = (camera_id or "").strip() or store.new_camera_id()
    store.upsert_camera(
        CameraIn(
            id=cid,
            name=(name or "").strip() or cid,
            main_uri=main_uri.strip(),
            enabled=enabled == "on",
        )
    )
    get_manager().request_reload()
    return RedirectResponse("/?msg=camera_saved", status_code=303)


@router.post("/ui/cameras/{camera_id}/delete")
def ui_delete_camera(camera_id: str) -> RedirectResponse:
    get_store().delete_camera(camera_id)
    get_manager().request_reload()
    return RedirectResponse("/?msg=camera_deleted", status_code=303)


@router.post("/ui/worker/start")
def ui_worker_start() -> RedirectResponse:
    get_manager().start()
    return RedirectResponse("/?msg=worker_started", status_code=303)


@router.post("/ui/worker/stop")
def ui_worker_stop() -> RedirectResponse:
    get_manager().stop()
    return RedirectResponse("/?msg=worker_stopped", status_code=303)
