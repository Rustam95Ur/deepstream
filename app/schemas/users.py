"""Console user and session schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas._util import normalize_email


class UserIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return (v or "").strip()


class UserUpdateIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    name: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        raw = v or ""
        if raw and len(raw) < 8:
            raise ValueError("Пароль слишком короткий")
        return raw


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime
    updated_at: datetime


class UserListOut(BaseModel):
    users: list[UserOut]
    next_cursor: str | None = None
    total: int = 0


class LoginIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)
    password_confirm: str = ""

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class SessionOut(BaseModel):
    authenticated: bool
    setup: bool
    user_id: str = ""
    email: str = ""
    name: str = ""
    node_id: str
    node_name: str
    license_valid: bool = False
    license_reason: str = ""
