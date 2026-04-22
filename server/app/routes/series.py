from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from .. import db
from ..filters import trading_exclusion_clause

router = APIRouter()


def _parse_ids(s: Optional[str]) -> Optional[list[int]]:
    if not s:
        return None
    try:
        return [int(x) for x in s.split(",") if x.strip()]
    except ValueError:
        return None


@router.get("/series")
def balance_series(
    accounts: Optional[str] = Query(None, description="CSV di account id; omesso = tutti"),
    mode: str = Query("cumulative", pattern="^(cumulative|per-account)$"),
    include_authorized: bool = Query(False),
    exclude_trading: bool = Query(False, description="Esclude compravendite titoli, dividendi, cedole"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> dict:
    ids = _parse_ids(accounts)

    where = []
    args: list = []
    if ids:
        where.append(f"a.id IN ({','.join('?' for _ in ids)})")
        args.extend(ids)
    if not include_authorized:
        where.append("(t.status IS NULL OR t.status != 'Autorizzato')")
    if exclude_trading:
        clause, clause_args = trading_exclusion_clause()
        # clause tollera NULL su t.description/full_description (quando LEFT JOIN non trova tx)
        where.append(f"(t.id IS NULL OR {clause})")
        args.extend(clause_args)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # Saldo iniziale per conto
    acc_rows = db.conn().execute(
        "SELECT id, account_number, holder_name, initial_balance, initial_balance_date "
        "FROM accounts" + (" WHERE id IN (" + ",".join("?" for _ in ids) + ")" if ids else ""),
        ids or [],
    ).fetchall()
    accounts_info = {r["id"]: dict(r) for r in acc_rows}

    # Transazioni aggregate per giorno e conto
    tx_rows = db.conn().execute(
        "SELECT a.id AS account_id, t.value_date, SUM(t.amount) AS delta "
        "FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id "
        + where_sql +
        " GROUP BY a.id, t.value_date "
        " ORDER BY t.value_date",
        args,
    ).fetchall()

    by_account: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for r in tx_rows:
        if r["value_date"] is None:
            continue
        by_account[r["account_id"]].append((r["value_date"], float(r["delta"])))

    # filtro date lato Python (più semplice)
    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to) if date_to else None

    if mode == "per-account":
        result_accounts = []
        for aid, info in accounts_info.items():
            running = float(info["initial_balance"] or 0.0)
            points: list[dict] = []
            if info["initial_balance_date"]:
                start_date = date.fromisoformat(info["initial_balance_date"])
                points.append({"date": start_date.isoformat(), "balance": running})
            for d_iso, delta in by_account.get(aid, []):
                d = date.fromisoformat(d_iso)
                running += delta
                if (df and d < df) or (dt and d > dt):
                    continue
                points.append({"date": d_iso, "balance": round(running, 2)})
            result_accounts.append({
                "account_id": aid,
                "account_number": info["account_number"],
                "holder_name": info["holder_name"],
                "initial_balance": info["initial_balance"],
                "initial_balance_date": info["initial_balance_date"],
                "points": points,
            })
        return {"mode": "per-account", "accounts": result_accounts}

    # cumulative: somma dei saldi di tutti i conti nel tempo
    # Strategia: costruisco la serie per-account completa, poi allineo su tutte le date osservate
    # e sommo il saldo corrente di ogni conto in quella data (forward-fill).
    all_dates: set[str] = set()
    per_acc_running: dict[int, list[tuple[str, float]]] = {}

    for aid, info in accounts_info.items():
        running = float(info["initial_balance"] or 0.0)
        series: list[tuple[str, float]] = []
        if info["initial_balance_date"]:
            series.append((info["initial_balance_date"], running))
            all_dates.add(info["initial_balance_date"])
        for d_iso, delta in by_account.get(aid, []):
            running += delta
            series.append((d_iso, running))
            all_dates.add(d_iso)
        per_acc_running[aid] = series

    sorted_dates = sorted(all_dates)
    # forward-fill per ogni conto
    cumulative_points: list[dict] = []
    idx = {aid: 0 for aid in per_acc_running}
    last_value = {aid: 0.0 for aid in per_acc_running}
    for d_iso in sorted_dates:
        d = date.fromisoformat(d_iso)
        total = 0.0
        for aid, series in per_acc_running.items():
            while idx[aid] < len(series) and series[idx[aid]][0] <= d_iso:
                last_value[aid] = series[idx[aid]][1]
                idx[aid] += 1
            total += last_value[aid]
        if (df and d < df) or (dt and d > dt):
            continue
        cumulative_points.append({"date": d_iso, "balance": round(total, 2)})

    return {
        "mode": "cumulative",
        "accounts": [
            {"account_id": aid, "account_number": info["account_number"], "holder_name": info["holder_name"]}
            for aid, info in accounts_info.items()
        ],
        "points": cumulative_points,
    }
