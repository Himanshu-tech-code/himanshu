"""Pull new/changed/removed transactions from Plaid (cursor-based) and store them categorized."""
import logging

from .categorize import categorize
from .db import db
from .plaid_client import PlaidClient, PlaidError
from .security import decrypt

log = logging.getLogger("spend.sync")


def _cents(amount: float) -> int:
    return round(amount * 100)


def load_rules(conn) -> list[tuple[str, str]]:
    return [(r["pattern"], r["category"]) for r in conn.execute("SELECT pattern, category FROM rules ORDER BY id")]


def _fetch_all(plaid: PlaidClient, token: str, cursor: str | None, retries: int = 3) -> dict:
    """Page through /transactions/sync; restart from the original cursor on mid-pagination mutation."""
    for _ in range(retries):
        added, modified, removed, accounts = [], [], [], {}
        cur = cursor
        try:
            while True:
                page = plaid.transactions_sync(token, cur)
                added += page["added"]
                modified += page["modified"]
                removed += page["removed"]
                for a in page.get("accounts", []):
                    accounts[a["account_id"]] = a
                cur = page["next_cursor"]
                if not page["has_more"]:
                    return {"added": added, "modified": modified, "removed": removed,
                            "accounts": list(accounts.values()), "cursor": cur}
        except PlaidError as e:
            if e.code != "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
                raise
    raise PlaidError("SYNC_RETRIES_EXHAUSTED", "data kept changing during pagination")


def sync_item(plaid: PlaidClient, item_id: str) -> dict:
    with db() as conn:
        item = conn.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()
    if item is None:
        raise KeyError(item_id)

    data = _fetch_all(plaid, decrypt(item["access_token_enc"]), item["cursor"])

    with db() as conn:  # single transaction: rows + cursor commit together
        rules = load_rules(conn)
        for a in data["accounts"]:
            conn.execute(
                """INSERT INTO accounts(account_id, item_id, name, mask, type, subtype)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(account_id) DO UPDATE SET name=excluded.name, mask=excluded.mask""",
                (a["account_id"], item_id, a.get("name"), a.get("mask"), a.get("type"), a.get("subtype")),
            )
        for t in data["added"] + data["modified"]:
            pfc = t.get("personal_finance_category") or {}
            category, source = categorize(
                t["name"], t.get("merchant_name"), pfc.get("primary"), pfc.get("detailed"), rules
            )
            conn.execute(
                """INSERT INTO transactions(txn_id, account_id, date, name, merchant, amount_cents, currency,
                                            pending, plaid_primary, plaid_detailed, category, category_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(txn_id) DO UPDATE SET
                     date=excluded.date, name=excluded.name, merchant=excluded.merchant,
                     amount_cents=excluded.amount_cents, pending=excluded.pending,
                     plaid_primary=excluded.plaid_primary, plaid_detailed=excluded.plaid_detailed,
                     category = CASE WHEN category_source='manual' THEN category ELSE excluded.category END,
                     category_source = CASE WHEN category_source='manual' THEN 'manual'
                                            ELSE excluded.category_source END""",
                (t["transaction_id"], t["account_id"], t["date"], t["name"], t.get("merchant_name"),
                 _cents(t["amount"]), t.get("iso_currency_code"), int(t.get("pending", False)),
                 pfc.get("primary"), pfc.get("detailed"), category, source),
            )
        for t in data["removed"]:
            conn.execute("DELETE FROM transactions WHERE txn_id = ?", (t["transaction_id"],))
        conn.execute("UPDATE items SET cursor = ?, last_synced_at = datetime('now') WHERE item_id = ?",
                     (data["cursor"], item_id))

    counts = {k: len(data[k]) for k in ("added", "modified", "removed")}
    log.info("synced item %s: %s", item_id, counts)
    return counts


def sync_all(plaid: PlaidClient) -> dict:
    with db() as conn:
        ids = [r["item_id"] for r in conn.execute("SELECT item_id FROM items")]
    out = {}
    for item_id in ids:
        try:
            out[item_id] = sync_item(plaid, item_id)
        except Exception as e:  # keep going; never log tokens
            log.error("sync failed for %s: %s", item_id, type(e).__name__)
            out[item_id] = {"error": getattr(e, "code", type(e).__name__)}
    return out


def recategorize_all(conn) -> None:
    """Re-run categorization on every non-manual transaction (after rules change)."""
    rules = load_rules(conn)
    for r in conn.execute("SELECT txn_id, name, merchant, plaid_primary, plaid_detailed FROM transactions "
                          "WHERE category_source != 'manual'").fetchall():
        cat, src = categorize(r["name"], r["merchant"], r["plaid_primary"], r["plaid_detailed"], rules)
        conn.execute("UPDATE transactions SET category=?, category_source=? WHERE txn_id=?",
                     (cat, src, r["txn_id"]))
