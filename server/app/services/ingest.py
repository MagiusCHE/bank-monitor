from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .. import db
from ..parsers import ParsedFile, ParsedTransaction


@dataclass
class IngestResult:
    account_id: int
    account_number: str
    holder_name: str
    created_account: bool
    inserted: int
    skipped_duplicates: int
    total_in_file: int
    initial_balance_updated: bool
    initial_balance: Optional[float]
    initial_balance_date: Optional[str]


def _hash(account_id: int, tx: ParsedTransaction, seq: int) -> str:
    h = hashlib.sha256()
    parts = (
        str(account_id),
        tx.value_date.isoformat(),
        f"{tx.amount:.2f}",
        tx.description or "",
        tx.full_description or "",
        tx.status or "",
        str(seq),
    )
    h.update("\x1f".join(parts).encode("utf-8"))
    return h.hexdigest()


def ingest(parsed: ParsedFile) -> IngestResult:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT id, holder_name, initial_balance, initial_balance_date "
            "FROM accounts WHERE account_number = ?",
            (parsed.account_number,),
        ).fetchone()

        created = False
        initial_balance_updated = False

        if row is None:
            ini_date = parsed.period_from.isoformat() if parsed.period_from else None
            cur = conn.execute(
                "INSERT INTO accounts (account_number, holder_name, initial_balance, initial_balance_date) "
                "VALUES (?, ?, ?, ?)",
                (parsed.account_number, parsed.holder_name, parsed.initial_balance, ini_date),
            )
            account_id = cur.lastrowid
            created = True
            initial_balance_updated = parsed.initial_balance is not None
            current_initial_balance = parsed.initial_balance
            current_initial_date = ini_date
        else:
            account_id = row["id"]
            current_initial_balance = row["initial_balance"]
            current_initial_date = row["initial_balance_date"]

            # aggiorna holder_name se ora è più informativo
            if parsed.holder_name and parsed.holder_name != row["holder_name"]:
                conn.execute(
                    "UPDATE accounts SET holder_name = ? WHERE id = ?",
                    (parsed.holder_name, account_id),
                )

            # aggiorna saldo iniziale se il file ha una data di inizio più vecchia
            if parsed.initial_balance is not None and parsed.period_from is not None:
                new_date = parsed.period_from.isoformat()
                if current_initial_date is None or new_date < current_initial_date:
                    conn.execute(
                        "UPDATE accounts SET initial_balance = ?, initial_balance_date = ? WHERE id = ?",
                        (parsed.initial_balance, new_date, account_id),
                    )
                    current_initial_balance = parsed.initial_balance
                    current_initial_date = new_date
                    initial_balance_updated = True

        # dedup ordinata: per ogni gruppo (value_date, amount, description, full_description, status)
        # assegno seq=0,1,2,... nell'ordine in cui le transazioni appaiono nel file.
        # Se N transazioni identiche sono già nel DB con seq 0..N-1, le righe 0..N-1 del file
        # collideranno sull'hash e verranno saltate; la N-esima (nuova) passerà.
        counters: dict[tuple, int] = defaultdict(int)
        inserted = 0
        skipped = 0

        for t in parsed.transactions:
            key = (
                t.value_date.isoformat(),
                round(t.amount, 2),
                t.description or "",
                t.full_description or "",
                t.status or "",
            )
            seq = counters[key]
            counters[key] += 1
            dedup = _hash(account_id, t, seq)

            try:
                conn.execute(
                    "INSERT INTO transactions "
                    "(account_id, op_date, value_date, amount, description, full_description, status, seq, dedup_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        account_id,
                        t.op_date.isoformat() if t.op_date else None,
                        t.value_date.isoformat(),
                        t.amount,
                        t.description,
                        t.full_description,
                        t.status,
                        seq,
                        dedup,
                    ),
                )
                inserted += 1
            except Exception as e:
                # IntegrityError su dedup_hash -> duplicato, skippa
                if "UNIQUE" in str(e):
                    skipped += 1
                else:
                    raise

        return IngestResult(
            account_id=account_id,
            account_number=parsed.account_number,
            holder_name=parsed.holder_name,
            created_account=created,
            inserted=inserted,
            skipped_duplicates=skipped,
            total_in_file=len(parsed.transactions),
            initial_balance_updated=initial_balance_updated,
            initial_balance=current_initial_balance,
            initial_balance_date=current_initial_date,
        )
