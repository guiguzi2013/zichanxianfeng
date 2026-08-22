"""测试：尽调引擎报告组装（mock 数据源与 LLM，验证 9 版块结构）

运行：cd backend && pytest tests/test_due_diligence.py -v
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---- mock 依赖，避免真实网络/LLM ----
import app.services.due_diligence as dd  # noqa: E402

class _FakeNodeProgress:
    def __init__(self):
        self.steps = []

    async def step(self, node, percent):
        self.steps.append((node, percent))


def _make_claim(**kw):
    defaults = dict(
        id=1, user_id=1, source_type="text", source_raw="test",
        debtor_name="青岛测试公司", principal_cents=539000000,
        interest_cents=429000000, fees_cents=None, guaranty_type="抵押",
        guarantor=None, collateral="抵押物：市北区房产，证号为：青房地权市字第201034568号",
        judicial_status="执行中", listing_price_cents=None, deadline=None,
        debtor_type="enterprise", completeness="green", missing_fields="[]",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestBuildReportContent:
    async def _run(self, claim):
        # monkeypatch 节点函数为确定性实现
        async def fake_node2(c):
            return {"type": "enterprise", "judicial_risk": {"note": "查询受限，需人工核实"}}
        async def fake_node3(c):
            return {"documents": {"found": False, "not_found_note": "未检索到判决书"}, "statutes_note": "AI生成需核验"}
        async def fake_node4(c):
            return {"present": True, "items": [{"description": c.collateral, "valuation": {"data_insufficient": True}}]}
        async def fake_node6(c, nodes):
            return {"summary": {"rating": "★★★", "core_logic": ["测试逻辑"]}, "risk": {"favorable": [], "risk": [], "need_manual_verify": ["测试"]}}

        orig = (dd._node2_judicial, dd._node3_legal, dd._node4_valuation, dd._node6_summary)
        dd._node2_judicial = fake_node2
        dd._node3_legal = fake_node3
        dd._node4_valuation = fake_node4
        dd._node6_summary = fake_node6
        try:
            return await dd.build_report_content(claim, _FakeNodeProgress())
        finally:
            dd._node2_judicial, dd._node3_legal, dd._node4_valuation, dd._node6_summary = orig

    def test_full_structure(self):
        import asyncio
        content = asyncio.run(self._run(_make_claim()))
        assert "report_meta" in content
        assert "sections" in content
        # 9 版块齐全
        for sec in ["summary", "reminders", "claim_basic", "debtor", "guarantor",
                    "collateral", "legal", "risk", "disposal"]:
            assert sec in content["sections"], f"missing {sec}"
        # 元信息
        assert content["report_meta"]["debtor_name"] == "青岛测试公司"
        assert content["report_meta"]["report_style"] == "full"
        # 本息
        assert content["sections"]["claim_basic"]["interest_detail"]["mode"] == "lpr_estimate"
        # 提醒（无判决书 → B5）
        reminders = content["sections"]["reminders"]["items"]
        ids = [r["rule_id"] for r in reminders]
        assert "B5" in ids
        # 免责声明
        assert "不构成投资建议" in content["disclaimer"]

    def test_person_simplified(self):
        import asyncio
        claim = _make_claim(debtor_type="person", collateral="唯一住房，住宅")
        content = asyncio.run(self._run(claim))
        assert content["report_meta"]["report_style"] == "simplified"

    def test_no_principal(self):
        import asyncio
        claim = _make_claim(principal_cents=None)
        content = asyncio.run(self._run(claim))
        assert content["sections"]["claim_basic"]["interest_detail"]["mode"] == "none"
