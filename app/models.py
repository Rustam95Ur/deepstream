"""Postgres tables: users, cameras, links, trigger/send history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CameraRow(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    main_uri: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    external_id: Mapped[str] = mapped_column(String(128), default="")
    extra: Mapped[dict[str, Any]] = mapped_column("meta", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LinkRow(Base):
    __tablename__ = "links"

    kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TriggerEventRow(Base):
    __tablename__ = "trigger_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    camera_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(64), default="incident")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class SendEventRow(Base):
    __tablename__ = "send_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sink: Mapped[str] = mapped_column(String(32), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
