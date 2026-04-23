from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File

from ..parsers import parse_workbook
from ..parsers import paypal as paypal_parser
from ..services.ingest import ingest
from ..services.paypal import ingest_and_enrich as paypal_ingest

router = APIRouter()


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(status_code=400, detail="Il file deve essere un .xlsx o un .csv (PayPal)")

    data = await file.read()

    if name.endswith(".csv"):
        if not paypal_parser.detect(data):
            raise HTTPException(status_code=400, detail="CSV non riconosciuto come export PayPal")
        try:
            parsed = paypal_parser.parse(data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Errore nel parsing del CSV PayPal: {e}")
        result = paypal_ingest(parsed)
        return {
            "source": "paypal",
            "total_in_file": result.total_in_file,
            "candidate_rows": result.candidate_rows,
            "inserted": result.inserted,
            "skipped_duplicates": result.skipped_duplicates,
            "newly_matched": result.newly_matched,
            "unmatched": result.unmatched,
            "transactions_enriched": result.transactions_enriched,
        }

    try:
        parsed = parse_workbook(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore nel parsing del file: {e}")

    result = ingest(parsed)
    return {
        "source": "bank",
        "template": parsed.template,
        "account": {
            "id": result.account_id,
            "account_number": result.account_number,
            "holder_name": result.holder_name,
            "initial_balance": result.initial_balance,
            "initial_balance_date": result.initial_balance_date,
        },
        "created_account": result.created_account,
        "initial_balance_updated": result.initial_balance_updated,
        "inserted": result.inserted,
        "skipped_duplicates": result.skipped_duplicates,
        "total_in_file": result.total_in_file,
        "period_from": parsed.period_from.isoformat() if parsed.period_from else None,
        "period_to": parsed.period_to.isoformat() if parsed.period_to else None,
    }
