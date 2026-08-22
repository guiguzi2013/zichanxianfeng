"""案件综合分析报告生成器

把案件中所有相关主体（借款人/保证人/关联人）的企查查数据融合，
输出：案件概览 → 主体风险汇总 → 财产线索汇总 → 追索优先级排序 → 综合建议。
规则驱动（稳定、免费、即时），供律师/债权人制定追索策略。
"""

EXEC = "被执行人"
DISHONEST = "失信信息"
LIMIT_HIGH = "限制高消费"
TERMINATED = "终本案件"

CLUE_KEYS = ("get_external_investments", "get_chattel_mortgage_info",
             "get_land_mortgage_info", "get_judicial_auction")


def _risk_counts(data: dict) -> dict[str, int]:
    scan = data.get("risk", {}).get("scan") or {}
    factors = scan.get("data", {}).get("风险因子扫描") or [] if scan.get("ok") else []
    return {f["风险因子"]: f.get("条目数") or 0 for f in factors if (f.get("条目数") or 0) > 0}


def _clue_count(data: dict) -> int:
    biz = data.get("biz") or {}
    total = 0
    for k in CLUE_KEYS:
        r = biz.get(k)
        if r and r.get("ok") and isinstance(r.get("data"), dict):
            for v in r["data"].values():
                if isinstance(v, list):
                    total += len(v)
    return total


def _status_of(data: dict) -> str:
    reg = data.get("biz", {}).get("get_company_registration_info")
    if reg and reg.get("ok") and isinstance(reg.get("data"), dict):
        return reg["data"].get("登记状态") or ""
    return ""


def _score(data: dict) -> int:
    """追索执行价值评分：
    有财产线索 +3（可直接执行）；登记存续 +2（可能仍有经营收入）；
    有被执行 -3 / 有失信 -3（清偿能力存疑）；有限高 -2 / 有终本 -2（执行受阻）。
    >=3 优先追索；>=0 建议调查；<0 暂缓（风险高）。"""
    s = 0
    if _clue_count(data) > 0:
        s += 3
    status = _status_of(data)
    if status and ("存续" in status or "在营" in status or "开业" in status):
        s += 2
    rc = _risk_counts(data)
    if rc.get(EXEC):
        s -= 3
    if rc.get(DISHONEST):
        s -= 3
    if rc.get(LIMIT_HIGH):
        s -= 2
    if rc.get(TERMINATED):
        s -= 2
    return max(s, -8)


def build_case_report(entities: list[dict], results: dict) -> dict:
    """entities: [{name, role, type?}]；results: {name: query_result}"""
    subjects: list[dict] = []
    for e in entities:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        data = results.get(name)
        if data is None:
            subjects.append({"name": name, "role": e.get("role") or "相关主体", "queried": False})
            continue
        rc = _risk_counts(data)
        clues = _clue_count(data)
        score = _score(data)
        subjects.append({
            "name": name,
            "role": e.get("role") or "相关主体",
            "queried": True,
            "status": _status_of(data),
            "risk": {k: rc.get(k, 0) for k in (EXEC, DISHONEST, LIMIT_HIGH, TERMINATED)},
            "clue_count": clues,
            "score": score,
            "priority": "优先追索" if score >= 3 else ("建议调查" if score >= 0 else "暂缓（风险高）"),
        })

    # 按追索价值排序（有数据的主体在前）
    ordered = sorted([s for s in subjects if s["queried"]], key=lambda s: -s["score"])
    not_queried = [s for s in subjects if not s["queried"]]

    # 汇总
    n_high_risk = sum(1 for s in subjects if s["queried"] and s["risk"][EXEC] > 0)
    n_with_clues = sum(1 for s in subjects if s["queried"] and s["clue_count"] > 0)
    n_priority = sum(1 for s in ordered if s["priority"] == "优先追索")

    # 综合建议
    advice: list[str] = []
    if n_priority > 0:
        advice.append(f"有 {n_priority} 家主体具备可执行财产线索且司法风险相对可控，建议列为追索优先对象，尽快诉前保全。")
    if n_high_risk > 0:
        advice.append(f"{n_high_risk} 家主体已涉被执行/失信，清偿能力存疑：注意参与分配顺序，尽快申报债权；对保证人重点核查其代偿能力。")
    if n_with_clues == 0 and subjects:
        advice.append("未发现明显可执行财产线索的主体，建议通过律师调查令/财产报告令深挖个人与企业名下资产，或评估债权转让。")
    if not_queried:
        advice.append(f"{len(not_queried)} 个主体（多为自然人）未走企查查查询：个人资产需线下调查，可结合其担任法定代表人/股东的企业线索追索。")
    if not advice:
        advice.append("暂无可执行线索，建议先全面调查后再制定追索方案。")

    return {
        "subject_count": len(subjects),
        "queried_count": len(subjects) - len(not_queried),
        "n_high_risk": n_high_risk,
        "n_with_clues": n_with_clues,
        "n_priority": n_priority,
        "ordered": ordered,
        "not_queried": not_queried,
        "advice": advice,
        "reminders": _match_case_reminders(results),
    }


def _match_case_reminders(results: dict) -> list[dict]:
    """跨主体匹配知识库案例场景，汇总风险提醒（如抵押物占用/终本/拒执/一人公司等）。

    每个主体的特征文本拼合后按关键词匹配，命中即返回提醒。
    """
    from ..api.knowledge import _match_keywords
    from ..database import SessionLocal
    from ..models import KnowledgeCase

    features = []
    for data in results.values():
        parts = []
        scan = data.get("risk", {}).get("scan") or {}
        if scan.get("ok") and isinstance(scan.get("data"), dict):
            for f in scan["data"].get("风险因子扫描") or []:
                if (f.get("条目数") or 0) > 0:
                    parts.append(f["风险因子"])
        biz = data.get("biz") or {}
        for tool in ("get_chattel_mortgage_info", "get_land_mortgage_info", "get_judicial_auction"):
            if (biz.get(tool) or {}).get("ok"):
                parts.append({"get_chattel_mortgage_info": "动产抵押",
                              "get_land_mortgage_info": "土地抵押",
                              "get_judicial_auction": "司法拍卖"}[tool])
        inv = biz.get("get_external_investments") or {}
        if inv.get("ok") and isinstance(inv.get("data"), dict):
            for v in inv["data"].values():
                if isinstance(v, list) and any("100%" in str(it.get("持股比例") or "") for it in v if isinstance(it, dict)):
                    parts.append("一人公司")
                    break
        shr = biz.get("get_shareholder_info") or {}
        if shr.get("ok") and isinstance(shr.get("data"), dict):
            for v in shr["data"].values():
                if isinstance(v, list) and len(v) == 1:
                    parts.append("一人公司")
        if parts:
            features.append(" ".join(parts))
    text = " ".join(features)
    if not text:
        return []

    db = SessionLocal()
    try:
        cases = db.query(KnowledgeCase).all()
        hits = []
        for c in cases:
            kw = f"{c.keywords or ''},{c.tags or ''},{c.scenario or ''}"
            if _match_keywords(text, kw):
                hits.append({
                    "scenario": c.scenario,
                    "title": c.title,
                    "summary": c.summary or "",
                    "approach": c.approach or "",
                    "result": c.result or "",
                })
        return hits
    except Exception:
        return []
    finally:
        db.close()
