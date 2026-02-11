"""初期スーパー管理者アカウント作成."""
import sys
from console_backend.database import SessionLocal
from console_backend.models import User
from console_backend.auth import get_password_hash


def create_super_admin(email: str, password: str):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"既に存在: {email}")
            sys.exit(1)
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            role="super_admin",
            client_id=None,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"スーパー管理者作成完了: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python seed_admin.py <email> <password>")
        sys.exit(1)
    create_super_admin(sys.argv[1], sys.argv[2])
