"""
console/deps.py

FastAPI Depends() providers: the current authenticated user (two flavors —
one redirects to /login for page routes, one returns 401 JSON for /api/*
routes), plus thin accessors for the shared app.state (sink config, policy
collection) so routers don't reach into `request.app.state` directly.
"""

from fastapi import HTTPException, Request

from console.auth import SESSION_COOKIE_NAME, read_session_token
from console.db import get_connection


def _load_user_from_request(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    data = read_session_token(token)
    if not data:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, email, full_name, role FROM users WHERE id = ?", (data["user_id"],)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def require_user_page(request: Request) -> dict:
    user = _load_user_from_request(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_user_api(request: Request) -> dict:
    user = _load_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_sink_config(request: Request):
    return request.app.state.sink_config


def get_policy_collection(request: Request):
    return request.app.state.policy_collection
