"""测试：金额/日期解析与完整度评估（extractor 纯函数）

运行：cd backend && pytest tests/test_extractor.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extractor import (  # noqa: E402
    evaluate_completeness,
    normalize_date,
    parse_amount_to_cents,
)


class TestParseAmount:
    def test_wan(self):
        assert parse_amount_to_cents("539万元") == 539000000

    def test_yi(self):
        assert parse_amount_to_cents("1.2亿") == 12000000000

    def test_with_comma(self):
        assert parse_amount_to_cents("1,200万元") == 1200000000

    def test_plain_yuan(self):
        assert parse_amount_to_cents("8000元") == 800000

    def test_unknown(self):
        assert parse_amount_to_cents("未知") is None
        assert parse_amount_to_cents("面议") is None
        assert parse_amount_to_cents(None) is None
        assert parse_amount_to_cents("") is None

    def test_raw_float(self):
        # Excel 原始浮点值（无单位时按元处理）
        assert parse_amount_to_cents("65.94") == 6594


class TestNormalizeDate:
    def test_full(self):
        assert normalize_date("2025年4月20日") == "2025-04-20"

    def test_iso(self):
        assert normalize_date("2025-04-20") == "2025-04-20"

    def test_year_only(self):
        assert normalize_date("2025年") == "2025-01-01"

    def test_invalid(self):
        assert normalize_date(None) is None
        assert normalize_date("未知") is None


class TestCompleteness:
    def test_green(self):
        level, missing = evaluate_completeness({
            "debtor_name": "青岛某公司", "principal_cents": 100,
            "collateral": "市北区某房产", "interest_cents": 20, "guaranty_type": "抵押",
        })
        assert level == "green", (level, missing)

    def test_yellow(self):
        # 关键字段齐备，但利息+担保类型缺失 → yellow
        level, _ = evaluate_completeness({
            "debtor_name": "青岛某公司", "principal_cents": 100,
            "collateral": "市北区某房产",
            "interest_cents": None, "guaranty_type": None,
        })
        assert level == "yellow"

    def test_red_no_name(self):
        level, missing = evaluate_completeness({
            "debtor_name": None, "principal_cents": 100,
            "collateral": "某房产",
        })
        assert level == "red"
        assert "债务人名称" in missing

    def test_red_no_principal(self):
        level, missing = evaluate_completeness({
            "debtor_name": "某公司", "principal_cents": None,
            "collateral": "某房产",
        })
        assert level == "red"
        assert "债权本金" in missing

    def test_red_no_collateral(self):
        # 抵押物是关键字段（产品决策），缺失 → red
        level, missing = evaluate_completeness({
            "debtor_name": "某公司", "principal_cents": 100,
            "collateral": None,
        })
        assert level == "red"
        assert "抵押物" in missing
