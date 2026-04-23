from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional


@dataclass
class PayPalRow:
    tx_date: date
    tx_time: Optional[str]
    merchant: str
    type: str
    status: str
    amount: float
    currency: str
    paypal_tx_code: str
    receipt_code: Optional[str]
    note: Optional[str]


@dataclass
class ParsedPayPalFile:
    rows: List[PayPalRow]
    total_in_file: int  # righe lette dal CSV prima del filtro "solo merchant"


_EXPECTED_HEADERS = {
    "Data", "Orario", "Nome", "Tipo", "Stato", "Valuta",
    "Importo", "Codice transazione",
}


def _decode(data: bytes) -> str:
    # PayPal esporta UTF-8 con BOM; gestiamo anche UTF-8 puro.
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def detect(data: bytes) -> bool:
    try:
        text = _decode(data[:4096])
        first_line = text.splitlines()[0] if text else ""
    except Exception:
        return False
    headers = {h.strip().strip('"') for h in first_line.split(",")}
    return _EXPECTED_HEADERS.issubset(headers)


def _parse_amount(s: str) -> float:
    # "1.234,56" -> 1234.56 ; "-107,84" -> -107.84
    s = (s or "").strip().replace(".", "").replace(",", ".")
    if not s:
        return 0.0
    return float(s)


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


def parse(data: bytes) -> ParsedPayPalFile:
    text = _decode(data)
    reader = csv.DictReader(io.StringIO(text))
    rows: List[PayPalRow] = []
    total = 0
    for raw in reader:
        total += 1
        merchant = (raw.get("Nome") or "").strip()
        code = (raw.get("Codice transazione") or "").strip()
        if not code:
            continue
        # Le righe "tecniche" PayPal (bonifico sul conto, trasferimento avviato)
        # hanno Nome vuoto: sono contropartite interne, non utili per l'enrichment.
        if not merchant:
            continue
        try:
            d = _parse_date(raw.get("Data", ""))
            amt = _parse_amount(raw.get("Importo", ""))
        except Exception:
            continue
        rows.append(PayPalRow(
            tx_date=d,
            tx_time=(raw.get("Orario") or "").strip() or None,
            merchant=merchant,
            type=(raw.get("Tipo") or "").strip(),
            status=(raw.get("Stato") or "").strip(),
            amount=amt,
            currency=(raw.get("Valuta") or "EUR").strip() or "EUR",
            paypal_tx_code=code,
            receipt_code=((raw.get("Codice ricevuta") or "").strip() or None),
            note=((raw.get("Descrizione") or "").strip() or None),
        ))
    return ParsedPayPalFile(rows=rows, total_in_file=total)
