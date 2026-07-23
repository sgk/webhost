from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

PASSWORD_SCHEME = "scrypt_v1"
PASSWORD_SCRYPT_N = 16384
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_SALT_BYTES = 16
PASSWORD_HASH_BYTES = 32
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024
PASSWORD_SCRYPT_MAXMEM = 64 * 1024 * 1024

DUMMY_PASSWORD_HASH = (
    "scrypt_v1$16384$8$1$d2ViaG9zdC1kdW1teS12MQ$"
    "JRR6KKeaN_2roe4mjmQZeOJ6ctuhR44IB9JQiu6YGIU"
)


def password_document_id(email: str) -> str:
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_new_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"パスワードは{PASSWORD_MIN_LENGTH}文字以上にしてください。")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"パスワードは{PASSWORD_MAX_LENGTH}文字以下にしてください。")


def generate_password() -> str:
    return secrets.token_urlsafe(24)


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    validate_new_password(password)
    password_salt = salt if salt is not None else secrets.token_bytes(PASSWORD_SALT_BYTES)
    if len(password_salt) != PASSWORD_SALT_BYTES:
        raise ValueError(f"ソルトは{PASSWORD_SALT_BYTES}バイトにしてください。")
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=password_salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_HASH_BYTES,
        maxmem=PASSWORD_SCRYPT_MAXMEM,
    )
    encoded_salt = base64.urlsafe_b64encode(password_salt).decode("ascii").rstrip("=")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return (
        f"{PASSWORD_SCHEME}${PASSWORD_SCRYPT_N}${PASSWORD_SCRYPT_R}$"
        f"{PASSWORD_SCRYPT_P}${encoded_salt}${encoded_digest}"
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    if len(password) > PASSWORD_MAX_LENGTH:
        return False
    try:
        scheme, n_text, r_text, p_text, salt_text, digest_text = encoded_hash.split("$")
        if scheme != PASSWORD_SCHEME:
            return False
        n = int(n_text)
        r = int(r_text)
        p = int(p_text)
        if (n, r, p) != (PASSWORD_SCRYPT_N, PASSWORD_SCRYPT_R, PASSWORD_SCRYPT_P):
            return False
        salt = _decode_base64(salt_text)
        expected = _decode_base64(digest_text)
        if len(salt) != PASSWORD_SALT_BYTES or len(expected) != PASSWORD_HASH_BYTES:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=PASSWORD_SCRYPT_MAXMEM,
        )
    except (binascii.Error, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _decode_base64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(f"{value}{padding}", altchars=b"-_", validate=True)
