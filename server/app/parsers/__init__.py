from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, List, Optional

from openpyxl import load_workbook

from . import fineco


@dataclass
class ParsedTransaction:
    op_date: Optional[date]       # None per movimenti "Autorizzati" senza data operazione
    value_date: date
    amount: float                 # segno: + entrata, - uscita
    description: str
    full_description: Optional[str]
    status: str                   # 'Contabilizzato' | 'Autorizzato' | altro


@dataclass
class ParsedFile:
    template: str                 # es. 'fineco'
    account_number: str
    holder_name: str
    period_from: Optional[date]
    period_to: Optional[date]
    initial_balance: Optional[float]
    final_balance: Optional[float]
    transactions: List[ParsedTransaction]


Detector = Callable[[object], bool]
Parser = Callable[[object], ParsedFile]

REGISTRY: list[tuple[str, Detector, Parser]] = [
    ("fineco", fineco.detect, fineco.parse),
]


def parse_workbook(file_bytes: bytes) -> ParsedFile:
    import io
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    for name, detect, parse in REGISTRY:
        if detect(wb):
            return parse(wb)
    raise ValueError("Formato file non riconosciuto. Template supportati: " + ", ".join(n for n, _, _ in REGISTRY))
