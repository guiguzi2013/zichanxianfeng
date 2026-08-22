"""深度调查报告生成器测试（纯本地，零企查查积分）"""
import pytest

from app.services.deep_investigation import build_deep_report


def _mk_deep(**over):
    base = {
        "biz": {
            "get_company_registration_info": {
                "ok": True,
                "data": {"企业名称": "测试企业有限公司", "登记状态": "存续"},
            },
            "get_external_investments": {
                "ok": True,
                "data": {"对外投资信息": [
                    {"被投资企业名称": "存续子公司", "状态": "存续", "持股比例": "100%"},
                    {"被投资企业名称": "已注销子公司", "状态": "注销", "持股比例": "100%"},
                ]},
            },
            "get_chattel_mortgage_info": {"ok": True, "data": {"动产抵押信息": [{"登记编号": "M001"}]}},
            "get_land_mortgage_info": {"ok": True, "data": {}},
            "get_judicial_auction": {"ok": True, "data": {}},
        },
        "risk": {"scan": {"ok": True, "data": {"摘要": "已全量扫描 35 项风险因子"}}},
    }
    details = {
        "get_judicial_documents": {"ok": True, "data": {"案件列表": [
            {"案件名称": "测试企业有限公司诉第三人合同纠纷", "案号": "(2024)浙01民初1号"},
            {"案件名称": "第三人诉测试企业有限公司借款纠纷", "案号": "(2024)浙01民初2号"},
        ]}},
        "get_case_filing_info": {"ok": True, "data": {"立案信息": [
            {"案件名称": "测试企业有限公司诉新债务人", "案号": "(2025)浙01民初3号"},
        ]}},
        "get_valuation_inquiry": {"ok": True, "data": {"询价评估": [{"标的": "机器设备"}]}},
        "get_property_asset_announcement": {"ok": True, "data": {"悬赏公告": [{"标的": "厂房"}]}},
        "get_equity_freeze": {"ok": True, "data": {"股权冻结": [{"被冻结股权": "某公司"}]}},
        "get_terminated_cases": {"ok": True, "data": {"终本案件": [{"案号": "(2023)浙01执1号"}]}},
    }
    extra_biz = {
        "get_annual_reports": {"ok": True, "data": {"年报信息": [{"年度": "2023"}]}},
        "get_financial_data": {"ok": True, "data": {}},
        "get_tax_invoice_info": {"ok": True, "data": {}},
    }
    deep = {"company": "测试企业有限公司", "base": base, "extra_biz": extra_biz, "risk_details": details}
    deep.update(over)
    return deep


def test_build_deep_report_dimensions():
    rep = build_deep_report(_mk_deep(), calls_used=14)
    names = [d["name"] for d in rep["dimensions"]]
    assert any("对外投资股权" in n for n in names)          # 只保留存续子公司
    assert any("动产抵押" in n for n in names)              # 有记录才出现
    assert not any("土地抵押" in n for n in names)          # 空数据不出现
    assert any("对外应收债权" in n for n in names)          # 作为原告的裁判文书 → 债权线索
    assert any("经营活跃度" in n for n in names)            # 年报有记录
    assert any("司法风险因子明细" in n for n in names)
    assert rep["calls_used"] == 14
    assert len(rep["offline_guides"]) >= 7
    assert rep["company"] == "测试企业有限公司"


def test_build_deep_report_empty():
    """无任何资产线索时：不报错，给出线下核实指引"""
    rep = build_deep_report(_mk_deep(
        base={"biz": {
            "get_company_registration_info": {"ok": True, "data": {"企业名称": "空壳企业"}},
            "get_external_investments": {"ok": True, "data": {}},
            "get_chattel_mortgage_info": {"ok": True, "data": {}},
            "get_land_mortgage_info": {"ok": True, "data": {}},
            "get_judicial_auction": {"ok": True, "data": {}},
        }, "risk": {"scan": {"ok": True, "data": {"摘要": ""}}}},
        extra_biz={},
        risk_details={},
    ), calls_used=8)
    assert rep["dimensions"] == []
    assert "线下" in rep["summary"] or "公开数据" in rep["summary"]
    assert len(rep["offline_guides"]) == 7
