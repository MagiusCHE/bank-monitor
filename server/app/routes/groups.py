from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..filters import trading_exclusion_clause
from ..services.grouping import (
    compiled_groups,
    compiled_tag_rules,
    compute_tags,
    match_group,
)

router = APIRouter()


# ---------- Tag rules ----------

class TagRuleIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    pattern: str = Field(..., min_length=1)
    tag: str = Field(..., min_length=1, max_length=50)
    priority: int = 0


@router.get("/tag-rules")
def list_tag_rules() -> list[dict]:
    rows = db.conn().execute(
        "SELECT id, name, pattern, tag, priority FROM tag_rules ORDER BY priority, id"
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/tag-rules")
def create_tag_rule(rule: TagRuleIn) -> dict:
    try:
        re.compile(rule.pattern)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"Regex non valida: {e}")
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO tag_rules (name, pattern, tag, priority) VALUES (?, ?, ?, ?)",
            (rule.name, rule.pattern, rule.tag, rule.priority),
        )
        rid = cur.lastrowid
    return {"id": rid, **rule.model_dump()}


@router.put("/tag-rules/{rule_id}")
def update_tag_rule(rule_id: int, rule: TagRuleIn) -> dict:
    try:
        re.compile(rule.pattern)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"Regex non valida: {e}")
    with db.tx() as conn:
        cur = conn.execute(
            "UPDATE tag_rules SET name=?, pattern=?, tag=?, priority=? WHERE id=?",
            (rule.name, rule.pattern, rule.tag, rule.priority, rule_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Regola non trovata")
    return {"id": rule_id, **rule.model_dump()}


@router.delete("/tag-rules/{rule_id}")
def delete_tag_rule(rule_id: int) -> dict:
    with db.tx() as conn:
        cur = conn.execute("DELETE FROM tag_rules WHERE id=?", (rule_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Regola non trovata")
    return {"deleted": rule_id}


@router.post("/tag-rules/bulk")
def bulk_replace_tag_rules(rules: list[TagRuleIn]) -> dict:
    """Sostituisce l'intera lista di tag_rules in modo atomico."""
    for r in rules:
        try:
            re.compile(r.pattern)
        except re.error as e:
            raise HTTPException(status_code=400, detail=f"Regex non valida in '{r.name}': {e}")
    with db.tx() as conn:
        conn.execute("DELETE FROM tag_rules")
        for r in rules:
            conn.execute(
                "INSERT INTO tag_rules (name, pattern, tag, priority) VALUES (?, ?, ?, ?)",
                (r.name, r.pattern, r.tag, r.priority),
            )
    return {"count": len(rules)}


# ---------- Groups ----------

class GroupIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(..., pattern="^(income|expense|any)$")
    priority: int = 0
    tags: list[str] = Field(default_factory=list)


@router.get("/groups")
def list_groups() -> list[dict]:
    rows = db.conn().execute(
        "SELECT g.id, g.name, g.kind, g.priority, "
        "       COALESCE((SELECT GROUP_CONCAT(tag, ',') FROM group_tags WHERE group_id=g.id), '') AS tags_csv "
        "FROM groups g ORDER BY g.priority, g.id"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        csv = d.pop("tags_csv") or ""
        d["tags"] = [t for t in csv.split(",") if t]
        out.append(d)
    return out


@router.post("/groups")
def create_group(g: GroupIn) -> dict:
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO groups (name, kind, priority) VALUES (?, ?, ?)",
            (g.name, g.kind, g.priority),
        )
        gid = cur.lastrowid
        for t in g.tags:
            conn.execute("INSERT INTO group_tags (group_id, tag) VALUES (?, ?)", (gid, t))
    return {"id": gid, **g.model_dump()}


@router.put("/groups/{group_id}")
def update_group(group_id: int, g: GroupIn) -> dict:
    with db.tx() as conn:
        cur = conn.execute(
            "UPDATE groups SET name=?, kind=?, priority=? WHERE id=?",
            (g.name, g.kind, g.priority, group_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Gruppo non trovato")
        conn.execute("DELETE FROM group_tags WHERE group_id=?", (group_id,))
        for t in g.tags:
            conn.execute("INSERT INTO group_tags (group_id, tag) VALUES (?, ?)", (group_id, t))
    return {"id": group_id, **g.model_dump()}


@router.delete("/groups/{group_id}")
def delete_group(group_id: int) -> dict:
    with db.tx() as conn:
        cur = conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Gruppo non trovato")
    return {"deleted": group_id}


@router.post("/groups/bulk")
def bulk_replace_groups(groups: list[GroupIn]) -> dict:
    """Sostituisce l'intera lista di gruppi (e loro tag) in modo atomico."""
    with db.tx() as conn:
        conn.execute("DELETE FROM group_tags")
        conn.execute("DELETE FROM groups")
        for g in groups:
            cur = conn.execute(
                "INSERT INTO groups (name, kind, priority) VALUES (?, ?, ?)",
                (g.name, g.kind, g.priority),
            )
            gid = cur.lastrowid
            for t in g.tags:
                conn.execute("INSERT INTO group_tags (group_id, tag) VALUES (?, ?)", (gid, t))
    return {"count": len(groups)}


# ---------- Tags (lista distinti) ----------

@router.get("/tags")
def list_tags() -> list[str]:
    """Tag distinti referenziati dalle regole o dai gruppi."""
    rows = db.conn().execute(
        "SELECT tag FROM tag_rules UNION SELECT tag FROM group_tags ORDER BY tag"
    ).fetchall()
    return [r["tag"] for r in rows]


# ---------- Reset ----------

@router.post("/seed")
def reset_seed() -> dict:
    """Wipe tag_rules + groups + group_tags e re-inserisce la seed iniziale."""
    db.reset_to_seed()
    return {"ok": True}


# ---------- Statistiche per gruppo (bar chart) ----------

def _parse_ids(s: Optional[str]) -> Optional[list[int]]:
    # None = parametro assente (tutti i conti); "" = lista vuota esplicita (nessuno)
    if s is None:
        return None
    try:
        return [int(x) for x in s.split(",") if x.strip()]
    except ValueError:
        return None


@router.get("/group-stats")
def group_stats(
    accounts: Optional[str] = Query(None),
    include_authorized: bool = Query(False),
    exclude_trading: bool = Query(False),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict:
    ids = _parse_ids(accounts)
    # Lista esplicitamente vuota = nessun conto -> stats vuote ma comunque con lista gruppi
    if ids is not None and len(ids) == 0:
        groups = compiled_groups()
        return {
            "groups": [
                {"id": g["id"], "name": g["name"], "kind": g["kind"], "tags": sorted(gtags),
                 "count": 0, "total": 0.0,
                 "income_total": 0.0, "expense_abs_total": 0.0,
                 "income_count": 0, "expense_count": 0}
                for g, gtags in groups
            ],
            "uncategorized": {"count": 0, "total": 0.0},
            "uncategorized_income": {"count": 0, "total": 0.0},
            "uncategorized_expense": {"count": 0, "total": 0.0},
        }

    where = ["1=1"]
    args: list = []
    if ids:
        where.append(f"account_id IN ({','.join('?' for _ in ids)})")
        args.extend(ids)
    if not include_authorized:
        where.append("(status IS NULL OR status != 'Autorizzato')")
    if exclude_trading:
        clause, clause_args = trading_exclusion_clause(
            desc_col="description", full_col="full_description"
        )
        where.append(clause)
        args.extend(clause_args)
    if date_from:
        where.append("value_date >= ?")
        args.append(date_from)
    if date_to:
        where.append("value_date <= ?")
        args.append(date_to)

    tx_rows = db.conn().execute(
        "SELECT amount, description, full_description, enriched_description "
        "FROM transactions WHERE " + " AND ".join(where),
        args,
    ).fetchall()

    rules = compiled_tag_rules()
    groups = compiled_groups()
    stats: dict[int, dict] = {
        g["id"]: {
            "id": g["id"], "name": g["name"], "kind": g["kind"], "tags": sorted(gtags),
            "count": 0, "total": 0.0,
            "income_total": 0.0, "expense_abs_total": 0.0,
            "income_count": 0, "expense_count": 0,
        }
        for g, gtags in groups
    }
    uncategorized_income = {"count": 0, "total": 0.0}
    uncategorized_expense = {"count": 0, "total": 0.0}

    for t in tx_rows:
        amount = float(t["amount"])
        tags = compute_tags(t["description"], t["full_description"], rules, t["enriched_description"])
        gid = match_group(amount, tags, groups)
        if gid is None:
            bucket = uncategorized_income if amount >= 0 else uncategorized_expense
            bucket["count"] += 1
            bucket["total"] += amount
        else:
            s = stats[gid]
            s["count"] += 1
            s["total"] += amount
            if amount >= 0:
                s["income_total"] += amount
                s["income_count"] += 1
            else:
                s["expense_abs_total"] += -amount
                s["expense_count"] += 1

    for s in stats.values():
        s["total"] = round(s["total"], 2)
        s["income_total"] = round(s["income_total"], 2)
        s["expense_abs_total"] = round(s["expense_abs_total"], 2)
    uncategorized_income["total"] = round(uncategorized_income["total"], 2)
    uncategorized_expense["total"] = round(uncategorized_expense["total"], 2)

    total_count = uncategorized_income["count"] + uncategorized_expense["count"]
    total_sum = round(uncategorized_income["total"] + uncategorized_expense["total"], 2)

    return {
        "groups": list(stats.values()),
        "uncategorized": {"count": total_count, "total": total_sum},
        "uncategorized_income": uncategorized_income,
        "uncategorized_expense": uncategorized_expense,
    }
