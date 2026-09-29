import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main, sync
from app.categorize import categorize
from app.config import get_settings
from app.db import db
from app.plaid_client import PlaidError
from app.security import decrypt, encrypt


def txn(id, name, amount, primary=None, merchant=None, date="2026-09-10", pending=False):
    return {"transaction_id": id, "account_id": "acc1", "name": name, "merchant_name": merchant,
            "amount": amount, "date": date, "iso_currency_code": "USD", "pending": pending,
            "personal_finance_category": {"primary": primary, "detailed": None} if primary else None}


class FakePlaid:
    def __init__(self, pages):
        self.pages, self.i = pages, 0
    def transactions_sync(self, token, cursor):
        assert token == "access-secret"
        p = self.pages[self.i]; self.i += 1
        if isinstance(p, Exception):
            raise p
        return p
    def verify_webhook(self, body, token):
        return False


def page(added=(), modified=(), removed=(), more=False, cursor="c1"):
    return {"added": list(added), "modified": list(modified), "removed": list(removed), "has_more": more,
            "next_cursor": cursor, "accounts": [{"account_id": "acc1", "name": "Checking", "mask": "1234"}]}


def add_item():
    with db() as c:
        c.execute("INSERT INTO items(item_id, institution, access_token_enc) VALUES ('it1','Bank',?)",
                  (encrypt("access-secret"),))


def test_token_encrypted_at_rest():
    add_item()
    raw = sqlite3.connect(get_settings().db_path).execute("SELECT access_token_enc FROM items").fetchone()[0]
    assert "access-secret" not in raw and decrypt(raw) == "access-secret"


def test_categorize_precedence():
    assert categorize("STARBUCKS #12", None, None, None, [])[0] == "Dining"
    assert categorize("STARBUCKS #12", None, None, None, [("starbucks", "Entertainment")]) == ("Entertainment", "rule")
    assert categorize("ACME LLC", None, "MEDICAL", None, []) == ("Health", "plaid")
    assert categorize("ACME LLC", None, None, None, []) == ("Other", "default")
    assert categorize("AUTOMATIC PAYMENT - THANK", None, "LOAN_PAYMENTS", None, [])[0] == "Transfers"
    assert categorize("CITI", None, "LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT", [])[0] == "Transfers"


def test_sync_paginates_and_preserves_manual_category():
    add_item()
    sync.sync_item(FakePlaid([page([txn("t1", "WHOLE FOODS", 50.25)], more=True, cursor="a"),
                              page([txn("t2", "PAYROLL", -2000, "INCOME")], cursor="b")]), "it1")
    with db() as c:
        rows = {r["txn_id"]: r for r in c.execute("SELECT * FROM transactions")}
        assert rows["t1"]["amount_cents"] == 5025 and rows["t1"]["category"] == "Groceries"
        assert rows["t2"]["category"] == "Income"
        assert c.execute("SELECT cursor FROM items").fetchone()[0] == "b"
        c.execute("UPDATE transactions SET category='Health', category_source='manual' WHERE txn_id='t1'")
    sync.sync_item(FakePlaid([page(modified=[txn("t1", "WHOLE FOODS", 51.00)], removed=[{"transaction_id": "t2"}])]), "it1")
    with db() as c:
        r = c.execute("SELECT * FROM transactions").fetchall()
        assert len(r) == 1 and r[0]["category"] == "Health" and r[0]["amount_cents"] == 5100


def test_sync_restarts_on_mutation_error():
    add_item()
    err = PlaidError("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION", "x")
    sync.sync_item(FakePlaid([page([txn("t1", "A", 1)], more=True), err, page([txn("t1", "A", 1)])]), "it1")
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


@pytest.fixture
def client():
    main._plaid = FakePlaid([])
    return TestClient(main.create_app(), base_url="http://localhost")


def login(c):
    r = c.post("/api/login", json={"password": "correct horse battery"})
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf"]}


def test_auth_required(client):
    assert client.get("/api/transactions").status_code == 401
    assert client.get("/api/accounts").status_code == 401


def test_csrf_enforced(client):
    h = login(client)
    assert client.post("/api/rules", json={"pattern": "abc", "category": "Dining"}).status_code == 403
    assert client.post("/api/rules", json={"pattern": "abc", "category": "Dining"}, headers=h).status_code == 200
    assert client.post("/api/rules", json={"pattern": "abc", "category": "Nope"}, headers=h).status_code == 422


def test_login_lockout(client):
    for _ in range(5):
        assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 429


def test_webhook_rejects_unsigned(client):
    assert client.post("/api/plaid-webhook", json={"webhook_type": "TRANSACTIONS"}).status_code == 401


def test_host_header_and_headers(client):
    assert client.get("/", headers={"host": "evil.com"}).status_code == 400
    r = client.get("/")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_manual_recategorize_creates_rule(client):
    h = login(client)
    add_item()
    sync.sync_item(FakePlaid([page([txn("t1", "ACME CORP 991", 9.99), txn("t2", "ACME CORP 992", 5)])]), "it1")
    assert client.patch("/api/transactions/t1", json={"category": "Education", "create_rule": True}, headers=h).status_code == 200
    cats = {t["txn_id"]: t["category"] for t in client.get("/api/transactions").json()}
    assert cats["t1"] == "Education"   # manual
