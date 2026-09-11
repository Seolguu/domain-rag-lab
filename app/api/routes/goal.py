"""목표자금(은퇴·내집마련 등) 계산기 — 필요 월 적립액을 역산 (본인만의 신규 기능).

연금 미래가치 공식을 사용한 순수 계산이며 외부 의존성이 없다.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/goal", tags=["goal"])


class GoalRequest(BaseModel):
    target_amount: float = Field(gt=0, le=100_000_000_000)
    years: int = Field(ge=1, le=60)
    annual_return_percent: float = Field(ge=0, le=30)
    current_savings: float = Field(default=0, ge=0, le=100_000_000_000)


@router.post("/required-savings")
def required_savings(req: GoalRequest) -> dict[str, object]:
    months = req.years * 12
    monthly_rate = (req.annual_return_percent / 100) / 12

    # 현재 보유자금이 이자율만으로 목표기간 후 자라는 미래가치
    fv_current = req.current_savings * (1 + monthly_rate) ** months
    remaining = max(0.0, req.target_amount - fv_current)

    if monthly_rate == 0:
        required_monthly = remaining / months if months else 0.0
    else:
        annuity_factor = ((1 + monthly_rate) ** months - 1) / monthly_rate
        required_monthly = remaining / annuity_factor if annuity_factor else 0.0

    total_contribution = required_monthly * months
    total_principal = total_contribution + req.current_savings
    total_growth = req.target_amount - total_principal

    # 연차별 잔액 추이 (그래프용)
    timeline = []
    balance = req.current_savings
    for month in range(1, months + 1):
        balance = balance * (1 + monthly_rate) + required_monthly
        if month % 12 == 0 or month == months:
            timeline.append({"year": round(month / 12, 1), "balance": round(balance)})

    return {
        "required_monthly_savings": round(required_monthly),
        "total_contribution": round(total_contribution),
        "total_principal": round(total_principal),
        "total_growth": round(max(0.0, total_growth)),
        "target_amount": req.target_amount,
        "years": req.years,
        "timeline": timeline,
        "disclaimer": "예상 수익률이 매월 일정하다고 가정한 학습용 역산입니다. 실제 투자수익률은 변동합니다.",
    }
