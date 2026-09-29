"""Minimal read-only Plaid client. Only the Transactions product is ever requested."""
import hashlib
import hmac
import time

import httpx
import jwt

from .config import get_settings


class PlaidError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class PlaidClient:
    def __init__(self, http: httpx.Client | None = None):
        s = get_settings()
        if not (s.plaid_client_id and s.plaid_secret):
            raise RuntimeError("PLAID_CLIENT_ID / PLAID_SECRET not configured")
        self._http = http or httpx.Client(
            base_url=s.plaid_base_url,
            timeout=30,
            headers={"PLAID-CLIENT-ID": s.plaid_client_id, "PLAID-SECRET": s.plaid_secret},
        )
        self._key_cache: dict[str, dict] = {}

    def _post(self, path: str, body: dict) -> dict:
        r = self._http.post(path, json=body)
        data = r.json()
        if r.status_code != 200:
            raise PlaidError(data.get("error_code", "UNKNOWN"), data.get("error_message", "request failed"))
        return data

    def create_link_token(self, client_user_id: str = "owner") -> str:
        s = get_settings()
        body = {
            "client_name": "Personal Spend Tracker",
            "language": "en",
            "country_codes": list(s.country_codes),
            "user": {"client_user_id": client_user_id},
            "products": ["transactions"],
        }
        if s.webhook_url:
            body["webhook"] = s.webhook_url
        return self._post("/link/token/create", body)["link_token"]

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        d = self._post("/item/public_token/exchange", {"public_token": public_token})
        return d["access_token"], d["item_id"]

    def transactions_sync(self, access_token: str, cursor: str | None) -> dict:
        body = {"access_token": access_token, "count": 500}
        if cursor:
            body["cursor"] = cursor
        return self._post("/transactions/sync", body)

    def remove_item(self, access_token: str) -> None:
        self._post("/item/remove", {"access_token": access_token})

    # --- webhook verification (https://plaid.com/docs/api/webhooks/webhook-verification/) ---
    def _verification_key(self, kid: str) -> dict:
        if kid not in self._key_cache:
            self._key_cache[kid] = self._post("/webhook_verification_key/get", {"key_id": kid})["key"]
        return self._key_cache[kid]

    def verify_webhook(self, body: bytes, token: str | None) -> bool:
        if not token:
            return False
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "ES256" or not header.get("kid"):
                return False
            jwk = self._verification_key(header["kid"])
            key = jwt.PyJWK(jwk).key
            claims = jwt.decode(token, key, algorithms=["ES256"], options={"verify_aud": False})
            if time.time() - claims.get("iat", 0) > 300:
                return False
            expected = claims.get("request_body_sha256", "")
            return hmac.compare_digest(expected, hashlib.sha256(body).hexdigest())
        except Exception:
            return False
