from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
SESSION_COOKIE = "sf_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def valid_password(password: str) -> bool:
    return MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        name, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if name != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_session_token(user_id: str, secret: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = f"v1.{user_id}.{issued}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


def read_session_token(
    token: str, secret: str, now: float | None = None
) -> str | None:
    try:
        encoded_payload, encoded_signature = token.split(".")
        payload = _b64decode(encoded_payload)
        signature = _b64decode(encoded_signature)
    except (ValueError, TypeError, base64.binascii.Error):
        return None
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        version, user_id, issued = payload.decode("utf-8").split(".")
    except ValueError:
        return None
    if version != "v1":
        return None
    current = now if now is not None else time.time()
    if current - int(issued) > SESSION_MAX_AGE:
        return None
    return user_id
