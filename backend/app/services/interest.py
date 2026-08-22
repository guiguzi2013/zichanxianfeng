"""本息计算服务（尽调引擎节点⑤，纯代码不调 LLM）

有判决书：按判决利率+罚息规则精确计算
无判决书：按 LPR 单利估算（标注仅供参考）
"""
from dataclasses import dataclass
from datetime import date

DAYS_PER_YEAR = 365
DEFAULT_LPR_RATE = 0.0345  # 无判决书估算利率；业务侧可用 config 覆盖


@dataclass
class InterestResult:
    items: list[dict]          # [{name, amount_cents, note}]
    total_cents: int
    calculation_mode: str      # with_judgment / lpr_estimate
    basis_note: str


def calculate_interest(
    principal_cents: int,
    start_date: date,
    end_date: date,
    *,
    has_judgment: bool = False,
    judgment_rate: float | None = None,     # 年化利率，如 0.0435
    judgment_penalty_per_day: float | None = None,  # 日罚息率，如 0.000175
) -> InterestResult:
    """计算本息合计（分）。

    Args:
        principal_cents: 本金（分）
        start_date: 起算日
        end_date: 截止日（尽调当日）
    """
    days = max((end_date - start_date).days, 0)

    if has_judgment and judgment_rate:
        rate = judgment_rate
        interest = int(round(principal_cents * rate * days / DAYS_PER_YEAR))
        items = [
            {"name": "本金", "amount_cents": principal_cents, "note": ""},
            {"name": "利息", "amount_cents": interest, "note": f"{start_date} 至 {end_date}，利率{rate*100:.2f}%/年（{days}天）"},
        ]
        if judgment_penalty_per_day:
            penalty = int(round(principal_cents * judgment_penalty_per_day * days))
            items.append({"name": "罚息", "amount_cents": penalty, "note": f"日罚息率{judgment_penalty_per_day:.6f}（{days}天）"})
        total = principal_cents + sum(i["amount_cents"] for i in items[1:])
        return InterestResult(
            items=items,
            total_cents=total,
            calculation_mode="with_judgment",
            basis_note="按判决书利率计算",
        )

    # LPR 估算
    rate = DEFAULT_LPR_RATE
    interest = int(round(principal_cents * rate * days / DAYS_PER_YEAR))
    items = [
        {"name": "本金", "amount_cents": principal_cents, "note": ""},
        {"name": "利息（估算）", "amount_cents": interest, "note": f"{start_date} 至 {end_date}，按LPR {rate*100:.2f}%/年（{days}天）"},
    ]
    return InterestResult(
        items=items,
        total_cents=principal_cents + interest,
        calculation_mode="lpr_estimate",
        basis_note="因缺失裁决文书按LPR估算仅供参考",
    )
