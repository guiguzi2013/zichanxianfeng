"""追索行动方案生成器

中心思想：用户尽调的目的 = 追查债务人与担保人的财产线索、追回钱款。
本模块基于尽调数据（本息/抵押物/司法风险/保证人）生成「下一步怎么做」的行动方案，
供报告的处置建议版块使用。规则可扩展，不依赖 LLM（稳定、免费、即时）。
"""

# 风险因子中文名
EXEC = "被执行人"
DISHONEST = "失信信息"
LIMIT_HIGH = "限制高消费"
TERMINATED = "终本案件"

_PRIORITY_LABEL = {"high": "高", "medium": "中", "info": "提示"}


def _factor_counts(debtor: dict) -> dict[str, int]:
    factors = debtor.get("risk_factors") or []
    return {f["label"]: f.get("count") or 0 for f in factors}


def build_recovery_plan(claim, nodes: dict) -> dict:
    """基于尽调数据生成追索行动方案。

    Returns:
        {
          "debt_total_wan": 123.45,
          "priority_text": "高/中",
          "actions": [{"step": 1, "title": "...", "detail": "...", "priority": "high"}],
          "paths": {"auction": {...}, "debt_in_kind": {...}, "worst": {...}},
          "reminders": [...],
        }
    """
    interest = nodes.get("interest") or {}
    total_cents = interest.get("total_cents") if interest.get("mode") else (claim.principal_cents or 0)
    total_wan = (total_cents or 0) / 100 / 10000
    debtor = nodes.get("debtor") or {}
    collateral = nodes.get("collateral") or {}
    fc = _factor_counts(debtor)

    actions: list[dict] = []

    # 1) 有抵押物 → 诉前保全（防转移，最高优先）
    if collateral.get("present") and claim.collateral:
        actions.append({
            "step": len(actions) + 1, "title": "诉前财产保全",
            "detail": f"对抵押物「{claim.collateral}」立即申请诉前财产保全，防止转移/变卖；保全后 30 日内必须起诉（否则保全解除）。",
            "priority": "high",
        })

    # 2) 已是被执行人 → 参与分配
    if fc.get(EXEC):
        actions.append({
            "step": len(actions) + 1, "title": "参与执行分配",
            "detail": f"债务人已是被执行人（{fc[EXEC]} 条记录），说明已有案件在执行中：尽快查明执行法院，申请参与分配、申报债权，避免其财产被在先债权人执行完毕。",
            "priority": "high",
        })

    # 3) 有保证人 → 列为共同被告
    if claim.guarantor:
        actions.append({
            "step": len(actions) + 1, "title": "保证人连带追索",
            "detail": f"将保证人「{claim.guarantor}」列为共同被告，主张连带清偿责任（需核对保证合同条款与保证期间是否届满）。",
            "priority": "high",
        })

    # 4) 失信/限高 → 施压
    if fc.get(DISHONEST) or fc.get(LIMIT_HIGH):
        actions.append({
            "step": len(actions) + 1, "title": "信用惩戒施压",
            "detail": f"债务人已被{'失信' if fc.get(DISHONEST) else ''}{'、' if fc.get(DISHONEST) and fc.get(LIMIT_HIGH) else ''}{'限高' if fc.get(LIMIT_HIGH) else ''}（{fc.get(DISHONEST, 0)}/{fc.get(LIMIT_HIGH, 0)} 条），可申请继续限制高消费、联动布控，以促履行。",
            "priority": "medium",
        })

    # 5) 无财产线索 → 调查令
    has_clue = collateral.get("present") or any(fc.values())
    if not has_clue:
        actions.append({
            "step": len(actions) + 1, "title": "深挖财产线索",
            "detail": "未发现明显可执行财产：建议申请律师调查令 / 法院财产报告令，查询银行账户、不动产、车辆、应收账款、到期债权等，必要时追加股东出资责任。",
            "priority": "medium",
        })

    # 6) 终本 → 恢复执行提示
    if fc.get(TERMINATED):
        actions.append({
            "step": len(actions) + 1, "title": "关注终本案件",
            "detail": f"存在终本案件（{fc[TERMINATED]} 条）：前期执行未果，需持续补充财产线索，待发现可供执行财产后申请恢复执行。",
            "priority": "medium",
        })

    # 7) 诉讼时效提醒
    actions.append({
        "step": len(actions) + 1, "title": "核查诉讼时效",
        "detail": "确认债权是否临近 3 年诉讼时效：必要时先行发函催收（中断时效）或尽快起诉，防止债权因时效届满丧失胜诉权。",
        "priority": "info",
    })

    # 路径对比（版块8 要求：两条路径 + 最坏情况）
    has_mortgage = collateral.get("present") and claim.collateral
    paths = {
        "auction": {
            "title": "路径一：正常拍卖受偿",
            "feasibility": "可行" if has_mortgage else "取决于财产线索",
            "detail": (
                f"保全/查封抵押物「{claim.collateral}」后诉讼，胜诉进入执行程序，法院评估拍卖变价受偿。"
                if has_mortgage else
                "取得执行依据后申请查封债务人在执行标的范围内的财产（账户/股权/不动产），拍卖变价受偿。"
            ),
            "risk": "需关注抵押物是否存在在先查封/轮候、租赁占用、唯一住房等障碍。",
        },
        "debt_in_kind": {
            "title": "路径二：以物抵债",
            "feasibility": "流拍后适用",
            "detail": (
                f"抵押物「{claim.collateral}」流拍后，可申请以物抵债或变卖；需核算过户税费与清偿顺位。"
                if has_mortgage else
                "如无可变现财产，可与债务人协商以实物资产抵偿债务（需评估资产价值与过户障碍）。"
            ),
            "risk": "以物抵债需全体债权人/法院认可，且要核算税费成本。",
        },
        "worst": {
            "title": "最坏情况：执行不能的兜底",
            "detail": (
                "对保证人追索连带责任；申请追加未实缴出资股东；持续关注失信/限高惩戒；待发现新财产线索后申请恢复执行。"
                if claim.guarantor else
                "申请追加未实缴出资股东/实际控制人；持续关注失信限高惩戒；发现新财产线索后申请恢复执行。"
            ),
            "risk": "若全部途径受阻，需评估债权转让或核销的可行性。",
        },
    }

    reminders = []
    if fc.get(EXEC):
        reminders.append("债务人已被执行，行动要快：参与分配有先后顺序，越晚申报受偿越少。")
    if claim.guarantor:
        reminders.append("保证责任可能因保证期间/保证方式（一般 vs 连带）不同而受限，先核对保证合同。")
    if collateral.get("present") is False:
        reminders.append("本债权缺少抵押物信息，回收高度依赖保证人偿付能力与后续财产线索挖掘。")

    has_high = any(a["priority"] == "high" for a in actions)
    return {
        "debt_total_wan": round(total_wan, 2),
        "priority_text": "高" if has_high else "中",
        "actions": actions,
        "paths": paths,
        "reminders": reminders,
    }
