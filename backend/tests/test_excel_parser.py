"""测试：Excel 列映射与单位继承（excel_parser 纯函数）

运行：cd backend && pytest tests/test_excel_parser.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.excel_parser import (  # noqa: E402
    _apply_unit_inheritance,
    _to_cents,
    build_mapping,
)


class TestBuildMapping:
    def test_real_headers(self):
        """用户真实表头 6/6 命中"""
        headers = ["债权项目", "债权本金（万元）", "债权利息(截至2025/4/20）", "保证人", "抵押物情况描述", "执行法院"]
        mapping = build_mapping(headers)
        assert mapping["debtor_name"] == "债权项目"
        assert mapping["principal_text"] == "债权本金（万元）"
        assert mapping["interest_text"] == "债权利息(截至2025/4/20）"
        assert mapping["guarantor"] == "保证人"
        assert mapping["collateral"] == "抵押物情况描述"
        assert mapping["judicial_status"] == "执行法院"

    def test_partial_match(self):
        headers = ["债务人", "本金", "备注"]
        mapping = build_mapping(headers)
        assert mapping["debtor_name"] == "债务人"
        assert mapping["principal_text"] == "本金"
        assert "extra_notes" in mapping  # 备注 → extra_notes


class TestToCents:
    def test_wan_unit(self):
        assert _to_cents(539, 10**4) == 539000000

    def test_plain_number(self):
        assert _to_cents(65.94, 1) == 6594

    def test_text_with_unit(self):
        assert _to_cents("1.2亿", 1) == 12000000000

    def test_none(self):
        assert _to_cents(None, 1) is None
        assert _to_cents("面议", 1) is None


class TestUnitInheritance:
    def test_inherit_wan(self):
        """无单位利息列继承本金列万元倍率"""
        rows = [{"principal_text": 580000000, "interest_text": 6594}]
        unit_mult = {"principal_text": 10**4}  # 利息列不在其中 → 需继承
        _apply_unit_inheritance(rows, unit_mult)
        assert rows[0]["interest_text"] == 6594 * 10**4
        assert rows[0]["interest_text_unit_inherited"] is True

    def test_no_inherit_when_large(self):
        """原值已大（>1亿分）不继承"""
        rows = [{"principal_text": 580000000, "interest_text": 500000000}]
        _apply_unit_inheritance(rows, {"principal_text": 10**4})
        assert rows[0]["interest_text"] == 500000000

    def test_no_inherit_when_unit_present(self):
        rows = [{"principal_text": 580000000, "interest_text": 500000000}]
        _apply_unit_inheritance(rows, {"principal_text": 10**4, "interest_text": 10**4})
        assert rows[0]["interest_text"] == 500000000
        assert "interest_text_unit_inherited" not in rows[0]
