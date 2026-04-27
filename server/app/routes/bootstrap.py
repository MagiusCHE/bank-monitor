from __future__ import annotations

from fastapi import APIRouter

from .. import db

router = APIRouter()


@router.get("/config")
def get_config() -> dict:
    """Bootstrap "leggero": tutto ciò che serve al client per disegnare l'UI di
    selezione conti e i pannelli regole/gruppi. Niente transazioni qui."""
    accounts = db.conn().execute(
        "SELECT a.id, a.account_number, a.holder_name, a.initial_balance, a.initial_balance_date, "
        "       COUNT(t.id) AS transaction_count, "
        "       MIN(t.value_date) AS first_tx, "
        "       MAX(t.value_date) AS last_tx "
        "FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id "
        "GROUP BY a.id ORDER BY a.holder_name, a.account_number"
    ).fetchall()

    tag_rules = db.conn().execute(
        "SELECT id, name, pattern, tag, priority FROM tag_rules ORDER BY priority, id"
    ).fetchall()

    groups = db.conn().execute(
        "SELECT g.id, g.name, g.kind, g.priority, "
        "       COALESCE((SELECT GROUP_CONCAT(tag, ',') FROM group_tags WHERE group_id=g.id), '') AS tags_csv "
        "FROM groups g ORDER BY g.priority, g.id"
    ).fetchall()

    groups_out = []
    for r in groups:
        d = dict(r)
        csv = d.pop("tags_csv") or ""
        d["tags"] = [t for t in csv.split(",") if t]
        groups_out.append(d)

    return {
        "accounts": [dict(r) for r in accounts],
        "tag_rules": [dict(r) for r in tag_rules],
        "groups": groups_out,
    }


@router.get("/transactions/all")
def get_all_transactions() -> list[dict]:
    """Bootstrap "pesante": TUTTE le transazioni di TUTTI i conti, senza filtri.
    Il client tiene questa lista in memoria e calcola filtri/aggregati localmente.
    Include status='Autorizzato' (il client decide se mostrarli o no)."""
    rows = db.conn().execute(
        "SELECT t.id, t.account_id, a.account_number, a.holder_name, "
        "       t.op_date, t.value_date, t.amount, t.description, t.full_description, "
        "       t.enriched_description, t.status "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "ORDER BY t.value_date, t.id"
    ).fetchall()
    return [dict(r) for r in rows]
