from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, Base
from app.models import (
    Institution,
    InstitutionType,
    CurrencyPair,
    TradeStatus,
    TradeDirection,
    TradeType,
)
from app import services
from app.schemas import (
    InstitutionCreate,
    CurrencyPairCreate,
    InstitutionLimitCreate,
    QuoteCreate,
    TradeCreate,
)


def assert_eq(actual, expected, msg=""):
    ok = actual == expected
    mark = "✓" if ok else "✗"
    print(f"  {mark} {msg}: expected={expected} actual={actual}")
    if not ok:
        raise AssertionError(f"FAIL: {msg}")


def test_isolated_clearing():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    try:
        print("=" * 70)
        print(" 核心场景验证：按机构清算隔离性测试")
        print(" 顺序：A(BOC) 先清算 → B(SPDB) 再清算 → 对手方(HSBC) 清算 → 重复清算拒绝")
        print("=" * 70)

        boc = services.create_institution(
            db,
            InstitutionCreate(
                code="BOC", name="中国银行", inst_type=InstitutionType.DOMESTIC_BANK, country="CN"
            ),
        )
        spdb = services.create_institution(
            db,
            InstitutionCreate(
                code="SPDB", name="浦发银行", inst_type=InstitutionType.DOMESTIC_BANK, country="CN"
            ),
        )
        hsbc = services.create_institution(
            db,
            InstitutionCreate(
                code="HSBC", name="汇丰银行", inst_type=InstitutionType.MARKET_MAKER, country="UK"
            ),
        )
        usd_cnh = services.create_currency_pair(
            db, CurrencyPairCreate(symbol="USD/CNH", base_currency="USD", quote_currency="CNH")
        )

        for inst in [boc, spdb, hsbc]:
            services.create_institution_limit(
                db,
                InstitutionLimitCreate(
                    institution_id=inst.id,
                    currency_pair_id=usd_cnh.id,
                    credit_limit=Decimal("10000000"),
                    exposure_limit=Decimal("5000000"),
                ),
            )

        q = services.create_quote(
            db,
            QuoteCreate(
                institution_id=hsbc.id,
                currency_pair_id=usd_cnh.id,
                bid_price=Decimal("7.235000"),
                ask_price=Decimal("7.240000"),
                bid_amount=Decimal("10000000"),
                ask_amount=Decimal("10000000"),
                valid_minutes=600,
            ),
        )

        print("\n[Step 1] 创建3笔交易：BOC买入100万、SPDB卖出50万、BOC卖出30万（对手方均为HSBC）")
        t1 = services.create_trade(
            db,
            TradeCreate(
                quote_id=q.id, initiator_id=boc.id,
                direction=TradeDirection.BUY, trade_type=TradeType.SPOT,
                amount=Decimal("1000000"),
            ),
        )
        t2 = services.create_trade(
            db,
            TradeCreate(
                quote_id=q.id, initiator_id=spdb.id,
                direction=TradeDirection.SELL, trade_type=TradeType.SPOT,
                amount=Decimal("500000"),
            ),
        )
        t3 = services.create_trade(
            db,
            TradeCreate(
                quote_id=q.id, initiator_id=boc.id,
                direction=TradeDirection.SELL, trade_type=TradeType.SPOT,
                amount=Decimal("300000"),
            ),
        )
        t1 = services.submit_trade(db, t1.id)
        t2 = services.submit_trade(db, t2.id)
        t3 = services.submit_trade(db, t3.id)
        assert_eq(t1.status.value, "EXECUTED", "BOC买入交易状态")
        assert_eq(t2.status.value, "EXECUTED", "SPDB卖出交易状态")
        assert_eq(t3.status.value, "EXECUTED", "BOC卖出交易状态")

        boc_lim_before = services.list_institution_limits(db, institution_id=boc.id)[0]
        spdb_lim_before = services.list_institution_limits(db, institution_id=spdb.id)[0]
        hsbc_lim_before = services.list_institution_limits(db, institution_id=hsbc.id)[0]
        print(f"\n  清算前各机构限额:")
        print(f"    BOC:  已用授信={boc_lim_before.used_credit} 净敞口={boc_lim_before.net_exposure}")
        print(f"    SPDB: 已用授信={spdb_lim_before.used_credit} 净敞口={spdb_lim_before.net_exposure}")
        print(f"    HSBC: 已用授信={hsbc_lim_before.used_credit} 净敞口={hsbc_lim_before.net_exposure}")

        # ===== A 先清算 =====
        print("\n[Step 2] >>> A(BOC) 先清算（institution_id=%s）" % boc.id)
        reports_boc = services.eod_clearing(db, institution_id=boc.id)
        print(f"  生成报表数量: {len(reports_boc)}")
        for r in reports_boc:
            print(f"    报表: 机构ID={r.institution_id} 买={r.buy_volume} 卖={r.sell_volume} 净额={r.net_volume} 笔数={r.trade_count}")

        assert_eq(len(reports_boc), 1, "BOC清算只生成BOC自己的报表")
        rep_boc = reports_boc[0]
        assert_eq(rep_boc.institution_id, boc.id, "报表属于BOC")
        assert_eq(rep_boc.buy_volume, Decimal("1000000"), "BOC报表买入量")
        assert_eq(rep_boc.sell_volume, Decimal("300000"), "BOC报表卖出量")
        assert_eq(rep_boc.net_volume, Decimal("700000"), "BOC报表净买入")
        assert_eq(rep_boc.trade_count, 2, "BOC报表包含2笔交易")

        hsbc_reports = services.list_clearing_reports(db, institution_id=hsbc.id, trade_date=date.today())
        assert_eq(len(hsbc_reports), 0, "BOC清算不生成HSBC报表")
        spdb_reports = services.list_clearing_reports(db, institution_id=spdb.id, trade_date=date.today())
        assert_eq(len(spdb_reports), 0, "BOC清算不生成SPDB报表")

        print("\n[Step 3] 验证交易状态：BOC参与的交易(t1,t3)立即变为CLEARED，与BOC无关的交易(t2)保持EXECUTED")
        t_cleared = services.list_trades(db, status="CLEARED", trade_date=date.today())
        cleared_ids = sorted(t.id for t in t_cleared)
        print(f"  CLEARED交易ID: {cleared_ids}")
        assert_eq(cleared_ids, sorted([t1.id, t3.id]), "BOC参与的t1,t3应为CLEARED")

        t_exec = services.list_trades(db, status="EXECUTED", trade_date=date.today())
        exec_ids = sorted(t.id for t in t_exec)
        print(f"  EXECUTED交易ID: {exec_ids}")
        assert_eq(exec_ids, [t2.id], "仅SPDB参与的t2保持EXECUTED")

        boc_lim_after = services.list_institution_limits(db, institution_id=boc.id)[0]
        spdb_lim_after = services.list_institution_limits(db, institution_id=spdb.id)[0]
        hsbc_lim_after = services.list_institution_limits(db, institution_id=hsbc.id)[0]
        print(f"\n  BOC清算后各机构限额:")
        print(f"    BOC:  已用={boc_lim_after.used_credit} 敞口={boc_lim_after.net_exposure}")
        print(f"    SPDB: 已用={spdb_lim_after.used_credit} 敞口={spdb_lim_after.net_exposure}")
        print(f"    HSBC: 已用={hsbc_lim_after.used_credit} 敞口={hsbc_lim_after.net_exposure}")

        assert_eq(boc_lim_after.used_credit, Decimal("0"), "BOC清算后used_credit归零")
        assert_eq(boc_lim_after.net_exposure, Decimal("0"), "BOC清算后net_exposure归零")
        assert_eq(spdb_lim_after.used_credit, spdb_lim_before.used_credit, "SPDB的used_credit不受BOC清算影响")
        assert_eq(spdb_lim_after.net_exposure, spdb_lim_before.net_exposure, "SPDB的net_exposure不受BOC清算影响")
        assert_eq(hsbc_lim_after.used_credit, hsbc_lim_before.used_credit, "HSBC的used_credit不受BOC清算影响")
        assert_eq(hsbc_lim_after.net_exposure, hsbc_lim_before.net_exposure, "HSBC的net_exposure不受BOC清算影响")

        print("\n[Step 4] 验证SPDB视角：t2仍为EXECUTED，统计正确，SPDB无报表")
        stats_spdb = services.get_statistics(db, institution_id=spdb.id, trade_date=date.today())
        assert_eq(stats_spdb.executed_trades, 1, "SPDB已成交(含已清算)笔数=1")
        assert_eq(stats_spdb.total_trades, 1, "SPDB总交易笔数=1")
        assert_eq(stats_spdb.total_volume, Decimal("500000"), "SPDB成交总量=50万")
        spdb_check = services.list_clearing_reports(db, institution_id=spdb.id, trade_date=date.today())
        assert_eq(len(spdb_check), 0, "SPDB尚未清算，无报表")
        print("  ✓ SPDB视角不受BOC清算干扰")

        print("\n[Step 5] >>> 立即对A(BOC)重复清算，应被拒绝")
        try:
            services.eod_clearing(db, institution_id=boc.id)
            print("  ✗ 本应抛出异常却成功了，幂等性失效")
            raise AssertionError("FAIL: BOC当天重复清算应被拒绝")
        except ValueError as e:
            print(f"  ✓ 正确拒绝: {e}")

        # ===== B 再清算 =====
        print("\n[Step 6] >>> B(SPDB) 再清算（institution_id=%s）" % spdb.id)
        reports_spdb = services.eod_clearing(db, institution_id=spdb.id)
        print(f"  生成报表数量: {len(reports_spdb)}")
        for r in reports_spdb:
            print(f"    报表: 机构ID={r.institution_id} 买={r.buy_volume} 卖={r.sell_volume} 净额={r.net_volume} 笔数={r.trade_count}")
        assert_eq(len(reports_spdb), 1, "SPDB清算只生成SPDB自己的报表")
        rep_spdb = reports_spdb[0]
        assert_eq(rep_spdb.institution_id, spdb.id, "报表属于SPDB")
        assert_eq(rep_spdb.buy_volume, Decimal("0"), "SPDB报表买入量=0")
        assert_eq(rep_spdb.sell_volume, Decimal("500000"), "SPDB报表卖出量=50万")
        assert_eq(rep_spdb.net_volume, Decimal("-500000"), "SPDB报表净卖出=-50万")
        assert_eq(rep_spdb.trade_count, 1, "SPDB报表包含1笔交易")

        print("\n[Step 7] 验证：B清算后，双方共同参与的交易已在BOC报表里，BOC额度不被重复释放")
        t_cleared_2 = services.list_trades(db, status="CLEARED", trade_date=date.today())
        cleared_ids_2 = sorted(t.id for t in t_cleared_2)
        print(f"  CLEARED交易ID: {cleared_ids_2}")
        assert_eq(cleared_ids_2, sorted([t1.id, t2.id, t3.id]), "SPDB清算后全部3笔均为CLEARED")

        boc_lim_after2 = services.list_institution_limits(db, institution_id=boc.id)[0]
        spdb_lim_after2 = services.list_institution_limits(db, institution_id=spdb.id)[0]
        hsbc_lim_after2 = services.list_institution_limits(db, institution_id=hsbc.id)[0]
        print(f"\n  SPDB清算后各机构限额:")
        print(f"    BOC:  已用={boc_lim_after2.used_credit} 敞口={boc_lim_after2.net_exposure}")
        print(f"    SPDB: 已用={spdb_lim_after2.used_credit} 敞口={spdb_lim_after2.net_exposure}")
        print(f"    HSBC: 已用={hsbc_lim_after2.used_credit} 敞口={hsbc_lim_after2.net_exposure}")

        assert_eq(boc_lim_after2.used_credit, Decimal("0"), "BOC额度不被SPDB清算重复释放(used_credit仍为0)")
        assert_eq(boc_lim_after2.net_exposure, Decimal("0"), "BOC敞口不被SPDB清算重复释放")
        assert_eq(spdb_lim_after2.used_credit, Decimal("0"), "SPDB清算后used_credit归零")
        assert_eq(spdb_lim_after2.net_exposure, Decimal("0"), "SPDB清算后net_exposure归零")
        assert_eq(hsbc_lim_after2.used_credit, hsbc_lim_before.used_credit, "HSBC的used_credit仍不受影响")
        assert_eq(hsbc_lim_after2.net_exposure, hsbc_lim_before.net_exposure, "HSBC的net_exposure仍不受影响")

        # ===== 对手方 HSBC 清算 =====
        print("\n[Step 8] >>> 对手方(HSBC) 清算，验证报表与对手方能对平")
        reports_hsbc = services.eod_clearing(db, institution_id=hsbc.id)
        print(f"  HSBC报表数: {len(reports_hsbc)}")
        for r in reports_hsbc:
            print(f"    报表: 机构ID={r.institution_id} 买={r.buy_volume} 卖={r.sell_volume} 净额={r.net_volume} 笔数={r.trade_count}")
        assert_eq(len(reports_hsbc), 1, "HSBC清算只生成自己的报表")
        rep_hsbc = reports_hsbc[0]
        assert_eq(rep_hsbc.institution_id, hsbc.id, "报表属于HSBC")
        assert_eq(rep_hsbc.buy_volume, Decimal("300000") + Decimal("500000"), "HSBC买入量 = BOC卖30万 + SPDB卖50万")
        assert_eq(rep_hsbc.sell_volume, Decimal("1000000"), "HSBC卖出量 = BOC买100万")
        assert_eq(rep_hsbc.net_volume, Decimal("-200000"), "HSBC净卖出 = -20万")
        assert_eq(rep_hsbc.trade_count, 3, "HSBC报表包含3笔交易")

        hsbc_lim_final = services.list_institution_limits(db, institution_id=hsbc.id)[0]
        assert_eq(hsbc_lim_final.used_credit, Decimal("0"), "HSBC清算后used_credit归零")
        assert_eq(hsbc_lim_final.net_exposure, Decimal("0"), "HSBC清算后net_exposure归零")

        boc_lim_final = services.list_institution_limits(db, institution_id=boc.id)[0]
        assert_eq(boc_lim_final.used_credit, Decimal("0"), "BOC额度不被HSBC清算影响")
        assert_eq(boc_lim_final.net_exposure, Decimal("0"), "BOC敞口不被HSBC清算影响")

        # ===== 重复清算拒绝 =====
        print("\n[Step 9] >>> 重复清算：已清算过的机构再次清算均应被拒绝")
        for inst_id, label in [(boc.id, "BOC"), (spdb.id, "SPDB"), (hsbc.id, "HSBC")]:
            try:
                services.eod_clearing(db, institution_id=inst_id)
                print(f"  ✗ {label}重复清算未被拒绝，幂等性失效")
                raise AssertionError(f"FAIL: {label}当天重复清算应被拒绝")
            except ValueError as e:
                print(f"  ✓ {label}重复清算被拒绝: {e}")

        print("\n  >>> 全量清算（无institution_id）也应被拒绝（已有报表）")
        try:
            services.eod_clearing(db)
            print("  ✗ 全量清算未被拒绝")
            raise AssertionError("FAIL: 已有机构单独清算后，全量清算应被拒绝")
        except ValueError as e:
            print(f"  ✓ 全量清算被拒绝: {e}")

        print("\n[Step 10] 对账单验证：各机构报表 vs 交易明细 vs 限额释放 三方一致")
        boc_trades = services.list_trades(db, institution_id=boc.id, trade_date=date.today())
        buy_from_trades = sum(t.amount for t in boc_trades if (t.initiator_id == boc.id and t.direction == TradeDirection.BUY) or (t.counterparty_id == boc.id and t.direction == TradeDirection.SELL))
        sell_from_trades = sum(t.amount for t in boc_trades if (t.initiator_id == boc.id and t.direction == TradeDirection.SELL) or (t.counterparty_id == boc.id and t.direction == TradeDirection.BUY))
        assert_eq(rep_boc.buy_volume, buy_from_trades, "BOC买入量：报表 vs 交易明细")
        assert_eq(rep_boc.sell_volume, sell_from_trades, "BOC卖出量：报表 vs 交易明细")

        all_trades_final = services.list_trades(db, trade_date=date.today())
        status_set = {t.status.value for t in all_trades_final}
        print(f"  最终全局交易状态集合: {status_set}")
        assert_eq(status_set, {"CLEARED"}, "全部交易应进入CLEARED状态")

        for inst_id, label in [(boc.id, "BOC"), (spdb.id, "SPDB"), (hsbc.id, "HSBC")]:
            lim = services.list_institution_limits(db, institution_id=inst_id)[0]
            assert_eq(lim.used_credit, Decimal("0"), f"{label}最终used_credit=0")
            assert_eq(lim.net_exposure, Decimal("0"), f"{label}最终net_exposure=0")
            reps = services.list_clearing_reports(db, institution_id=inst_id, trade_date=date.today())
            assert_eq(len(reps), 1, f"{label}最终报表数量=1")

        print("\n[Step 11] 统计一致性：拒单统计按发起方归属，确保各机构统计口径可对账")
        rejected = services.create_trade(
            db,
            TradeCreate(
                quote_id=q.id, initiator_id=boc.id,
                direction=TradeDirection.BUY, trade_type=TradeType.SPOT,
                amount=Decimal("99999999"),
            ),
        )
        services.submit_trade(db, rejected.id)

        stats_boc = services.get_statistics(db, institution_id=boc.id, trade_date=date.today())
        stats_spdb = services.get_statistics(db, institution_id=spdb.id, trade_date=date.today())
        stats_hsbc = services.get_statistics(db, institution_id=hsbc.id, trade_date=date.today())
        print(f"  BOC统计: 总={stats_boc.total_trades} 已成交={stats_boc.executed_trades} 拒单={stats_boc.cancelled_trades}")
        print(f"  SPDB统计: 总={stats_spdb.total_trades} 已成交={stats_spdb.executed_trades} 拒单={stats_spdb.cancelled_trades}")
        print(f"  HSBC统计: 总={stats_hsbc.total_trades} 已成交={stats_hsbc.executed_trades} 拒单={stats_hsbc.cancelled_trades}")
        assert_eq(len(stats_boc.reject_reasons), 1, "BOC统计有拒单原因分布（BOC发起的拒单归BOC）")
        assert_eq(len(stats_spdb.reject_reasons), 0, "SPDB统计拒单原因为空（拒单不是SPDB发起）")
        assert_eq(len(stats_hsbc.reject_reasons), 0, "HSBC统计拒单原因为空（拒单不是HSBC发起）")
        print("  ✓ 拒单按发起机构归属，跨机构统计互不牵连")

        print("\n" + "=" * 70)
        print(" ✓ A先清算→B再清算→对手方清算→重复清算拒绝 全流程验证通过！")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    import os
    db_path = "./fxtrade.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    test_isolated_clearing()
