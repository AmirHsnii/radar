"""
JWT-based authentication for the admin panel.

Credentials are read from env (ADMIN_USERNAME / ADMIN_PASSWORD).
Tokens are signed with SECRET_KEY using HS256.
"""
from __future__ import annotations

import time

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.settings_env import ADMIN_PASSWORD, ADMIN_USERNAME, SECRET_KEY

_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 28_800  # 8 h

_bearer = HTTPBearer(auto_error=False)


def create_access_token() -> str:
    payload = {
        "sub": "admin",
        "iat": int(time.time()),
        "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=_ALGORITHM)


def verify_credentials(username: str, password: str) -> bool:
    if not ADMIN_PASSWORD:
        raise RuntimeError("ADMIN_PASSWORD is not set in environment")
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    return payload["sub"]
