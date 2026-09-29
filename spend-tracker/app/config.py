import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PLAID_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


def _req(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing required setting {name}. Run `python -m app.setup`.")
    return val


@dataclass(frozen=True)
class Settings:
    session_secret: str
    token_key: str
    password_hash: str
    plaid_client_id: str
    plaid_secret: str
    plaid_env: str
    db_path: Path
    cookie_secure: bool
    allowed_hosts: tuple
    webhook_url: str
    sync_interval_minutes: int
    country_codes: tuple

    @property
    def plaid_base_url(self) -> str:
        return PLAID_URLS[self.plaid_env]


@lru_cache
def get_settings() -> Settings:
    env = os.environ.get("PLAID_ENV", "sandbox").strip().lower()
    if env not in PLAID_URLS:
        raise RuntimeError("PLAID_ENV must be 'sandbox' or 'production'")
    return Settings(
        session_secret=_req("SESSION_SECRET"),
        token_key=_req("TOKEN_ENCRYPTION_KEY"),
        password_hash=_req("APP_PASSWORD_HASH"),
        plaid_client_id=os.environ.get("PLAID_CLIENT_ID", "").strip(),
        plaid_secret=os.environ.get("PLAID_SECRET", "").strip(),
        plaid_env=env,
        db_path=Path(os.environ.get("DB_PATH", BASE_DIR / "data" / "spend.db")),
        cookie_secure=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        allowed_hosts=tuple(
            h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
        ),
        webhook_url=os.environ.get("WEBHOOK_URL", "").strip(),
        sync_interval_minutes=int(os.environ.get("SYNC_INTERVAL_MINUTES", "30")),
        country_codes=tuple(c.strip() for c in os.environ.get("PLAID_COUNTRY_CODES", "US,CA").split(",")),
    )
