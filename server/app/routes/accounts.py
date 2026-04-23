from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..filters import trading_exclusion_clause
from ..services.grouping import (
    compiled_groups,
    compiled_tag_rules,
    compute_tags,
    match_group,
)

router = APIRouter()


def _parse_ids(s: Optional[str]) -> Optional[list[int]]:
    # None = parametro assente (tutti i conti); "" = lista vuota esplicita (nessuno)
    if s is None:
        return None
    try:
        return [int(x) for x in s.split(",") if x.strip()]
    except ValueError:
        return None


@router.get("/transactions")
def list_transactions(
    accounts: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="Data esatta (YYYY-MM-DD) — se omessa usa date_from/date_to"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    include_authorized: bool = Query(False),
    exclude_trading: bool = Query(False),
    group_id: Optional[int] = Query(None, description="Filtra per gruppo. 0 = non classificati (nessun gruppo matcha)"),
    uncategorized_kind: Optional[str] = Query(None, pattern="^(income|expense)$",
                                              description="Con group_id=0, filtra solo entrate o solo uscite"),
    untagged: bool = Query(False, description="Solo transazioni che non hanno alcun tag"),
    limit: int = Query(500, ge=1, le=5000),
) -> list[dict]:
    ids = _parse_ids(accounts)
    # Lista esplicitamente vuota = nessun conto -> risposta vuota
    if ids is not None and len(ids) == 0:
        return []
    where: list[str] = ["1=1"]
    args: list = []
    if ids:
        where.append(f"t.account_id IN ({','.join('?' for _ in ids)})")
        args.extend(ids)
    if date:
        where.append("t.value_date = ?")
        args.append(date)
    else:
        if date_from:
            where.append("t.value_date >= ?")
            args.append(date_from)
        if date_to:
            where.append("t.value_date <= ?")
            args.append(date_to)
    if not include_authorized:
        where.append("(t.status IS NULL OR t.status != 'Autorizzato')")
    if exclude_trading:
        clause, clause_args = trading_exclusion_clause()
        where.append(clause)
        args.extend(clause_args)

    rows = db.conn().execute(
        "SELECT t.id, t.account_id, a.account_number, a.holder_name, "
        "       t.op_date, t.value_date, t.amount, t.description, t.full_description, t.status "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE " + " AND ".join(where) +
        " ORDER BY t.value_date DESC, ABS(t.amount) DESC LIMIT ?",
        args + [limit],
    ).fetchall()

    rules = compiled_tag_rules()
    groups = compiled_groups() if (group_id is not None) else None

    out: list[dict] = []
    for r in rows:
        d = dict(r)
        tags = compute_tags(r["description"], r["full_description"], rules)
        d["tags"] = tags

        if untagged and tags:
            continue

        if group_id is not None:
            gid = match_group(float(r["amount"]), tags, groups)
            if group_id == 0:
                if gid is not None:
                    continue
                if uncategorized_kind == "income" and r["amount"] < 0:
                    continue
                if uncategorized_kind == "expense" and r["amount"] >= 0:
                    continue
            elif gid != group_id:
                continue

        out.append(d)
    return out


@router.get("/accounts")
def list_accounts() -> list[dict]:
    rows = db.conn().execute(
        "SELECT a.id, a.account_number, a.holder_name, a.initial_balance, a.initial_balance_date, "
        "       COUNT(t.id) AS transaction_count, "
        "       MIN(t.value_date) AS first_tx, "
        "       MAX(t.value_date) AS last_tx "
        "FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id "
        "GROUP BY a.id ORDER BY a.holder_name, a.account_number"
    ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int) -> dict:
    with db.tx() as conn:
        cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conto non trovato")
    return {"deleted": account_id}
