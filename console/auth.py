"""
console/auth.py

Password hashing (bcrypt) + signed-cookie sessions (itsdangerous) for the
console's real login. No server-side session store — the cookie itself
carries the (signed, tamper-proof) user id and email.

SECRET_KEY: read from the SESSION_SECRET_KEY env var if set, otherwise
generated once and persisted to a gitignored local file. Falling back to a
random key generated fresh on every process start would log everyone out
on every `uvicorn --reload` restart during development, which is worse than
persisting a locally-generated one.
"""

import os
import secrets
from pathlib import Path

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SECRET_KEY_FILE = Path(__file__).parent / ".secret_key"
SESSION_COOKIE_NAME = "itops_session"
SESSION_MAX_AGE = 12 * 60 * 60  # 12 hours


def _get_secret_key() -> str:
    env_key = os.environ.get("SESSION_SECRET_KEY")
    if env_key:
        return env_key
    if SECRET_KEY_FILE.exists():
        return SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(key, encoding="utf-8")
    return key


_serializer = URLSafeTimedSerializer(_get_secret_key(), salt="itops-console-session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_session_token(user_id: int, email: str) -> str:
    return _serializer.dumps({"user_id": user_id, "email": email})


def read_session_token(token: str) -> dict | None:
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
