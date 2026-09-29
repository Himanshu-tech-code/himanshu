# Personal Spend Tracker

Self-hosted, single-user spend tracker. Connects to your US/Canada banks via [Plaid](https://plaid.com),
pulls transactions as they post, auto-categorizes them, and lets you correct categories (corrections stick).

## Run it

```bash
cd spend-tracker
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m app.setup                      # creates .env (chmod 600): keys, password hash, Plaid creds
uvicorn app.main:get_app --factory --host 127.0.0.1 --port 8000
# open http://localhost:8000
```

1. Get free Plaid keys at dashboard.plaid.com. Start with `PLAID_ENV=sandbox` (login `user_good` / `pass_good`).
2. For real banks, request Production access for the **Transactions** product, set `PLAID_ENV=production`
   and use the production secret.
3. Tests: `pytest`

## How new transactions arrive

- **Polling (default):** every `SYNC_INTERVAL_MINUTES` (30) while the app runs, plus the "Sync now" button.
- **Webhooks (optional, near-instant):** set `WEBHOOK_URL` to a public HTTPS URL that reaches
  `/api/plaid-webhook` (e.g. a Cloudflare Tunnel / Tailscale Funnel exposing *only* that path).
  Every webhook is verified against Plaid's signed JWT + body SHA-256 before anything happens.

## Security model

| Threat | Mitigation |
|---|---|
| Bank password theft | The app **never sees** your bank credentials. Login happens inside Plaid Link (bank OAuth where supported). |
| Money movement | Only the read-only `transactions` product is requested. No payments/transfer/auth products. |
| Stolen database / backup | Plaid access tokens are Fernet-encrypted (AES-128-CBC+HMAC) in the DB; key lives only in `.env` (0600). DB file is 0600. Use full-disk encryption for the transaction data itself. |
| Unauthorized app access | Argon2id password, 12h session, HttpOnly + SameSite=Strict cookie, CSRF token on every write, login lockout (5 failures → 15 min). |
| Remote/LAN exposure | Binds to `127.0.0.1` by default; Host-header allowlist (blocks DNS rebinding). If you expose it, use HTTPS + `COOKIE_SECURE=true` behind a VPN/tunnel with its own auth. |
| XSS / clickjacking | Strict CSP (only self + cdn.plaid.com), UI renders with `textContent` only, `frame-ancestors 'none'`. |
| Forged webhooks | Signature (ES256) + freshness (5 min) + body-hash verification. |
| Secrets in git | `.env`, `data/` are gitignored. Run `git status` before commits. |
| Leak recovery | "Disconnect" calls Plaid `/item/remove`, revoking the token at the source. Rotate the Plaid secret from the dashboard if `.env` is ever exposed. |

**Do not** publish this folder's `.env` or `data/`. This repo also serves a public GitHub Pages site from
the root; the tracker's code is inert there, but keep secrets out of the repo.

## Categorization

Precedence: **your manual choice** → your rules (merchant contains …) → built-in keyword rules
(`app/categorize.py`) → Plaid's category → "Other". Changing a category prompts "always do this for this
merchant?" which adds a rule and re-categorizes everything non-manual. "Income" and "Transfers" are excluded
from spend totals.

## Layout

`app/plaid_client.py` Plaid calls + webhook verification · `app/sync.py` cursor sync ·
`app/categorize.py` categories/rules · `app/security.py` crypto/auth · `app/main.py` API · `app/static/` UI
