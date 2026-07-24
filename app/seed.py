from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, Base
from app.models import (
    Institution,
    InstitutionType,
    CurrencyPair,
    InstitutionLimit,
)
from app import services
from app.schemas import (
    InstitutionCreate,
    CurrencyPairCreate,
    InstitutionLimitCreate,
    QuoteCreate,
    TradeCreate,
)
from app.models import TradeDirection, TradeType


def seed():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    try:
        if db.query(Institution).first():
            print("种子数据已存在，跳过")
            return

        print("=== 创建参与机构 ===")
        hsbc = services.create_institution(
            db,
            InstitutionCreate(
                code="HSBC",
                name="汇丰银行（上海自贸区支行）",
                inst_type=InstitutionType.MARKET_MAKER,
                country="UK",
            ),
        )
        boc = services.create_institution(
            db,
            InstitutionCreate(
                code="BOC",
                name="中国银行（上海自贸区分行）",
                inst_type=InstitutionType.DOMESTIC_BANK,
                country="CN",
            ),
        )
        cbi = services.create_institution(
            db,
            InstitutionCreate(
                code="CITI",
                name="花旗银行（上海自贸区支行）",
                inst_type=InstitutionType.FOREIGN_BANK,
                country="US",
            ),
        )
        spdb = services.create_institution(
            db,
            InstitutionCreate(
                code="SPDB",
                name="浦发银行（上海自贸区分行）",
                inst_type=InstitutionType.DOMESTIC_BANK,
                country="CN",
            ),
        )
        print(f"  做市商: {hsbc.name} (id={hsbc.id})")
        print(f"  境内银行: {boc.name} (id={boc.id}), {spdb.name} (id={spdb.id})")
        print(f"  境外银行: {cbi.name} (id={cbi.id})")

        print("\n=== 创建货币对 ===")
        usd_cnh = services.create_currency_pair(
            db,
            CurrencyPairCreate(symbol="USD/CNH", base_currency="USD", quote_currency="CNH"),
        )
        eur_cnh = services.create_currency_pair(
            db,
            CurrencyPairCreate(symbol="EUR/CNH", base_currency="EUR", quote_currency="CNH"),
        )
        gbp_cnh = services.create_currency_pair(
            db,
            CurrencyPairCreate(symbol="GBP/CNH", base_currency="GBP", quote_currency="CNH"),
        )
        print(f"  {usd_cnh.symbol} (id={usd_cnh.id})")
        print(f"  {eur_cnh.symbol} (id={eur_cnh.id})")
        print(f"  {gbp_cnh.symbol} (id={gbp_cnh.id})")

        print("\n=== 设置授信额度和敞口限额 ===")
        services.create_institution_limit(
            db,
            InstitutionLimitCreate(
                institution_id=hsbc.id,
                currency_pair_id=usd_cnh.id,
                credit_limit=Decimal("5000000"),
                exposure_limit=Decimal("3000000"),
            ),
        )
        services.create_institution_limit(
            db,
            InstitutionLimitCreate(
                institution_id=hsbc.id,
                currency_pair_id=eur_cnh.id,
                credit_limit=Decimal("3000000"),
                exposure_limit=Decimal("2000000"),
            ),
        )
        services.create_institution_limit(
            db,
            InstitutionLimitCreate(
                institution_id=boc.id,
                currency_pair_id=usd_cnh.id,
                credit_limit=Decimal("2000000"),
                exposure_limit=Decimal("1000000"),
            ),
        )
        services.create_institution_limit(
            db,
            InstitutionLimitCreate(
                institution_id=cbi.id,
                currency_pair_id=usd_cnh.id,
                credit_limit=Decimal("500000"),
                exposure_limit=Decimal("300000"),
            ),
        )
        services.create_institution_limit(
            db,
            InstitutionLimitCreate(
                institution_id=spdb.id,
                currency_pair_id=usd_cnh.id,
                credit_limit=Decimal("1500000"),
                exposure_limit=Decimal("800000"),
            ),
        )
        services.create_institution_limit(
            db,
            InstitutionLimitCreate(
                institution_id=spdb.id,
                currency_pair_id=eur_cnh.id,
                credit_limit=Decimal("1000000"),
                exposure_limit=Decimal("600000"),
            ),
        )
        print("  各机构限额设置完成")

        print("\n=== 做市商挂出双向报价 ===")
        q1 = services.create_quote(
            db,
            QuoteCreate(
                institution_id=hsbc.id,
                currency_pair_id=usd_cnh.id,
                bid_price=Decimal("7.235000"),
                ask_price=Decimal("7.240000"),
                bid_amount=Decimal("2000000"),
                ask_amount=Decimal("2000000"),
                valid_minutes=120,
            ),
        )
        print(f"  报价1: USD/CNH 做市商={hsbc.code} 买=7.2350 卖=7.2400 量=2,000,000 (id={q1.id})")

        q2 = services.create_quote(
            db,
            QuoteCreate(
                institution_id=hsbc.id,
                currency_pair_id=eur_cnh.id,
                bid_price=Decimal("7.850000"),
                ask_price=Decimal("7.860000"),
                bid_amount=Decimal("1500000"),
                ask_amount=Decimal("1500000"),
                valid_minutes=60,
            ),
        )
        print(f"  报价2: EUR/CNH 做市商={hsbc.code} 买=7.8500 卖=7.8600 量=1,500,000 (id={q2.id})")

        print("\n=== 场景1: 正常撮合成交 ===")
        print("  中国银行买入 USD 500,000 @ 7.2400（汇丰卖出价）")
        t1 = services.create_trade(
            db,
            TradeCreate(
                quote_id=q1.id,
                initiator_id=boc.id,
                direction=TradeDirection.BUY,
                trade_type=TradeType.SPOT,
                amount=Decimal("500000"),
            ),
        )
        print(f"  交易创建: id={t1.id} 状态={t1.status.value}")

        t1_result = services.submit_trade(db, t1.id)
        print(f"  撮合结果: 状态={t1_result.status.value}")
        if t1_result.reject_reason:
            print(f"  拒单原因: {t1_result.reject_reason}")
        else:
            print(f"  ✓ 成交! 方向={t1_result.direction.value} 数量={t1_result.amount} 价格={t1_result.price}")

        limits_boc = services.list_institution_limits(db, institution_id=boc.id)
        for lim in limits_boc:
            print(f"  中银行限额: 授信={lim.credit_limit} 已用={lim.used_credit} 净敞口={lim.net_exposure} 限额={lim.exposure_limit}")

        print("\n=== 场景2: 超限额被拒 ===")
        print("  花旗银行买入 USD 400,000 @ 7.2400（但敞口限额仅300,000）")
        t2 = services.create_trade(
            db,
            TradeCreate(
                quote_id=q1.id,
                initiator_id=cbi.id,
                direction=TradeDirection.BUY,
                trade_type=TradeType.SPOT,
                amount=Decimal("400000"),
            ),
        )
        print(f"  交易创建: id={t2.id} 状态={t2.status.value}")

        t2_result = services.submit_trade(db, t2.id)
        print(f"  撮合结果: 状态={t2_result.status.value}")
        if t2_result.reject_reason:
            print(f"  ✗ 拒单! 原因: {t2_result.reject_reason}")

        print("\n=== 场景3: 远期成交 ===")
        print("  浦发银行卖出 EUR 300,000 远期1个月 @ 7.8500（汇丰买入价）")
        t3 = services.create_trade(
            db,
            TradeCreate(
                quote_id=q2.id,
                initiator_id=spdb.id,
                direction=TradeDirection.SELL,
                trade_type=TradeType.FORWARD,
                amount=Decimal("300000"),
                forward_date=date.today() + timedelta(days=30),
            ),
        )
        print(f"  交易创建: id={t3.id} 状态={t3.status.value}")

        t3_result = services.submit_trade(db, t3.id)
        print(f"  撮合结果: 状态={t3_result.status.value}")
        if t3_result.reject_reason:
            print(f"  拒单原因: {t3_result.reject_reason}")
        else:
            print(f"  ✓ 成交! 方向={t3_result.direction.value} 数量={t3_result.amount} 价格={t3_result.price} 远期日={t3_result.forward_date}")

        print("\n=== 日终清算 ===")
        reports = services.eod_clearing(db)
        for r in reports:
            inst = db.query(Institution).filter(Institution.id == r.institution_id).first()
            cp = db.query(CurrencyPair).filter(CurrencyPair.id == r.currency_pair_id).first()
            print(
                f"  {inst.code} | {cp.symbol} | 买入={r.buy_volume} "
                f"卖出={r.sell_volume} 净额={r.net_volume} 笔数={r.trade_count}"
            )

        print("\n=== 统计 ===")
        stats = services.get_statistics(db)
        print(f"  总交易: {stats.total_trades}")
        print(f"  已成交: {stats.executed_trades}")
        print(f"  已拒单: {stats.cancelled_trades}")
        print(f"  成交总量: {stats.total_volume}")
        if stats.reject_reasons:
            print("  拒单原因分布:")
            for rr in stats.reject_reasons:
                print(f"    - {rr.reject_reason}: {rr.count}笔")

        print("\n=== 种子数据初始化完成 ===")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
