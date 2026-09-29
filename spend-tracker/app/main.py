import json
import logging
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .categorize import CATEGORIES, NON_SPEND
from .config import get_settings
from .db import db, init_db
from .plaid_client import PlaidClient, PlaidError
from .security import LoginLimiter, decrypt, encrypt, verify_password
from .sync import recategorize_all, sync_all, sync_item

log = logging.getLogger("spend")
STATIC = Path(__file__).parent / "static"
limiter = LoginLimiter()
_plaid: PlaidClient | None = None
_plaid_lock = threading.Lock()


def plaid() -> PlaidClient:
    global _plaid
    with _plaid_lock:
        if _plaid is None:
            _plaid = PlaidClient()
        return _plaid


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with db() as conn:  # apply any updated built-in rules to existing, non-manual rows
        recategorize_all(conn)
    stop = threading.Event()

    def poll():  # fallback for when webhooks aren't reachable (typical for a local-only app)
        interval = get_settings().sync_interval_minutes * 60
        while not stop.wait(interval):
            try:
                sync_all(plaid())
            except Exception as e:
                log.error("poll failed: %s", type(e).__name__)

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    yield
    stop.set()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware, secret_key=s.session_secret, session_cookie="spend_session",
        https_only=s.cookie_secure, same_site="strict", max_age=12 * 3600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(s.allowed_hosts))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.plaid.com; "
            "frame-src https://cdn.plaid.com; connect-src 'self'; style-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        if s.cookie_secure:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    register_routes(app)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def require_auth(request: Request):
    if not request.session.get("auth"):
        raise HTTPException(401, "Not authenticated")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(sent, request.session.get("csrf", "")):
            raise HTTPException(403, "Bad CSRF token")


class Login(BaseModel):
    password: str = Field(max_length=256)


class Exchange(BaseModel):
    public_token: str
    institution_name: str = "Bank"


class TxnPatch(BaseModel):
    category: str
    create_rule: bool = False


class RuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=100)
    category: str


def _check_category(c: str):
    if c not in CATEGORIES:
        raise HTTPException(422, "Unknown category")


