from __future__ import annotations

# Pattern SQL LIKE-based per escludere transazioni di trading (compravendita titoli,
# dividendi, cedole, rimborsi titoli). Usato da /api/series e /api/transactions
# quando exclude_trading=true.
# SQLite non ha REGEXP di default: uso LIKE su keyword. Copre Fineco.
_TRADING_KEYWORDS = [
    # NB: niente 'compravendita' generico: compare anche in "SALDO IMMOBILE OGGETTO
    # DI COMPRAVENDITA". Le vere compravendite titoli Fineco hanno sempre 'titoli'.
    "titoli",
    "dividend",
    "cedol",
    "rimborso titoli",
]


def trading_exclusion_clause(
    desc_col: str = "t.description",
    full_col: str = "t.full_description",
) -> tuple[str, list]:
    """Ritorna (sql_fragment, args) da AND-are in una WHERE per escludere le transazioni
    di trading basandosi su description + full_description.
    """
    parts: list[str] = []
    args: list = []
    for kw in _TRADING_KEYWORDS:
        parts.append(f"LOWER(COALESCE({desc_col}, '')) NOT LIKE ?")
        args.append(f"%{kw}%")
        parts.append(f"LOWER(COALESCE({full_col}, '')) NOT LIKE ?")
        args.append(f"%{kw}%")
    return "(" + " AND ".join(parts) + ")", args
