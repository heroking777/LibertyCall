"""クライアント管理APIルーター."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from ..database import get_db
from ..models import Client, User
from ..auth import get_current_user, require_super_admin

router = APIRouter(prefix="/clients", tags=["clients"])


class ClientCreate(BaseModel):
    client_id: str
    name: str
    description: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ClientResponse(BaseModel):
    id: int
    client_id: str
    name: str
    description: Optional[str]
    is_active: bool
    created_at: str
    created_by: int

    class Config:
        from_attributes = True


def serialize_client(client: Client) -> dict:
    return {
        "id": client.id,
        "client_id": client.client_id,
        "name": client.name,
        "description": client.description,
        "is_active": client.is_active,
        "created_at": client.created_at.isoformat() if client.created_at else "",
        "created_by": client.created_by,
    }


@router.get("")
def list_clients(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    clients = db.query(Client).all()
    return {"clients": [serialize_client(c) for c in clients]}


@router.post("", status_code=201)
def create_client(
    req: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    existing = db.query(Client).filter(Client.client_id == req.client_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="このクライアントIDは既に使用されています")
    client = Client(
        client_id=req.client_id,
        name=req.name,
        description=req.description,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return serialize_client(client)


@router.put("/{client_id}")
def update_client(
    client_id: str,
    req: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="クライアントが見つかりません")
    if req.name is not None:
        client.name = req.name
    if req.description is not None:
        client.description = req.description
    if req.is_active is not None:
        client.is_active = req.is_active
    db.commit()
    db.refresh(client)
    return serialize_client(client)


@router.delete("/{client_id}")
def delete_client(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="クライアントが見つかりません")
    db.delete(client)
    db.commit()
    return {"detail": "削除しました"}
