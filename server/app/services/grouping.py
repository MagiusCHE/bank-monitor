from __future__ import annotations

import re
from typing import Optional

from .. import db


# Fineco nell'export xlsx wrappa la descrizione completa a larghezza fissa
# inserendo uno spazio spurio esattamente ogni N caratteri (N=40 sui campioni osservati).
# Esempio: "Pag. del DD/MM/YY ora HH:MM presso: CONAD SUPERSTORE VIA X ..." →
#          "Pag. del DD/MM/YY ora HH:MM presso: CONA D SUPERSTORE VIA X ..."
_FINECO_WRAP_WIDTH = 40


def dewrap(text: str) -> str:
    if not text:
        return ""
    chars = list(text)
    for pos in range(_FINECO_WRAP_WIDTH, len(chars), _FINECO_WRAP_WIDTH):
        if chars[pos] != " ":
            continue
        left = chars[pos - 1] if pos - 1 >= 0 else ""
        right = chars[pos + 1] if pos + 1 < len(chars) else ""
        if left.isalpha() and right.isalpha():
            chars[pos] = ""
    return "".join(chars)


CompiledRule = tuple[dict, "re.Pattern"]
CompiledGroup = tuple[dict, set[str]]


def compiled_tag_rules() -> list[CompiledRule]:
    rows = db.conn().execute(
        "SELECT id, name, pattern, tag, priority FROM tag_rules ORDER BY priority, id"
    ).fetchall()
    out: list[CompiledRule] = []
    for r in rows:
        try:
            rx = re.compile(r["pattern"])
        except re.error:
            continue
        out.append((dict(r), rx))
    return out


def compiled_groups() -> list[CompiledGroup]:
    rows = db.conn().execute(
        "SELECT g.id, g.name, g.kind, g.priority, "
        "       COALESCE((SELECT GROUP_CONCAT(tag, '\x1f') FROM group_tags WHERE group_id = g.id), '') AS tags "
        "FROM groups g ORDER BY g.priority, g.id"
    ).fetchall()
    out: list[CompiledGroup] = []
    for r in rows:
        d = dict(r)
        tags = set(t for t in d.pop("tags").split("\x1f") if t)
        out.append((d, tags))
    return out


def compute_tags(
    description: Optional[str],
    full_description: Optional[str],
    rules: list[CompiledRule],
) -> list[str]:
    """Ritorna tag ordinati (dedup) applicando tutte le regole che matchano."""
    desc = description or ""
    full = full_description or ""
    haystack = desc + " " + full
    dewrapped = desc + " " + dewrap(full)
    seen: list[str] = []
    s: set[str] = set()
    for rule, rx in rules:
        if rx.search(haystack) or rx.search(dewrapped):
            t = rule["tag"]
            if t not in s:
                s.add(t)
                seen.append(t)
    return seen


def match_group(
    amount: float,
    tags: list[str] | set[str],
    groups: list[CompiledGroup],
) -> Optional[int]:
    """Ritorna id del primo gruppo compatibile (kind + tag-overlap), None altrimenti."""
    if not tags:
        return None
    tag_set = set(tags)
    is_income = amount > 0
    for g, gtags in groups:
        if g["kind"] == "income" and not is_income:
            continue
        if g["kind"] == "expense" and is_income:
            continue
        if gtags & tag_set:
            return g["id"]
    return None
