"""智能提醒规则引擎（21条，代码化）

对应《智能提醒规则库完整定义.md》。每条规则 = (rule_id, check, trigger_desc, content)。
match() 遍历规则表返回触发的提醒，只显示相关的，不信息轰炸。
"""
from dataclasses import dataclass, field


@dataclass
class Reminder:
    rule_id: str
    trigger: str
    content: str


@dataclass
class Rule:
    rule_id: str
    check: callable
    trigger_desc: str
    content: str


def _count_collaterals(collateral: str | None) -> int:
    """粗略统计抵押物数量（组合策略，兼容多种真实表述）。

    1) 数"第X号"证号段（最可靠，如"第201034568号、第201034616号"→2）
    2) 数"证号"关键词出现次数
    3) 数"名下/位于"标记（多套住宅场景）
    4) 数"一套/两套/N套"（备用）
    无法判定返回 1。
    """
    if not collateral:
        return 0
    import re
    nums = re.findall(r"第\s*[\dA-Za-z]+\s*号", collateral)
    if nums:
        return len(nums)
    if re.search(r"证号", collateral):
        return len(re.findall(r"证号", collateral))
    if re.search(r"名下|位于", collateral):
        return len(re.findall(r"名下|位于", collateral))
    if re.search(r"[一二两三四五六七八九十\d]+套|一套", collateral):
        return len(re.findall(r"[一二两三四五六七八九十\d]+套|一套", collateral))
    return 1


def _contains(text: str | None, keywords: list[str]) -> bool:
    if not text:
        return False
    return any(k in text for k in keywords)


# ---------- A. 抵押物相关 ----------
def _build_rules() -> list[Rule]:
    return [
        Rule("A1", lambda c, d: _count_collaterals(c.collateral) > 1,
             "抵押物数量>1", "同一债权项下多个抵押物须整体拍卖，不可单独竞买，需整体评估价值和处置难度"),
        Rule("A2", lambda c, d: _contains(c.collateral, ["第二顺位", "三顺位", "二押", "三押"]),
             "存在第二/三顺位抵押", "优先债权需先受偿，实际受偿金额可能大幅缩水"),
        Rule("A3", lambda c, d: _contains(c.collateral, ["轮候查封", "轮候"]),
             "存在轮候查封", "首封法院主导处置，周期可能较长；轮候查封债权人可能参与分配"),
        Rule("A4", lambda c, d: _contains(c.collateral, ["租赁", "租约", "出租", "备案"]),
             "有租赁备案/已知租约", "买卖不破租赁，影响交付和成交价格"),
        Rule("A5", lambda c, d: _contains(c.collateral, ["占用", "第三方占用", "有人住"]),
             "抵押物被第三方占用", "清场交付不确定，建议实地查看"),
        Rule("A6", lambda c, d: _contains(c.collateral, ["划拨"]),
             "划拨土地", "需补缴土地出让金（评估地价40%~60%）"),
        Rule("A7", lambda c, d: _contains(c.collateral, ["在建工程", "在建"]),
             "在建工程", "可能存在建设工程款优先受偿权"),
        Rule("A8", lambda c, d: _contains(c.collateral, ["工业厂房", "厂房", "集体土地", "工业用地"]),
             "工业厂房/集体土地", "流转受限，变现难度高"),
        Rule("A9", lambda c, d: c.debtor_type == "person" and _contains(c.collateral, ["住宅", "住房", "唯一住房"]),
             "自然人唯一住房", "执行难度大，需保障基本居住（5~8年租金）"),
        Rule("A10", lambda c, d: _contains(c.collateral, ["违建", "改建", "无证", "违章"]),
             "违建/改建", "无证部分不在抵押范围，可能无法过户"),

        # B. 法律程序相关
        Rule("B1", lambda c, d: _contains(c.judicial_status, ["破产", "重整", "清算"]),
             "债务人进入破产程序", "执行中止，需申报债权，回收重大不确定"),
        Rule("B2", lambda c, d: _contains(c.judicial_status, ["刑事", "刑民"]),
             "债务人涉刑事案件", "先刑后民，执行可能中止"),
        Rule("B3", lambda c, d: c.guaranty_type == "保证" and c.guarantor,
             "保证期间可能已过", "保证人可能免责，需查阅原合同确认"),
        Rule("B4", lambda c, d: _contains(c.judicial_status, ["执行中", "已判决"]),
             "申请执行时效", "确认是否在法定期限内申请执行"),
        Rule("B5", lambda c, d: not (d and d.get("legal_documents")),
             "未检索到判决书", "无法确认金额利率，本息为估算，建议补充"),

        # C. 交易成本相关
        Rule("C1", lambda c, d: _contains(c.judicial_status, ["拍卖"]) or (d and d.get("disposal_path") == "司法拍卖"),
             "司法拍卖处置", "买受人承担全部税费（成交价10%~30%），商业用房土地增值税率较高"),
        Rule("C2", lambda c, d: _contains(c.collateral, ["欠费", "欠缴", "物业费", "水电", "税费"]),
             "欠缴税费", "物业费、水电、土地使用税等欠缴，过户需结清"),
        Rule("C3", lambda c, d: d and d.get("disposal_path") == "债权转让",
             "债权转让", "需书面通知债务人，建议EMS保留凭证"),
        Rule("C4", lambda c, d: _contains(c.collateral, ["权属", "证载", "不一致"]),
             "权属不一致", "抵押物权属与证载不一致时以不动产登记簿为准，建议查档"),

        # D. 自然人专项
        Rule("D1", lambda c, d: c.debtor_type == "person" and not (d and d.get("legal_documents")),
             "自然人无判决书", "自然人民事执行能力有限，重点关注抵押物"),
        Rule("D2", lambda c, d: c.debtor_type == "person" and (d and (d.get("execution_cases") or 0) >= 2),
             "多个被执行案件", "多债权人参与分配，受偿比例可能低于预期"),
    ]


class ReminderEngine:
    def __init__(self) -> None:
        self.rules: list[Rule] = _build_rules()

    def match(self, claim, dd_result: dict | None = None) -> list[Reminder]:
        """遍历规则表，返回触发提醒（按 A→D 顺序）。dd_result 为尽调引擎输出聚合。"""
        reminders = []
        for rule in self.rules:
            try:
                if rule.check(claim, dd_result or {}):
                    reminders.append(Reminder(rule_id=rule.rule_id, trigger=rule.trigger_desc, content=rule.content))
            except Exception:  # noqa: BLE001  单条规则异常不影响整体
                continue
        return reminders
