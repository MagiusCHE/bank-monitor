from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File

from ..parsers import parse_workbook
from ..services.ingest import ingest

router = APIRouter()


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Il file deve essere un .xlsx")

    data = await file.read()
    try:
        parsed = parse_workbook(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore nel parsing del file: {e}")

    result = ingest(parsed)
    return {
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
