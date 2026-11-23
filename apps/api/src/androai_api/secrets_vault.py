"""Encryption for secrets stored in the database (e.g. payment-provider keys, signing-key
passphrases). Fernet (AES-128-CBC + HMAC-SHA256). The key lives in the environment /
secret manager, never in the database. Rotation: a comma-separated key list; the first
key encrypts, all keys decrypt.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import get_settings


class SecretsUnavailable(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    raw = get_settings().secrets_encryption_key
    if not raw:
        raise SecretsUnavailable("SECRETS_ENCRYPTION_KEY is not configured")
    return MultiFernet([Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()])


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise SecretsUnavailable("secret cannot be decrypted with the configured key") from e


def mask_secret(value: str | None, visible: int = 4) -> str:
    """For logs and API responses: never return the full value."""
    if not value:
        return ""
    return "*" * 8 if len(value) <= visible * 2 else f"{value[:visible]}...{value[-2:]}"
