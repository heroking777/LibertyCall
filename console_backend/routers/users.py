"""ユーザー管理APIルーター."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models import User
from ..auth import get_current_user, require_super_admin, get_password_hash

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    email: str
    password: str
    role: str = "client_admin"
    client_id: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    client_id: Optional[str] = None
    is_active: Optional[bool] = None


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "client_id": user.client_id,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else "",
    }


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    users = db.query(User).all()
    return {"users": [serialize_user(u) for u in users]}


@router.post("", status_code=201)
def create_user(
    req: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    if req.role not in ("super_admin", "client_admin"):
        raise HTTPException(status_code=400, detail="roleはsuper_adminまたはclient_adminのみ")
    if req.role == "client_admin" and not req.client_id:
        raise HTTPException(status_code=400, detail="client_adminにはclient_idが必要です")
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="このメールアドレスは既に使用されています")
    user = User(
        email=req.email,
        hashed_password=get_password_hash(req.password),
        role=req.role,
        client_id=req.client_id if req.role == "client_admin" else None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.put("/{user_id}")
def update_user(
    user_id: int,
    req: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    if req.email is not None:
        dup = db.query(User).filter(User.email == req.email, User.id != user_id).first()
        if dup:
            raise HTTPException(status_code=400, detail="このメールアドレスは既に使用されています")
        user.email = req.email
    if req.password is not None:
        user.hashed_password = get_password_hash(req.password)
    if req.role is not None:
        if req.role not in ("super_admin", "client_admin"):
            raise HTTPException(status_code=400, detail="roleはsuper_adminまたはclient_adminのみ")
        user.role = req.role
    if req.client_id is not None:
        user.client_id = req.client_id
    if req.is_active is not None:
        user.is_active = req.is_active
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="自分自身は削除できません")
    db.delete(user)
    db.commit()
    return {"detail": "削除しました"}
