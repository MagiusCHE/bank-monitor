from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db

router = APIRouter()


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int) -> dict:
    with db.tx() as conn:
        cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conto non trovato")
    return {"deleted": account_id}
