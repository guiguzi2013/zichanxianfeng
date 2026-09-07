# -*- coding: utf-8 -*-
"""报告"律师式建议"润色(2026-09-08 用户拍板: 分析段落不得照搬模板原话)

原则:
- 报告里每个有分析结果的地方(无形资产维度提示/权利主张案件/追索引言/画像司法概述…),
  由 LLM 基于该企业**真实查询结果**组织语言, 资深不良资产律师口吻, 差异化表达;
- 不背离用户原意与"追回欠款/财产线索"目的; 只基于传入数据与通用处置经验,
  不编造数据与法规(平台法律铁律); 禁内部词(企查查/积分/缓存/系统等);
- 一次调用返回多槽 JSON; 失败/超时/演示模式 → 返回空, 调用方保留模板兜底(报告永不因润色失败)。
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_SYSTEM = """你是一位资深不良资产处置律师, 正在为一家不良资产/债权从业机构撰写《财产线索报告》的执业分析建议。
你的文字将直接出现在正式报告中给从业者阅读, 要求:
1. 语气专业、克制、面向实操, 像资深律师审阅卷宗后给出的针对性建议; 每条围绕该企业查询到的真实数据展开,
   可点名具体数字与条目(只准引用提供的数据, 不得虚构或推算任何数字);
2. **严禁逐句复述或改写下方"参考要点"的原文**——要点只是必须覆盖的语义范围, 必须用你自己的话、
   结合查询摘要中的数据(数量/状态分布/代表性条目)重新组织; 与数据无关的通用知识不要写;
