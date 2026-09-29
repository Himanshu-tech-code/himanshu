import os

import pytest
from cryptography.fernet import Fernet

from argon2 import PasswordHasher

os.environ.update(
    SESSION_SECRET="test-secret", TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    APP_PASSWORD_HASH=PasswordHasher().hash("correct horse battery"),
    PLAID_CLIENT_ID="id", PLAID_SECRET="sec", ALLOWED_HOSTS="testserver,localhost",
)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    from app import config, main
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    config.get_settings.cache_clear()
    main.limiter.__init__()
    from app.db import init_db
    init_db()
    yield
    config.get_settings.cache_clear()
