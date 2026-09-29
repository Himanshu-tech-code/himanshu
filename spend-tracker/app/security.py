"""Crypto + auth helpers: token encryption at rest, password hashing, login throttling."""
import time
import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from .config import get_settings

_ph = PasswordHasher()


def _fernet() -> Fernet:
    return Fernet(get_settings().token_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _ph.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


class LoginLimiter:
    """Lock out after N consecutive failures (global + per-client), for a cooldown period."""

    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900):
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.time() - self.lockout_seconds
        self._fails[key] = [t for t in self._fails.get(key, []) if t > cutoff]
        return self._fails[key]

    def blocked(self, *keys: str) -> bool:
        with self._lock:
            return any(len(self._recent(k)) >= self.max_failures for k in keys)

    def record_failure(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._recent(k).append(time.time())

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)