3. 不编造、不引用任何具体法律法规条文(可用"依法""司法程序"等概括表述), 不预测处置结果;
4. 禁止出现: 企查查、数据源、积分、缓存、调用、系统、AI、模型 等内部或技术词汇; 不使用"据公开信息""数据截至"之外的免责腔;
5. 每个主题段落独立成文, 语言要因企业而异——数据不同, 表述与侧重必须不同; 避免空泛套话;
6. 段落 120~280 字, 直接可用, 不要标题编号、不要解释你在做什么。"""

# 段落要点(供 LLM 内化语义, 禁止复述原文; 仅为"必须覆盖"清单, 措辞由模型按数据重组)
_IPR_POINTS = {
    "get_patent_info": "覆盖: 专利可评估后司法拍卖变现; 不同类型价值量级差异(发明最高, 实用/外观较低, 可落地转化更高); 先筛法律状态有效(未缴年费终止/无效不可执行)的专利再谈处置。",
    "get_international_patent": "覆盖: 国际专利价值高可评估执行; 结合数量与法律状态说明。",
    "get_trademark_info": "覆盖: 注册商标承载品牌价值可执行; 结合数量、续展等状态说明; 处置前核验状态与近似争议。",
    "get_trademark_document": "覆盖: 商标争议/评审文书的存在 → 相关商标有失效风险, 失效即不可再作无形资产变现; 结合文书条数说明关注与核验动作。",
    "get_internet_service_info": "覆盖: 备案域名可评估执行; 网站可作核验经营与找新线索入口; 备案类型本身执行难度。",
    "get_commercial_franchise": "覆盖: 特许经营权可执行; 加盟/授权收益可能存在隐瞒, 有追偿空间。",
    "get_ipr_pledge": "覆盖: 质押=有价值但被锁定; 执行须先处理质押负担; 质权人可作线索。",
    "claimant": "覆盖: 权利方诉讼胜诉可能带来执行回款(未来财产); 跟踪+判决前保全/轮候其可能取得的财产与账户。",
    "recovery_intro": "覆盖: 依据分级清单给总体处置思路(优先级/节奏/配合动作), 与分级表呼应, 不复述逐条。",
    "judicial_overview": "覆盖: 按命中维度与数量解读风险形态与清偿压力、威胁点与核实建议; 不复述清单。",
}
_IPR_POINTS_RE = re.compile(r"^(ipr_[a-z_]+|claimant|recovery_intro|judicial_overview)$")


def _slots_needed(sections: list) -> dict:
    """收集报告 sections 中的待润色槽位: {slot: 现模板文本或要点}"""
    out: dict = {}
    for sec in sections or []:
        slot = sec.get("note_slot")
        if slot and slot not in out:
            out[slot] = (sec.get("note") or "")[:200]
    return out


def _slot_point(slot: str, fallback: str) -> str:
    base = _IPR_POINTS.get(slot) or fallback
    return base


async def polish_report(sections: list, context_txt: str) -> list:
    """就地润色 sections 的 note(按 note_slot); 失败/无槽位/演示模式 → 原样返回。

    context_txt: 该企业查询结果摘要(维度计数/代表条目/风险命中/权利主张统计等)。
    """
    slots = _slots_needed(sections)
    if not slots:
        return sections
    if not context_txt.strip():
        return sections

    try:
        from .llm import LLMError, chat_json
        from ..config import get_settings
        settings = get_settings()
        if settings.llm_mock or not settings.deepseek_api_key:
            return sections  # 演示/未配 key: 保留模板

        slot_list = "、".join(slots.keys())
        need = "\n".join(f"- {k}: 参考要点 → {_slot_point(k, v)}" for k, v in slots.items())
        user = (
            "【被查询企业查询结果摘要】\n" + context_txt[:6000]
            + "\n\n【需要你撰写建议的段落与参考要点】\n" + need
            + "\n\n请输出 JSON 对象, 键为上述段落标识(" + slot_list + "), 值为该段建议文本;"
              "只输出确有分析价值的段落; 不要输出空串键。"
        )
        obj = await chat_json(_SYSTEM, user, temperature=0.5)
        if not isinstance(obj, dict):
            return sections
        replaced = 0
        for sec in sections:
            slot = sec.get("note_slot")
            if slot and isinstance(obj.get(slot), str) and obj[slot].strip():
                sec["note"] = obj[slot].strip()
                replaced += 1
        logger.info("polish_report: %d/%d slots replaced", replaced, len(slots))
    except LLMError as e:
        logger.warning("polish_report LLM 失败, 保留模板: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.exception("polish_report error: %s", e)
    return sections


def build_context(result: dict) -> str:
    """从财产线索 result 汇总润色上下文(控制长度, 供 LLM 引用)"""
    lines: list = []
    company = result.get("search_name") or result.get("company") or ""
    if company:
        lines.append(f"企业: {company}")
    biz = result.get("biz") or {}
    reg = (biz.get("get_company_registration_info") or {}).get("data") or {}
    if isinstance(reg, dict):
        lines.append(f"登记状态: {reg.get('登记状态') or '—'}; 注册资本: {reg.get('注册资本') or '—'}")
    # 司法命中(画像 result 已有 risk.hits; 线索 result 无 hits → 从 scan 提取)
    risk = result.get("risk") or {}
    hits = list(risk.get("hits") or [])
    if not hits and isinstance(risk.get("scan"), dict):
        sd = risk["scan"].get("data") or {}
        for f in (sd.get("风险因子扫描") or [])[:18]:
            if isinstance(f, dict) and (f.get("条目数") or 0) > 0:
                hits.append({"label": f.get("风险因子"), "count": f.get("条目数")})
    if hits:
        lines.append("司法风险命中: " + "、".join(f"{h.get('label')}{h.get('count')}条" for h in hits[:15]))
    # 无形资产
    ipr = result.get("ipr") or {}
    for tool, label in (("get_patent_info", "专利"), ("get_international_patent", "国际专利"),
                        ("get_trademark_info", "商标"), ("get_trademark_document", "商标文书"),
                        ("get_internet_service_info", "网络服务备案"), ("get_commercial_franchise", "特许经营"),
                        ("get_ipr_pledge", "知产出质")):
        r = ipr.get(tool)
        if not r or not r.get("ok"):
            continue
        d = r.get("data")
        if not isinstance(d, dict):
            continue
        if str(d.get("搜索结果") or "").count("未发现"):
            continue
        summary = str(d.get("摘要") or "")
        recs = []
        for v in d.values():
            if isinstance(v, list):
                for it in v[:4]:
                    if isinstance(it, dict):
                        nm = it.get("发明名称") or it.get("商标名称") or it.get("软件全称") or it.get("网站名称") \
                             or it.get("服务名称") or next((x for x in it.values() if isinstance(x, str) and x), "")
                        st = it.get("法律状态") or it.get("商标状态") or ""
                        recs.append(f"{nm}" + (f"({st})" if st else ""))
                break
        lines.append(f"{label}: {summary[:120]}" + (" 代表条目: " + "、".join(recs[:4]) if recs else ""))
    return "\n".join(lines)
