"""测试：本息计算 + 提醒规则引擎（无第三方依赖的纯逻辑）

运行：cd backend && pytest tests/test_engine.py -v
"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.interest import calculate_interest  # noqa: E402
from app.services.reminder_engine import ReminderEngine  # noqa: E402

engine = ReminderEngine()


def make_claim(**kw):
    defaults = dict(
        collateral=None, judicial_status=None, debtor_type="enterprise",
        guaranty_type=None, guarantor=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestInterest:
    def test_lpr_estimate(self):
        res = calculate_interest(539000000, date(2020, 5, 1), date(2026, 8, 17))
        assert res.calculation_mode == "lpr_estimate"
        assert res.total_cents > 539000000
        assert len(res.items) == 2

    def test_with_judgment(self):
        res = calculate_interest(
            539000000, date(2020, 5, 1), date(2026, 8, 17),
            has_judgment=True, judgment_rate=0.0435, judgment_penalty_per_day=0.000175,
        )
        assert res.calculation_mode == "with_judgment"
        assert len(res.items) == 3  # 本金 + 利息 + 罚息

    def test_judgment_higher_than_lpr(self):
        lpr = calculate_interest(539000000, date(2020, 5, 1), date(2026, 8, 17))
        jud = calculate_interest(
            539000000, date(2020, 5, 1), date(2026, 8, 17),
            has_judgment=True, judgment_rate=0.0435,
        )
        assert jud.total_cents >= lpr.total_cents


class TestReminderRules:
    def test_a1_multi_collateral_real_format(self):
        claim = make_claim(
            collateral="抵押物：王国平名下三处房产，证号为：青房地权市字第201034568号、青房地权市字第201034616号、青房地权市字第201034594号",
        )
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": []})]
        assert "A1" in ids

    def test_a6_draw(self):
        claim = make_claim(collateral="土地性质划拨")
        ids = [r.rule_id for r in engine.match(claim, {})]
        assert "A6" in ids

    def test_a9_person_home(self):
        claim = make_claim(collateral="唯一住房，住宅", debtor_type="person")
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": []})]
        assert "A9" in ids

    def test_b1_bankruptcy(self):
        claim = make_claim(judicial_status="已进入破产程序")
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": ["x"]})]
        assert "B1" in ids

    def test_b5_no_judgment(self):
        claim = make_claim()
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": []})]
        assert "B5" in ids

    def test_c1_auction(self):
        claim = make_claim(judicial_status="涉及司法拍卖")
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": ["x"]})]
        assert "C1" in ids

    def test_d1_person_no_judgment(self):
        claim = make_claim(debtor_type="person")
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": []})]
        assert "D1" in ids

    def test_no_false_positive(self):
        """无风险信息不触发 A/B/C/D 大部分规则"""
        claim = make_claim()
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": ["x"]})]
        assert "A1" not in ids
        assert "B1" not in ids

    def test_rule_order(self):
        claim = make_claim(collateral="划拨土地，多套", judicial_status="破产")
        ids = [r.rule_id for r in engine.match(claim, {"legal_documents": ["x"]})]
        assert ids == sorted(ids, key=lambda x: (x[0], int(x[1:])))
