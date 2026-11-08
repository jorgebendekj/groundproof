from datetime import timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, User, now

bearer = HTTPBearer(auto_error=False)


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def make_token(user: User) -> str:
    s = get_settings()
    exp = now() + timedelta(minutes=s.jwt_expire_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, s.jwt_secret, algorithm="HS256")


def current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if cred is None:
        raise HTTPException(401, "Not authenticated")
    try:
        data = jwt.decode(cred.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, "Invalid token") from e
    user = db.get(User, int(data["sub"]))
    if not user:
        raise HTTPException(401, "Unknown user")
    return user


def require(*roles: str):
    def dep(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Role '{user.role}' not allowed")
        return user
    return dep


def audit(db: Session, user: User | None, action: str, obj_type: str, obj_id: object,
          before: dict | None = None, after: dict | None = None) -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, object_type=obj_type,
                    object_id=str(obj_id), before=before, after=after))


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"