def register_routes(app: FastAPI):
    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/session")
    def session(request: Request):
        return {"authenticated": bool(request.session.get("auth")), "csrf": request.session.get("csrf")}

    @app.post("/api/login")
    def login(body: Login, request: Request):
        ip = request.client.host if request.client else "unknown"
        if limiter.blocked("global", ip):
            raise HTTPException(429, "Too many attempts. Try again later.")
        if not verify_password(body.password, get_settings().password_hash):
            limiter.record_failure("global", ip)
            raise HTTPException(401, "Invalid password")
        limiter.reset("global", ip)
        request.session.clear()  # fresh session on login
        request.session.update(auth=True, csrf=secrets.token_urlsafe(32))
        return {"csrf": request.session["csrf"]}

    @app.post("/api/logout", dependencies=[Depends(require_auth)])
    def logout(request: Request):
        request.session.clear()
        return {"ok": True}

    @app.get("/api/categories", dependencies=[Depends(require_auth)])
    def categories():
        return CATEGORIES

    # ---- bank connection ----
    @app.post("/api/link-token", dependencies=[Depends(require_auth)])
    def link_token():
        try:
            return {"link_token": plaid().create_link_token()}
        except PlaidError as e:
            raise HTTPException(502, e.code)

    @app.post("/api/exchange", dependencies=[Depends(require_auth)])
    def exchange(body: Exchange, tasks: BackgroundTasks):
        try:
            token, item_id = plaid().exchange_public_token(body.public_token)
        except PlaidError as e:
            raise HTTPException(502, e.code)
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO items(item_id, institution, access_token_enc) VALUES (?,?,?)",
                (item_id, body.institution_name[:100], encrypt(token)),
            )
        tasks.add_task(sync_item, plaid(), item_id)
        return {"item_id": item_id}

    @app.get("/api/accounts", dependencies=[Depends(require_auth)])
    def accounts():
        with db() as conn:
            rows = conn.execute(
                """SELECT i.item_id, i.institution, i.last_synced_at, a.account_id, a.name, a.mask
                   FROM items i LEFT JOIN accounts a USING(item_id) ORDER BY i.institution, a.name"""
            ).fetchall()
        return [dict(r) for r in rows]

    @app.delete("/api/items/{item_id}", dependencies=[Depends(require_auth)])
    def disconnect(item_id: str):
        with db() as conn:
            row = conn.execute("SELECT access_token_enc FROM items WHERE item_id=?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        try:
            plaid().remove_item(decrypt(row["access_token_enc"]))  # revoke access at the bank side
        except PlaidError as e:
            log.warning("item/remove failed: %s", e.code)
        with db() as conn:
            conn.execute("DELETE FROM items WHERE item_id=?", (item_id,))
        return {"ok": True}

    @app.post("/api/sync", dependencies=[Depends(require_auth)])
    def sync_now():
        return sync_all(plaid())

    @app.post("/api/plaid-webhook")
    async def webhook(request: Request, tasks: BackgroundTasks):
        raw = await request.body()
        if not plaid().verify_webhook(raw, request.headers.get("plaid-verification")):
            raise HTTPException(401)
        evt = json.loads(raw)
        if evt.get("webhook_type") == "TRANSACTIONS" and evt.get("webhook_code") == "SYNC_UPDATES_AVAILABLE":
            tasks.add_task(_safe_sync_item, evt.get("item_id"))
        return {"ok": True}

    # ---- data ----
    @app.get("/api/transactions", dependencies=[Depends(require_auth)])
    def transactions(month: str | None = None, category: str | None = None, q: str | None = None,
                     limit: int = 500):
        sql = ("SELECT t.*, a.name AS account_name, a.mask FROM transactions t "
               "JOIN accounts a USING(account_id) WHERE 1=1")
        args: list = []
        if month:
            sql += " AND substr(t.date,1,7) = ?"; args.append(month)
        if category:
            sql += " AND t.category = ?"; args.append(category)
        if q:
            sql += " AND (t.name LIKE ? OR t.merchant LIKE ?)"; args += [f"%{q}%"] * 2
        sql += " ORDER BY t.date DESC, t.txn_id LIMIT ?"; args.append(min(limit, 2000))
        with db() as conn:
            return [dict(r) for r in conn.execute(sql, args)]

    @app.get("/api/summary", dependencies=[Depends(require_auth)])
    def summary(month: str):
        ph = ",".join("?" * len(NON_SPEND))
        with db() as conn:
            rows = conn.execute(
                f"""SELECT category, SUM(amount_cents) AS cents, COUNT(*) AS n FROM transactions
                    WHERE substr(date,1,7)=? AND category NOT IN ({ph})
                    GROUP BY category ORDER BY cents DESC""", (month, *NON_SPEND)).fetchall()
            inc = conn.execute("SELECT COALESCE(-SUM(amount_cents),0) FROM transactions "
                               "WHERE substr(date,1,7)=? AND category='Income'", (month,)).fetchone()[0]
        by_cat = [dict(r) for r in rows]
        return {"month": month, "spend_cents": sum(r["cents"] for r in by_cat),
                "income_cents": inc, "by_category": by_cat}

    @app.get("/api/months", dependencies=[Depends(require_auth)])
    def months():
        with db() as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT substr(date,1,7) m FROM transactions ORDER BY m DESC")]

    @app.patch("/api/transactions/{txn_id}", dependencies=[Depends(require_auth)])
    def patch_txn(txn_id: str, body: TxnPatch):
        _check_category(body.category)
        with db() as conn:
            row = conn.execute("SELECT name, merchant FROM transactions WHERE txn_id=?", (txn_id,)).fetchone()
            if row is None:
                raise HTTPException(404)
            conn.execute("UPDATE transactions SET category=?, category_source='manual' WHERE txn_id=?",
                         (body.category, txn_id))
            if body.create_rule:
                pattern = (row["merchant"] or row["name"]).strip()
                conn.execute("INSERT INTO rules(pattern, category) VALUES (?,?)", (pattern, body.category))
                recategorize_all(conn)
        return {"ok": True}

    @app.get("/api/rules", dependencies=[Depends(require_auth)])
    def rules():
        with db() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM rules ORDER BY id")]

    @app.post("/api/rules", dependencies=[Depends(require_auth)])
    def add_rule(body: RuleIn):
        _check_category(body.category)
        with db() as conn:
            conn.execute("INSERT INTO rules(pattern, category) VALUES (?,?)", (body.pattern.strip(), body.category))
            recategorize_all(conn)
        return {"ok": True}

    @app.delete("/api/rules/{rule_id}", dependencies=[Depends(require_auth)])
    def del_rule(rule_id: int):
        with db() as conn:
            conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
            recategorize_all(conn)
        return {"ok": True}


def _safe_sync_item(item_id: str):
    try:
        sync_item(plaid(), item_id)
    except Exception as e:
        log.error("webhook sync failed: %s", type(e).__name__)


def get_app() -> FastAPI:
    return create_app()
