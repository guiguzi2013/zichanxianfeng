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
            "collateral": "市北区XX路88号XX小区3号楼602室（面积89.5㎡）", "interest_cents": 20, "guaranty_type": "抵押",
        })
        assert level == "green", (level, missing)

    def test_yellow(self):
        # 关键字段齐备，但利息+担保类型缺失 → yellow
        level, _ = evaluate_completeness({
            "debtor_name": "青岛某公司", "principal_cents": 100,
            "collateral": "市北区XX路88号XX小区3号楼602室",
            "interest_cents": None, "guaranty_type": None,
        })
        assert level == "yellow"

    def test_red_pure_type_collateral(self):
        # 2026-09-02 用户规则细化：抵押物只有类型词（无具体位置/面积/证号）→ 视为抵押物缺失 → red
        level, missing = evaluate_completeness({
            "debtor_name": "青岛某公司", "principal_cents": 100,
            "collateral": "住宅房产", "extra_fields": {"collateral_type": "住宅房产"},
        })
        assert level == "red"
        assert "抵押物" in missing

    def test_red_non_realestate_collateral(self):
        # 2026-09-02 用户规则细化：抵押物是机器设备等非房产 → 不可尽调 → red
        level, missing = evaluate_completeness({
            "debtor_name": "青岛某公司", "principal_cents": 100,
            "collateral": "机器设备一批", "extra_fields": {"collateral_type": "其他"},
        })
        assert level == "red"
        assert "抵押物" in missing

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


class Test453Regression:
    """2026-09-02 回归：feed#453 债权与原文不符的根因修复
    （kv 3列错位/债务人垃圾提取/抵押物注释误提取）"""

    def test_kv_three_col_group_key_value(self):
        """3 列行 ["组名","键","值"]（如 ["债权基本情况","贷款发放金额","10000000.00 元"]）
        必须解析为 键→值，不能错位成 组名→键"""
        from app.scrapers.jd_credit import _parse_kv_table
        kv = _parse_kv_table(
            ["债权情况说明"],
            [
                ["债权名称", "借款合同号 159002161646025 的不良贷款债权"],
                ["债权基本情况", "贷款发放金额", "10000000.00 元"],
                ["本金余额", "2793186.45 元"],
                ["抵、质押及担保情况", "抵、质押及保证担保人", "陈大光"],
                ["抵、质押物：（产权号、面积等）", "权属南宁泰富大厦第3层，面积1593.62㎡"],
            ],
        )
        assert kv is not None
        assert kv.get("贷款发放金额") == "10000000.00 元", kv  # 不再错位成 "债权基本情况"→"贷款发放金额"
        assert kv.get("本金余额") == "2793186.45 元", kv
        assert kv.get("抵、质押及保证担保人") == "陈大光", kv
        assert "权属南宁泰富大厦" in str(kv.get("抵、质押物：（产权号、面积等）")), kv

    def test_debtor_no_garbage_from_duiying(self):
        """标题"…债权及对应的从权利…"不能把"对"当"对债务人"提取出垃圾（453 案例"应的从权利（"）"""
        from app.scrapers.text_extract import extract_debtor
        assert extract_debtor("借款合同号 159002161646025 的不良贷款债权及对应的从权利（详见合同）") == ""
        assert extract_debtor("靖远县振兴工贸有限责任公司等6户债权资产") == "靖远县振兴工贸有限责任公司"

    def test_collateral_skips_disclaimer(self):
        """免责/注释段落含"抵押"字样不能被当抵押物描述（453 案例取到"抵押房地产可能已被查封…"）"""
        from app.scrapers.text_extract import extract_collateral_from_text
        text = "注：上述标的债权介绍仅供参考。4、标的资产项下抵押房地产可能已被其他债权人通过法院查封；存在法院判决部分担保人不承担担保责任的可能，本行不承担任何法律责任。"
        ctype, desc = extract_collateral_from_text(text)
        assert ctype == "" and desc == "", (ctype, desc)
        # 正常描述仍可提取
        ctype2, desc2 = extract_collateral_from_text("抵押物为天和家园住宅小区60套6428.11平方米住宅提供抵押担保")
        assert ctype2 == "住宅房产" and "天和家园" in desc2
