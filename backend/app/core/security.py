"""Password hashing (Argon2id), JWT (RS256) and symmetric encryption for files and PHI columns."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings
from app.core.ids import utcnow

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> None:
    from app.core.errors import BadRequest

    if len(password) < 10 or password.lower() == password or not any(c.isdigit() for c in password):
        raise BadRequest("Password must be at least 10 characters and contain upper-case, lower-case and digits")


# ---- secrets bootstrap -------------------------------------------------------------------------

def _secret_file(name: str) -> Path:
    settings.SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return settings.SECRETS_DIR / name


def _ensure_rsa_keys() -> tuple[bytes, bytes]:
    priv_path = settings.JWT_PRIVATE_KEY_PATH or _secret_file("jwt.pem")
    pub_path = settings.JWT_PUBLIC_KEY_PATH or _secret_file("jwt.pub")
    if not priv_path.exists():
        if settings.is_production:
            raise RuntimeError("JWT private key missing; provision JWT_PRIVATE_KEY_PATH in production")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
        os.chmod(priv_path, 0o600)
        pub_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                           serialization.PublicFormat.SubjectPublicKeyInfo))
    return priv_path.read_bytes(), pub_path.read_bytes()


@lru_cache
def _jwt_keys() -> tuple[bytes, bytes]:
    return _ensure_rsa_keys()


@lru_cache
def _fernet() -> Fernet:
    key = settings.FILE_ENCRYPTION_KEY
    if not key:
        if settings.is_production:
            raise RuntimeError("FILE_ENCRYPTION_KEY must be set in production")
        path = _secret_file("file_encryption.key")
        if not path.exists():
            path.write_text(Fernet.generate_key().decode())
            os.chmod(path, 0o600)
        key = path.read_text().strip()
    return Fernet(key.encode() if isinstance(key, str) else key)


# ---- JWT ---------------------------------------------------------------------------------------

def create_access_token(user_id: str, roles: list[str]) -> tuple[str, int]:
    priv, _ = _jwt_keys()
    ttl = settings.ACCESS_TOKEN_TTL_MINUTES * 60
    now = utcnow()
    payload = {"sub": user_id, "roles": roles, "iat": now, "exp": now + timedelta(seconds=ttl),
               "jti": secrets.token_hex(8), "typ": "access"}
    return jwt.encode(payload, priv, algorithm="RS256"), ttl


def decode_access_token(token: str) -> dict:
    _, pub = _jwt_keys()
    payload = jwt.decode(token, pub, algorithms=["RS256"])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw)


# ---- hashing / encryption ----------------------------------------------------------------------

def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    return _fernet().decrypt(token)


def encrypt_str(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def random_name() -> str:
    return base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
