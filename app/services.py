from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    ClearingReport,
    CurrencyPair,
    Institution,
    InstitutionLimit,
    InstitutionType,
    Quote,
    QuoteStatus,
    Trade,
    TradeDirection,
    TradeStatus,
    TradeType,
)
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
    RejectReasonDistribution,
    TradeCreate,
    TradeOut,
    TradeStatistics,
)


def create_institution(db: Session, data: InstitutionCreate) -> InstitutionOut:
    inst = Institution(**data.model_dump())
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return InstitutionOut.model_validate(inst)


def list_institutions(db: Session, inst_type: Optional[str] = None) -> list[InstitutionOut]:
    q = db.query(Institution)
    if inst_type:
        q = q.filter(Institution.inst_type == inst_type)
    return [InstitutionOut.model_validate(i) for i in q.all()]


def get_institution(db: Session, inst_id: int) -> Optional[InstitutionOut]:
    inst = db.query(Institution).filter(Institution.id == inst_id).first()
    return InstitutionOut.model_validate(inst) if inst else None


def create_currency_pair(db: Session, data: CurrencyPairCreate) -> CurrencyPairOut:
    cp = CurrencyPair(**data.model_dump())
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return CurrencyPairOut.model_validate(cp)


def list_currency_pairs(db: Session) -> list[CurrencyPairOut]:
    return [CurrencyPairOut.model_validate(cp) for cp in db.query(CurrencyPair).all()]


def create_institution_limit(db: Session, data: InstitutionLimitCreate) -> InstitutionLimitOut:
    lim = InstitutionLimit(**data.model_dump(), used_credit=Decimal("0"), net_exposure=Decimal("0"))
    db.add(lim)
    db.commit()
    db.refresh(lim)
    return InstitutionLimitOut.model_validate(lim)


def list_institution_limits(
    db: Session, institution_id: Optional[int] = None
) -> list[InstitutionLimitOut]:
    q = db.query(InstitutionLimit)
    if institution_id:
        q = q.filter(InstitutionLimit.institution_id == institution_id)
    return [InstitutionLimitOut.model_validate(l) for l in q.all()]


