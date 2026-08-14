"""Console users CRUD."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api import ApiAuth
from app.paging import cursor_or_400, cursor_str
from app.schemas import UserIn, UserListOut, UserOut, UserUpdateIn
from app.users import (
    EmailTakenError,
    UserRecord,
    create_user,
    delete_user,
    get_user,
    list_users,
    update_user,
    user_count,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"], dependencies=[ApiAuth])


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _out(user: UserRecord) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("", response_model=UserListOut)
def get_users(
    q: str = Query(default=""),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str = Query(default=""),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> UserListOut:
    payload = cursor_or_400(cursor)
    after_email = after_id = None
    if payload is not None:
        after_email = cursor_str(payload, "k")
        after_id = cursor_str(payload, "id")
    paginated = limit is not None or payload is not None
    page_size = (limit or 10) if paginated else None
    users, next_cursor = list_users(
        q=q,
        since=_aware(since),
        until=_aware(until),
        after_email=after_email,
        after_id=after_id,
        limit=page_size,
    )
    return UserListOut(users=[_out(u) for u in users], next_cursor=next_cursor, total=user_count())


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def post_user(body: UserIn) -> UserOut:
    try:
        user = create_user(body.email, body.password, body.name)
    except EmailTakenError:
        raise HTTPException(status_code=409, detail="Email уже занят") from None
    return _out(user)


@router.get("/{user_id}", response_model=UserOut)
def get_one_user(user_id: str) -> UserOut:
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return _out(user)


@router.put("/{user_id}", response_model=UserOut)
def put_user(user_id: str, body: UserUpdateIn) -> UserOut:
    try:
        user = update_user(user_id, email=body.email, name=body.name, password=body.password)
    except EmailTakenError:
        raise HTTPException(status_code=409, detail="Email уже занят") from None
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return _out(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(user_id: str, request: Request) -> None:
    current: UserRecord | None = getattr(request.state, "user", None)
    if current and current.id == user_id:
        raise HTTPException(status_code=400, detail="Нельзя удалить текущий аккаунт")
    if user_count() <= 1:
        raise HTTPException(status_code=400, detail="Нельзя удалить последнего пользователя")
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="Пользователь не найден")
