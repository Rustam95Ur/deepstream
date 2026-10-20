"""Outbound webhook proxy: request plan and input validation."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.ds.sinks.http_sink import HttpProxy, connect_plan
from app.schemas.webhooks import WebhookIn


def _hook(**extra: object) -> WebhookIn:
    payload = {
        "url": "https://foqus.vision/api/v1/incidents/",
        "login": "admin",
        "password": "secret-pass",
        **extra,
    }
    return WebhookIn.model_validate(payload)


def test_proxy_off_by_default() -> None:
    hook = _hook()
    assert hook.proxy_enabled is False
    assert hook.proxy_host == ""
    assert hook.proxy_port == 0
    assert hook.proxy_password is None


def test_proxy_requires_host_and_port() -> None:
    with pytest.raises(ValidationError):
        _hook(proxy_enabled=True)
    with pytest.raises(ValidationError):
        _hook(proxy_enabled=True, proxy_host="10.0.0.8")


def test_proxy_url_splits_host_and_port() -> None:
    hook = _hook(proxy_enabled=True, proxy_host="http://10.0.0.8:3128")
    assert hook.proxy_host == "10.0.0.8"
    assert hook.proxy_port == 3128


def test_explicit_port_wins_over_pasted_url() -> None:
    hook = _hook(proxy_enabled=True, proxy_host="http://10.0.0.8:3128", proxy_port=8080)
    assert hook.proxy_host == "10.0.0.8"
    assert hook.proxy_port == 8080


def test_proxy_password_needs_login() -> None:
    with pytest.raises(ValidationError):
        _hook(proxy_enabled=True, proxy_host="10.0.0.8", proxy_port=3128, proxy_password="x")


def test_direct_https_plan() -> None:
    plan = connect_plan("https://foqus.vision/api/v1/incidents/")
    assert not isinstance(plan, str)
    assert plan.connect_host == "foqus.vision"
    assert plan.connect_port == 443
    assert plan.path == "/api/v1/incidents/"
    assert plan.tls is True
    assert plan.tunnel is None


def test_http_proxy_uses_absolute_uri_and_basic_auth() -> None:
    proxy = HttpProxy(host="10.0.0.8", port=3128, username="proxy", password="p@ss")
    plan = connect_plan("http://campus.example/api/v1/incidents/?x=1", proxy)
    assert not isinstance(plan, str)
    assert plan.connect_host == "10.0.0.8"
    assert plan.connect_port == 3128
    assert plan.tls is False
    assert plan.path == "http://campus.example/api/v1/incidents/?x=1"
    token = base64.b64encode(b"proxy:p@ss").decode("ascii")
    assert plan.extra_headers == {"Proxy-Authorization": f"Basic {token}"}


def test_https_proxy_uses_connect_tunnel() -> None:
    proxy = HttpProxy(host="10.0.0.8", port=3128, username="proxy", password="secret")
    plan = connect_plan("https://foqus.vision/api/v1/incidents/", proxy)
    assert not isinstance(plan, str)
    assert plan.tls is True
    assert plan.tunnel == ("foqus.vision", 443)
    assert plan.path == "/api/v1/incidents/"
    assert plan.extra_headers is None
    assert plan.tunnel_headers is not None
    assert plan.tunnel_headers["Proxy-Authorization"].startswith("Basic ")
