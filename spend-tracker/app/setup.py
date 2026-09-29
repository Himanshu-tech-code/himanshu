"""One-time setup: generate secrets, hash your password, write .env with 0600 permissions."""
import getpass
import os
import secrets
import sys

from argon2 import PasswordHasher
from cryptography.fernet import Fernet

from .config import BASE_DIR

ENV = BASE_DIR / ".env"


def main():
    if ENV.exists():
        sys.exit(f"{ENV} already exists; delete it first if you really want to regenerate "
                 "(this would make stored bank tokens undecryptable).")
    pw = getpass.getpass("Choose an app password (min 12 chars): ")
    if len(pw) < 12 or pw != getpass.getpass("Repeat: "):
        sys.exit("Password too short or mismatch.")
    cid = input("Plaid client_id (Enter to fill in later): ").strip()
    secret = getpass.getpass("Plaid secret (Enter to fill in later): ").strip()
    env = input("Plaid environment [sandbox/production] (sandbox): ").strip() or "sandbox"
    lines = {
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "APP_PASSWORD_HASH": PasswordHasher().hash(pw),
        "PLAID_CLIENT_ID": cid, "PLAID_SECRET": secret, "PLAID_ENV": env,
    }
    fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        for k, v in lines.items():
            f.write(f"{k}={v}\n" if k != "APP_PASSWORD_HASH" else f"{k}='{v}'\n")
    print(f"Wrote {ENV} (permissions 600). Back up TOKEN_ENCRYPTION_KEY somewhere safe.")


if __name__ == "__main__":
    main()
