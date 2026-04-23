from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .. import db
from ..parsers.paypal import ParsedPayPalFile, PayPalRow


MATCH_WINDOW_DAYS = 7

# Sia gli addebiti SDD sia i bonifici in entrata PayPal citano PayPal Europe (o
# "PayPal (Europe)") in full_description. `%PayPal%Europe%` copre entrambe le forme.
_PAYPAL_DESC_LIKE = "%PayPal%Europe%"


@dataclass
class PayPalIngestResult:
    total_in_file: int           # righe nel CSV
    candidate_rows: int          # righe utili (con merchant) prima del filtro duplicati
    inserted: int                # nuove righe aggiunte al ledger
    skipped_duplicates: int      # già presenti (stesso paypal_tx_code)
    newly_matched: int           # righe ledger linkate a una tx bancaria in questo giro
    unmatched: int               # righe ledger ancora senza match dopo questo giro
    transactions_enriched: int   # transazioni bancarie che hanno ora una enriched_description


def _fmt_merchant(row: sqlite3.Row) -> str:
    d = row["tx_date"]
    # tx_date è ISO YYYY-MM-DD; rendo dd/mm per la visualizzazione
    try:
        y, m, dd = d.split("-")
        short = f"{dd}/{m}"
    except Exception:
        short = d
    return f"{row['merchant']} ({short})"


def _recompute_enriched(conn: sqlite3.Connection, transaction_id: int) -> None:
    """Ricalcola transactions.enriched_description unendo tutti i PayPal ledger righi matchati a quella tx.
    Idempotente: a parità di righe collegate produce sempre la stessa stringa."""
    rows = conn.execute(
        "SELECT tx_date, merchant FROM paypal_ledger "
        "WHERE matched_transaction_id = ? "
        "ORDER BY tx_date, id",
        (transaction_id,),
    ).fetchall()
    if not rows:
        conn.execute("UPDATE transactions SET enriched_description = NULL WHERE id = ?", (transaction_id,))
        return
    parts = [_fmt_merchant(r) for r in rows]
    conn.execute(
        "UPDATE transactions SET enriched_description = ? WHERE id = ?",
        (" + ".join(parts), transaction_id),
    )


def _find_match(conn: sqlite3.Connection, row: PayPalRow) -> Optional[int]:
    """Trova la transazione bancaria candidata per una riga PayPal.
    Chiave: importo esatto + finestra [tx_date, tx_date+7]. Tiebreak: data più vicina.
    Esclude status='Autorizzato'. Esclude tx già matchate da un'altra riga PayPal."""
    start = row.tx_date.isoformat()
    end = (row.tx_date + timedelta(days=MATCH_WINDOW_DAYS)).isoformat()
    amount = round(row.amount, 2)

    # Acquisti (amount < 0) -> SDD PayPal. Rimborsi (amount > 0) -> bonifico SEPA in entrata.
    # In entrambi i casi full_description contiene "PayPal Europe"; basta filtrare per segno e il LIKE.
    q = (
        "SELECT t.id, t.value_date FROM transactions t "
        "WHERE ROUND(t.amount, 2) = ? "
        "  AND t.value_date >= ? AND t.value_date <= ? "
        "  AND (t.status IS NULL OR t.status != 'Autorizzato') "
        "  AND t.full_description LIKE ? "
        "  AND NOT EXISTS (SELECT 1 FROM paypal_ledger p WHERE p.matched_transaction_id = t.id) "
        "ORDER BY ABS(julianday(t.value_date) - julianday(?)) ASC, t.value_date ASC, t.id ASC "
        "LIMIT 1"
    )
    hit = conn.execute(q, (amount, start, end, _PAYPAL_DESC_LIKE, row.tx_date.isoformat())).fetchone()
    return hit["id"] if hit else None


def rematch_pending(conn: sqlite3.Connection) -> tuple[int, set[int]]:
    """Scorre le righe ledger senza match e prova ad agganciarle a una tx bancaria.
    Ritorna (newly_matched_count, set_of_enriched_tx_ids). Lavora sulla conn passata
    (no BEGIN annidato). Ricalcola enriched_description delle tx toccate."""
    newly_matched = 0
    enriched_ids: set[int] = set()

    pending = conn.execute(
        "SELECT id, tx_date, amount FROM paypal_ledger "
        "WHERE matched_transaction_id IS NULL "
        "ORDER BY tx_date ASC, id ASC"
    ).fetchall()

    for pr in pending:
        row = PayPalRow(
            tx_date=date.fromisoformat(pr["tx_date"]),
            tx_time=None, merchant="", type="", status="",
            amount=float(pr["amount"]),
            currency="", paypal_tx_code="", receipt_code=None, note=None,
        )
        tx_id = _find_match(conn, row)
        if tx_id is None:
            continue
        conn.execute(
            "UPDATE paypal_ledger SET matched_transaction_id = ? WHERE id = ?",
            (tx_id, pr["id"]),
        )
        newly_matched += 1
        enriched_ids.add(tx_id)

    for tx_id in enriched_ids:
        _recompute_enriched(conn, tx_id)

    return newly_matched, enriched_ids


def ingest_and_enrich(parsed: ParsedPayPalFile) -> PayPalIngestResult:
    inserted = 0
    skipped = 0

    with db.tx() as conn:
        # 1) Insert idempotente nel ledger.
        for r in parsed.rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO paypal_ledger "
                "(tx_date, tx_time, merchant, type, status, amount, currency, "
                " paypal_tx_code, receipt_code, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r.tx_date.isoformat(),
                    r.tx_time,
                    r.merchant,
                    r.type,
                    r.status,
                    r.amount,
                    r.currency,
                    r.paypal_tx_code,
                    r.receipt_code,
                    r.note,
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

        # 2+3) Matcha le righe ancora senza abbinamento (anche quelle di ri-upload passati).
        newly_matched, enriched_ids = rematch_pending(conn)

        # 4) Quanti ledger restano non matchati in totale (non solo quelli nuovi).
        unmatched = conn.execute(
            "SELECT COUNT(*) AS n FROM paypal_ledger WHERE matched_transaction_id IS NULL"
        ).fetchone()["n"]

    return PayPalIngestResult(
        total_in_file=parsed.total_in_file,
        candidate_rows=len(parsed.rows),
        inserted=inserted,
        skipped_duplicates=skipped,
        newly_matched=newly_matched,
        unmatched=unmatched,
        transactions_enriched=len(enriched_ids),
    )
