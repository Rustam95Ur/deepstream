"""Console users CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api import ApiAuth
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


def _out(user: UserRecord) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("", response_model=UserListOut)
def get_users() -> UserListOut:
    return UserListOut(users=[_out(u) for u in list_users()])


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
