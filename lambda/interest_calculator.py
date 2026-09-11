"""예금·적금 이자 계산기 — AWS Lambda (API Gateway HTTP API, payload v2.0).

의존성 없음(순수 표준 라이브러리). 이자소득세는 15.4%(소득세 14% + 지방소득세 1.4%) 가정.
비과세·세금우대·중도해지·우대금리 조건은 반영하지 않는 학습용 계산이다.
"""

from __future__ import annotations

import json

_TAX_RATE = 0.154  # 이자소득세 15.4%
_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **_CORS},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _deposit(principal: float, annual_rate: float, months: int, compounding: str) -> dict:
    """예금: 목돈을 한 번 예치."""
    r = annual_rate / 100
    if compounding == "compound":  # 월복리
        maturity = principal * (1 + r / 12) ** months
        pretax_interest = maturity - principal
    else:  # 단리
        pretax_interest = principal * r * months / 12
        maturity = principal + pretax_interest
    return _summary(principal, pretax_interest)


def _savings(monthly: float, annual_rate: float, months: int, compounding: str) -> dict:
    """적금: 매월 일정액을 납입 (매월 초 납입 가정)."""
    r = annual_rate / 100
    principal = monthly * months
    if compounding == "compound":  # 월복리
        maturity = 0.0
        for _ in range(months):
            maturity = (maturity + monthly) * (1 + r / 12)
        pretax_interest = maturity - principal
    else:  # 단리 — n개월치, (n-1)+...+1+0 개월 이자
        # k번째 납입금은 (months - k + 1)개월간 예치
        pretax_interest = sum(monthly * r * (months - k) / 12 for k in range(months))
    return _summary(principal, pretax_interest)


def _summary(principal: float, pretax_interest: float) -> dict:
    tax = pretax_interest * _TAX_RATE
    aftertax_interest = pretax_interest - tax
    maturity_aftertax = principal + aftertax_interest
    effective_rate = (aftertax_interest / principal * 100) if principal else 0.0
    return {
        "principal": round(principal),
        "pretax_interest": round(pretax_interest),
        "tax": round(tax),
        "tax_rate_percent": _TAX_RATE * 100,
        "aftertax_interest": round(aftertax_interest),
        "maturity_amount": round(maturity_aftertax),
        "aftertax_effective_return_percent": round(effective_rate, 3),
    }


def handler(event: dict, context: object = None) -> dict:
    method = (event.get("requestContext", {}).get("http", {}).get("method") or "POST").upper()
    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    try:
        payload = json.loads(event.get("body") or "{}")
    except (ValueError, TypeError):
        return _resp(400, {"error": "요청 본문이 올바른 JSON이 아닙니다."})

    product = str(payload.get("product", "deposit"))
    compounding = str(payload.get("compounding", "compound"))
    if compounding not in ("simple", "compound"):
        return _resp(400, {"error": "compounding 은 'simple' 또는 'compound' 여야 합니다."})

    try:
        annual_rate = float(payload.get("annual_rate", 0))
        months = int(payload.get("months", 0))
    except (ValueError, TypeError):
        return _resp(400, {"error": "annual_rate 와 months 는 숫자여야 합니다."})

    if not (0 < months <= 600):
        return _resp(400, {"error": "months 는 1~600 사이여야 합니다."})
    if not (0 <= annual_rate <= 30):
        return _resp(400, {"error": "annual_rate 는 0~30(%) 사이여야 합니다."})

    try:
        if product == "savings":
            monthly = float(payload.get("monthly_amount", 0))
            if not (0 < monthly <= 100_000_000):
                return _resp(400, {"error": "monthly_amount 는 1~1억 사이여야 합니다."})
            result = _savings(monthly, annual_rate, months, compounding)
        else:
            principal = float(payload.get("principal", 0))
            if not (0 < principal <= 10_000_000_000):
                return _resp(400, {"error": "principal 은 1~100억 사이여야 합니다."})
            result = _deposit(principal, annual_rate, months, compounding)
    except (ValueError, TypeError, OverflowError):
        return _resp(400, {"error": "계산에 실패했습니다. 입력값을 확인하세요."})

    return _resp(200, {
        "product": "savings" if product == "savings" else "deposit",
        "compounding": compounding,
        "annual_rate_percent": annual_rate,
        "months": months,
        **result,
        "disclaimer": "이자소득세 15.4% 가정. 비과세·세금우대·우대금리·중도해지는 반영하지 않은 학습용 계산입니다.",
    })
