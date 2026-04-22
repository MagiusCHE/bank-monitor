from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import ParsedFile, ParsedTransaction


_HEADER_ROW = ("Data_Operazione", "Data_Valuta", "Entrate", "Uscite",
               "Descrizione", "Descrizione_Completa", "Stato")


def detect(wb) -> bool:
    try:
        ws = wb["Movimenti"] if "Movimenti" in wb.sheetnames else wb.worksheets[0]
    except Exception:
        return False
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i > 20:
            return False
        if row and isinstance(row[0], str) and row[0].startswith("Conto Corrente:"):
            return True
    return False


def _to_date(v) -> Optional[date]:
    if v is None or v == "-" or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s or s == "-":
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
    return None


def _parse_amount_it(s: str) -> Optional[float]:
    # "62.426,13" -> 62426.13 ; "-1.234,56" -> -1234.56
    if s is None:
        return None
    s = s.strip().replace("\xa0", " ")
    m = re.search(r"-?[\d\.]+,\d+", s)
    if not m:
        m = re.search(r"-?\d+(?:[\.,]\d+)?", s)
        if not m:
            return None
        return float(m.group(0).replace(",", "."))
    num = m.group(0).replace(".", "").replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def parse(wb) -> "ParsedFile":
    from . import ParsedFile, ParsedTransaction

    ws = wb["Movimenti"] if "Movimenti" in wb.sheetnames else wb.worksheets[0]

    account_number: Optional[str] = None
    holder_name: Optional[str] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    initial_balance: Optional[float] = None
    final_balance: Optional[float] = None

    rows = list(ws.iter_rows(values_only=True))

    header_idx = -1
    for i, row in enumerate(rows):
        if not row:
            continue
        first = row[0] if len(row) > 0 else None
        if isinstance(first, str):
            s = first.strip()
            if s.startswith("Conto Corrente:"):
                account_number = s.split(":", 1)[1].strip()
            elif s.startswith("Intestazione Conto Corrente:"):
                holder_name = s.split(":", 1)[1].strip()
            elif s.startswith("Periodo"):
                m = re.search(r"Dal:\s*(\S+)\s*Al:\s*(\S+)", s)
                if m:
                    period_from = _to_date(m.group(1))
                    period_to = _to_date(m.group(2))
            elif "Saldo Iniziale" in s:
                # "Saldo Iniziale: 62.426,13 - \t\t\tSaldo Finale: 67.314,83"
                m_ini = re.search(r"Saldo Iniziale:\s*([0-9\.\,\-]+)", s)
                m_fin = re.search(r"Saldo Finale:\s*([0-9\.\,\-]+)", s)
                if m_ini:
                    initial_balance = _parse_amount_it(m_ini.group(1))
                if m_fin:
                    final_balance = _parse_amount_it(m_fin.group(1))
            elif s == _HEADER_ROW[0]:
                # verifica che sia proprio la riga header attesa
                norm = tuple((c or "").strip() if isinstance(c, str) else c for c in row[:len(_HEADER_ROW)])
                if norm == _HEADER_ROW:
                    header_idx = i
                    break

    if account_number is None or holder_name is None:
        raise ValueError("File Fineco: impossibile leggere numero conto o intestatario")
    if header_idx < 0:
        raise ValueError("File Fineco: riga header movimenti non trovata")

    transactions: list[ParsedTransaction] = []
    for row in rows[header_idx + 1:]:
        if row is None:
            continue
        # righe vuote
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue

        op_raw = row[0]
        value_raw = row[1] if len(row) > 1 else None
        entrate = row[2] if len(row) > 2 else None
        uscite = row[3] if len(row) > 3 else None
        descr = row[4] if len(row) > 4 else None
        descr_full = row[5] if len(row) > 5 else None
        stato = row[6] if len(row) > 6 else None

        value_date = _to_date(value_raw)
        if value_date is None:
            # riga senza data valuta non è una transazione valida
            continue

        op_date = _to_date(op_raw)

        amount: Optional[float] = None
        if entrate is not None and entrate != "":
            amount = float(entrate) if not isinstance(entrate, str) else _parse_amount_it(entrate)
        elif uscite is not None and uscite != "":
            amount = float(uscite) if not isinstance(uscite, str) else _parse_amount_it(uscite)
        if amount is None:
            continue

        description = (descr or "").strip() if isinstance(descr, str) else str(descr or "")
        full_description = None
        if descr_full is not None:
            full_description = descr_full.strip() if isinstance(descr_full, str) else str(descr_full)

        status = (stato or "").strip() if isinstance(stato, str) else str(stato or "")
        if not status:
            status = "Contabilizzato"

        transactions.append(ParsedTransaction(
            op_date=op_date,
            value_date=value_date,
            amount=amount,
            description=description,
            full_description=full_description,
            status=status,
        ))

    return ParsedFile(
        template="fineco",
        account_number=account_number,
        holder_name=holder_name,
        period_from=period_from,
        period_to=period_to,
        initial_balance=initial_balance,
        final_balance=final_balance,
        transactions=transactions,
    )
