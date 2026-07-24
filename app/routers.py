from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ClearingReportOut,
    CurrencyPairCreate,
    CurrencyPairOut,
    InstitutionCreate,
    InstitutionLimitCreate,
    InstitutionLimitOut,
    InstitutionOut,
    QuoteCreate,
    QuoteOut,
    TradeCreate,
    TradeOut,
    TradeStatistics,
)
from app import services

router = APIRouter()


@router.post("/institutions", response_model=InstitutionOut)
def api_create_institution(data: InstitutionCreate, db: Session = Depends(get_db)):
    try:
        return services.create_institution(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/institutions", response_model=list[InstitutionOut])
def api_list_institutions(
    inst_type: Optional[str] = Query(None), db: Session = Depends(get_db)
):
    return services.list_institutions(db, inst_type)


@router.get("/institutions/{inst_id}", response_model=InstitutionOut)
def api_get_institution(inst_id: int, db: Session = Depends(get_db)):
    result = services.get_institution(db, inst_id)
    if not result:
        raise HTTPException(status_code=404, detail="机构不存在")
    return result


@router.post("/currency-pairs", response_model=CurrencyPairOut)
def api_create_currency_pair(data: CurrencyPairCreate, db: Session = Depends(get_db)):
    try:
        return services.create_currency_pair(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/currency-pairs", response_model=list[CurrencyPairOut])
def api_list_currency_pairs(db: Session = Depends(get_db)):
    return services.list_currency_pairs(db)


@router.post("/institution-limits", response_model=InstitutionLimitOut)
def api_create_institution_limit(
    data: InstitutionLimitCreate, db: Session = Depends(get_db)
):
    try:
        return services.create_institution_limit(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/institution-limits", response_model=list[InstitutionLimitOut])
def api_list_institution_limits(
    institution_id: Optional[int] = Query(None), db: Session = Depends(get_db)
):
    return services.list_institution_limits(db, institution_id)


@router.post("/quotes", response_model=QuoteOut)
def api_create_quote(data: QuoteCreate, db: Session = Depends(get_db)):
    try:
        return services.create_quote(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/quotes", response_model=list[QuoteOut])
def api_list_quotes(
    currency_pair_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return services.list_quotes(db, currency_pair_id, status)


@router.post("/quotes/{quote_id}/cancel", response_model=QuoteOut)
def api_cancel_quote(quote_id: int, db: Session = Depends(get_db)):
    try:
        return services.cancel_quote(db, quote_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trades", response_model=TradeOut)
def api_create_trade(data: TradeCreate, db: Session = Depends(get_db)):
    try:
        return services.create_trade(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trades/{trade_id}/submit", response_model=TradeOut)
def api_submit_trade(trade_id: int, db: Session = Depends(get_db)):
    try:
        return services.submit_trade(db, trade_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trades/{trade_id}/cancel", response_model=TradeOut)
def api_cancel_trade(trade_id: int, db: Session = Depends(get_db)):
    try:
        return services.cancel_trade(db, trade_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trades", response_model=list[TradeOut])
def api_list_trades(
    institution_id: Optional[int] = Query(None),
    currency_pair_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    trade_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    return services.list_trades(db, institution_id, currency_pair_id, status, trade_date)


@router.post("/clearing/eod", response_model=list[ClearingReportOut])
def api_eod_clearing(
    trade_date: Optional[date] = Query(None),
    institution_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    try:
        return services.eod_clearing(db, trade_date, institution_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/clearing/reports", response_model=list[ClearingReportOut])
def api_list_clearing_reports(
    trade_date: Optional[date] = Query(None),
    institution_id: Optional[int] = Query(None),
    currency_pair_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    return services.list_clearing_reports(db, trade_date, institution_id, currency_pair_id)


@router.get("/statistics", response_model=TradeStatistics)
def api_get_statistics(
    institution_id: Optional[int] = Query(None),
    currency_pair_id: Optional[int] = Query(None),
    trade_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    return services.get_statistics(db, institution_id, currency_pair_id, trade_date)
