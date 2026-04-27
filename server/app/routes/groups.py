from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db

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
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO tag_rules (name, pattern, tag, priority) VALUES (?, ?, ?, ?)",
            (rule.name, rule.pattern, rule.tag, rule.priority),
        )
        rid = cur.lastrowid
    return {"id": rid, **rule.model_dump()}


@router.put("/tag-rules/{rule_id}")
def update_tag_rule(rule_id: int, rule: TagRuleIn) -> dict:
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
    """Sostituisce l'intera lista di tag_rules in modo atomico.
    La validazione delle regex è responsabilità del client (Tauri/JS): il server
    accetta qualsiasi pattern testuale e si limita allo storage."""
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
    """Tag distinti referenziati dalle regole o dai gruppi.

    Tenuto vivo per evolutivi futuri (es. tag pre-calcolati lato server quando il
    DB cambia, così il client non li ricalcola ad ogni bootstrap). Il client
    attuale costruisce comunque la lista dai dati in memoria."""
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