def create_quote(db: Session, data: QuoteCreate) -> QuoteOut:
    inst = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not inst or inst.inst_type != InstitutionType.MARKET_MAKER:
        raise ValueError("只有做市商才能挂出报价")
    cp = db.query(CurrencyPair).filter(CurrencyPair.id == data.currency_pair_id).first()
    if not cp:
        raise ValueError("货币对不存在")
    now = datetime.now(timezone.utc)
    quote = Quote(
        institution_id=data.institution_id,
        currency_pair_id=data.currency_pair_id,
        bid_price=data.bid_price,
        ask_price=data.ask_price,
        bid_original=data.bid_amount,
        ask_original=data.ask_amount,
        bid_available=data.bid_amount,
        ask_available=data.ask_amount,
        valid_until=now + timedelta(minutes=data.valid_minutes),
        status=QuoteStatus.ACTIVE,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return QuoteOut.model_validate(quote)


def list_quotes(
    db: Session,
    currency_pair_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[QuoteOut]:
    q = db.query(Quote)
    if currency_pair_id:
        q = q.filter(Quote.currency_pair_id == currency_pair_id)
    if status:
        q = q.filter(Quote.status == status)
    return [QuoteOut.model_validate(qt) for qt in q.all()]


def cancel_quote(db: Session, quote_id: int) -> QuoteOut:
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise ValueError("报价不存在")
    if quote.status != QuoteStatus.ACTIVE:
        raise ValueError(f"报价状态为{quote.status.value}，无法取消")
    quote.status = QuoteStatus.CANCELLED
    db.commit()
    db.refresh(quote)
    return QuoteOut.model_validate(quote)


def create_trade(db: Session, data: TradeCreate) -> TradeOut:
    quote = db.query(Quote).filter(Quote.id == data.quote_id).first()
    if not quote:
        raise ValueError("报价不存在")

    if data.direction == TradeDirection.BUY:
        price = quote.ask_price
    else:
        price = quote.bid_price

    trade = Trade(
        quote_id=data.quote_id,
        initiator_id=data.initiator_id,
        counterparty_id=quote.institution_id,
        currency_pair_id=quote.currency_pair_id,
        direction=data.direction,
        trade_type=data.trade_type,
        trade_date=date.today(),
        forward_date=data.forward_date,
        amount=data.amount,
        price=price,
        status=TradeStatus.QUOTED,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return TradeOut.model_validate(trade)


def submit_trade(db: Session, trade_id: int) -> TradeOut:
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise ValueError("交易不存在")
    if trade.status != TradeStatus.QUOTED:
        raise ValueError(f"交易状态为{trade.status.value}，无法提交撮合")

    trade.status = TradeStatus.PENDING
    db.flush()

    now = datetime.now(timezone.utc)

    quote = db.query(Quote).filter(Quote.id == trade.quote_id).first()
    if quote.status != QuoteStatus.ACTIVE or quote.valid_until.replace(tzinfo=timezone.utc) < now:
        trade.status = TradeStatus.CANCELLED
        trade.reject_reason = "报价已过期或已失效"
        db.commit()
        db.refresh(trade)
        return TradeOut.model_validate(trade)

    if trade.direction == TradeDirection.BUY:
        if trade.amount > quote.ask_available:
            trade.status = TradeStatus.CANCELLED
            trade.reject_reason = (
                f"成交量{trade.amount}超过对手卖出可用额度{quote.ask_available}"
            )
            db.commit()
            db.refresh(trade)
            return TradeOut.model_validate(trade)
    else:
        if trade.amount > quote.bid_available:
            trade.status = TradeStatus.CANCELLED
            trade.reject_reason = (
                f"成交量{trade.amount}超过对手买入可用额度{quote.bid_available}"
            )
            db.commit()
            db.refresh(trade)
            return TradeOut.model_validate(trade)

    initiator_limit = (
        db.query(InstitutionLimit)
        .filter(
            InstitutionLimit.institution_id == trade.initiator_id,
            InstitutionLimit.currency_pair_id == trade.currency_pair_id,
        )
        .first()
    )
    if initiator_limit:
        projected_exposure = abs(initiator_limit.net_exposure + _exposure_delta(trade))
        if projected_exposure > initiator_limit.exposure_limit:
            trade.status = TradeStatus.CANCELLED
            trade.reject_reason = (
                f"本方预计净敞口{projected_exposure}将突破敞口限额"
                f"{initiator_limit.exposure_limit}（当前净敞口"
                f"{initiator_limit.net_exposure}）"
            )
            db.commit()
            db.refresh(trade)
            return TradeOut.model_validate(trade)
        if initiator_limit.used_credit + trade.amount > initiator_limit.credit_limit:
            trade.status = TradeStatus.CANCELLED
            trade.reject_reason = (
                f"本方占用额度{initiator_limit.used_credit + trade.amount}"
                f"将突破授信额度{initiator_limit.credit_limit}"
            )
            db.commit()
            db.refresh(trade)
            return TradeOut.model_validate(trade)

    counterparty_limit = (
        db.query(InstitutionLimit)
        .filter(
            InstitutionLimit.institution_id == trade.counterparty_id,
            InstitutionLimit.currency_pair_id == trade.currency_pair_id,
        )
        .first()
    )
    if counterparty_limit:
        counter_delta = -_exposure_delta(trade)
        projected_cp_exposure = abs(counterparty_limit.net_exposure + counter_delta)
        if projected_cp_exposure > counterparty_limit.exposure_limit:
            trade.status = TradeStatus.CANCELLED
            trade.reject_reason = (
                f"对手方预计净敞口{projected_cp_exposure}将突破敞口限额"
                f"{counterparty_limit.exposure_limit}"
            )
            db.commit()
            db.refresh(trade)
            return TradeOut.model_validate(trade)

    trade.status = TradeStatus.EXECUTED

    if trade.direction == TradeDirection.BUY:
        quote.ask_available -= trade.amount
    else:
        quote.bid_available -= trade.amount

    if quote.ask_available <= 0 and quote.bid_available <= 0:
        quote.status = QuoteStatus.EXPIRED

    if initiator_limit:
        initiator_limit.net_exposure += _exposure_delta(trade)
        initiator_limit.used_credit += trade.amount

    if counterparty_limit:
        counterparty_limit.net_exposure -= _exposure_delta(trade)
        counterparty_limit.used_credit += trade.amount

    db.commit()
    db.refresh(trade)
    return TradeOut.model_validate(trade)


def _exposure_delta(trade: Trade) -> Decimal:
    if trade.direction == TradeDirection.BUY:
        return trade.amount
    return -trade.amount


def cancel_trade(db: Session, trade_id: int) -> TradeOut:
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise ValueError("交易不存在")
    if trade.status not in (TradeStatus.QUOTED, TradeStatus.PENDING):
        raise ValueError(f"交易状态为{trade.status.value}，无法撤销")
    trade.status = TradeStatus.CANCELLED
    trade.reject_reason = "主动撤销"
    db.commit()
    db.refresh(trade)
    return TradeOut.model_validate(trade)


def list_trades(
    db: Session,
    institution_id: Optional[int] = None,
    currency_pair_id: Optional[int] = None,
    status: Optional[str] = None,
    trade_date: Optional[date] = None,
) -> list[TradeOut]:
    q = db.query(Trade)
    if institution_id:
        q = q.filter(
            (Trade.initiator_id == institution_id)
            | (Trade.counterparty_id == institution_id)
        )
    if currency_pair_id:
        q = q.filter(Trade.currency_pair_id == currency_pair_id)
    if status:
        q = q.filter(Trade.status == status)
    if trade_date:
        q = q.filter(Trade.trade_date == trade_date)
    return [TradeOut.model_validate(t) for t in q.all()]


def eod_clearing(
    db: Session,
    trade_date: Optional[date] = None,
    institution_id: Optional[int] = None,
) -> list[ClearingReportOut]:
    if trade_date is None:
        trade_date = date.today()

    if institution_id is not None:
        inst = db.query(Institution).filter(Institution.id == institution_id).first()
        if not inst:
            raise ValueError(f"机构ID={institution_id}不存在")

    existing_reports = db.query(ClearingReport).filter(
        ClearingReport.trade_date == trade_date
    )
    if institution_id is not None:
        existing_reports = existing_reports.filter(
            ClearingReport.institution_id == institution_id
        )
    if existing_reports.first() is not None:
        msg = f"{trade_date}的清算报表已生成"
        if institution_id is not None:
            msg += f"（机构ID={institution_id}）"
        raise ValueError(msg + "，请勿重复清算")

    executed_q = db.query(Trade).filter(Trade.trade_date == trade_date)
    if institution_id is not None:
        executed_q = executed_q.filter(
            (Trade.initiator_id == institution_id)
            | (Trade.counterparty_id == institution_id)
        ).filter(
            Trade.status.in_([TradeStatus.EXECUTED, TradeStatus.CLEARED])
        )
    else:
        executed_q = executed_q.filter(Trade.status == TradeStatus.EXECUTED)
    executed_trades = executed_q.all()

    if not executed_trades:
        return []

    buckets: dict[tuple[int, int], dict] = defaultdict(
        lambda: {"buy": Decimal("0"), "sell": Decimal("0"), "count": 0}
    )

    for t in executed_trades:
        if institution_id is None or t.initiator_id == institution_id:
            key = (t.initiator_id, t.currency_pair_id)
            b = buckets[key]
            if t.direction == TradeDirection.BUY:
                b["buy"] += t.amount
            else:
                b["sell"] += t.amount
            b["count"] += 1

        if institution_id is None or t.counterparty_id == institution_id:
            cp_key = (t.counterparty_id, t.currency_pair_id)
            cb = buckets[cp_key]
            if t.direction == TradeDirection.BUY:
                cb["sell"] += t.amount
            else:
                cb["buy"] += t.amount
            cb["count"] += 1

    reports = []
    clearing_institutions: set[int] = set()
    for (inst_id, cp_id), b in buckets.items():
        report = ClearingReport(
            trade_date=trade_date,
            institution_id=inst_id,
            currency_pair_id=cp_id,
            buy_volume=b["buy"],
            sell_volume=b["sell"],
            net_volume=b["buy"] - b["sell"],
            trade_count=b["count"],
        )
        db.add(report)
        reports.append(report)
        clearing_institutions.add(inst_id)

    for t in executed_trades:
        t.status = TradeStatus.CLEARED

    for inst_id in clearing_institutions:
        inst_reports = [r for r in reports if r.institution_id == inst_id]
        for r in inst_reports:
            lim = (
                db.query(InstitutionLimit)
                .filter(
                    InstitutionLimit.institution_id == inst_id,
                    InstitutionLimit.currency_pair_id == r.currency_pair_id,
                )
                .first()
            )
            if lim is None:
                continue
            released_exposure = r.net_volume
            if abs(released_exposure) <= abs(lim.net_exposure):
                lim.net_exposure -= released_exposure
            else:
                lim.net_exposure = Decimal("0")
            total_volume = r.buy_volume + r.sell_volume
            if total_volume <= lim.used_credit:
                lim.used_credit -= total_volume
            else:
                lim.used_credit = Decimal("0")

    db.commit()
    for r in reports:
        db.refresh(r)
    return [ClearingReportOut.model_validate(r) for r in reports]


def list_clearing_reports(
    db: Session,
    trade_date: Optional[date] = None,
    institution_id: Optional[int] = None,
    currency_pair_id: Optional[int] = None,
) -> list[ClearingReportOut]:
    q = db.query(ClearingReport)
    if trade_date:
        q = q.filter(ClearingReport.trade_date == trade_date)
    if institution_id:
        q = q.filter(ClearingReport.institution_id == institution_id)
    if currency_pair_id:
        q = q.filter(ClearingReport.currency_pair_id == currency_pair_id)
    return [ClearingReportOut.model_validate(r) for r in q.all()]


def get_statistics(
    db: Session,
    institution_id: Optional[int] = None,
    currency_pair_id: Optional[int] = None,
    trade_date: Optional[date] = None,
) -> TradeStatistics:
    q = db.query(Trade)
    if institution_id:
        q = q.filter(
            (Trade.initiator_id == institution_id)
            | (Trade.counterparty_id == institution_id)
        )
    if currency_pair_id:
        q = q.filter(Trade.currency_pair_id == currency_pair_id)
    if trade_date:
        q = q.filter(Trade.trade_date == trade_date)

    trades = q.all()
    total = len(trades)
    executed = [t for t in trades if t.status == TradeStatus.EXECUTED or t.status == TradeStatus.CLEARED]
    cancelled = [t for t in trades if t.status == TradeStatus.CANCELLED]
    volume = sum(t.amount for t in executed)

    reason_map: dict[str, int] = defaultdict(int)
    for t in cancelled:
        if institution_id is not None and t.initiator_id != institution_id:
            continue
        reason = t.reject_reason or "未说明"
        reason_map[reason] += 1

    return TradeStatistics(
        institution_id=institution_id,
        currency_pair_id=currency_pair_id,
        total_trades=total,
        executed_trades=len(executed),
        cancelled_trades=len(cancelled),
        total_volume=volume,
        reject_reasons=[
            RejectReasonDistribution(reject_reason=r, count=c)
            for r, c in sorted(reason_map.items(), key=lambda x: -x[1])
        ],
    )
