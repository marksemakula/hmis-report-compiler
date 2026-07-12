"""JWT authentication and role-based access control."""
import os
import time

import jwt
from fastapi import HTTPException, Request

JWT_ALGO = "HS256"
TOKEN_TTL = 60 * 60 * 12  # 12 hours

ROLES = {"admin": 3, "data_officer": 2, "viewer": 1}


def _secret():
    return os.environ.get("JWT_SECRET", "change-me-in-production")


def issue_token(user: dict) -> str:
    payload = {
        "sub": user["email"],
        "role": user["role"],
        "name": user.get("full_name", ""),
        "exp": int(time.time()) + TOKEN_TTL,
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGO)


def current_user(request: Request) -> dict:
    token = request.cookies.get("hmis_token", "")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return jwt.decode(token, _secret(), algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session")


def require_role(user: dict, minimum: str):
    if ROLES.get(user.get("role", ""), 0) < ROLES[minimum]:
        raise HTTPException(status_code=403, detail=f"This action requires the {minimum.replace('_',' ')} role or above")
