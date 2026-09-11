"""로그인 사용자가 직접 등록하는 개인 포트폴리오 트래커 (본인만의 신규 기능).

기존 auth(로그인)와 시장 시세 조회를 실제로 엮어, 보유 종목의 실시간
평가손익을 계산한다. 다른 학생 제출과 구분되는 이 앱만의 기능이다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes.auth import current_user
from app.core.database import get_db
from app.models.portfolio_holding import PortfolioHolding
from app.models.user import User

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


class HoldingCreate(BaseModel):
    ticker: str = Field(pattern=r"^\d{6}$")
    market: str = Field(pattern=r"^(KOSPI|KOSDAQ)$")
    name: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0, le=1_000_000_000)
    buy_price: float = Field(gt=0, le=1_000_000_000)


class HoldingResponse(BaseModel):
    id: int
    ticker: str
    market: str
    name: str
    quantity: float
    buy_price: float

    class Config:
        from_attributes = True


async def _live_price(ticker: str, market: str) -> float | None:
    symbol = f"{ticker}.{'KS' if market == 'KOSPI' else 'KQ'}"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "FinanceInsightLab/1.0"})
            response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        price = result["meta"].get("regularMarketPrice")
        return float(price) if price is not None else None
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None


@router.get("/holdings", response_model=list[HoldingResponse])
def list_holdings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.user_id == user.id)
        .order_by(PortfolioHolding.id.desc())
        .all()
    )


@router.post("/holdings", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
def create_holding(payload: HoldingCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    holding = PortfolioHolding(user_id=user.id, **payload.model_dump())
    db.add(holding)
    db.commit()
    db.refresh(holding)
    return holding


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(holding_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    holding = (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.id == holding_id, PortfolioHolding.user_id == user.id)
        .first()
    )
    if not holding:
        raise HTTPException(status_code=404, detail="보유 종목을 찾을 수 없습니다.")
    db.delete(holding)
    db.commit()


@router.get("/summary")
async def portfolio_summary(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """보유 종목의 실시간 시세를 조회해 평가금액·손익·비중을 계산한다."""
    holdings = (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.user_id == user.id)
        .order_by(PortfolioHolding.id.desc())
        .all()
    )
    if not holdings:
        return {"holdings": [], "total_cost": 0, "total_value": 0, "total_pnl": 0, "total_pnl_percent": 0, "updated_at": datetime.now(timezone.utc).isoformat()}

    prices = await asyncio.gather(*(_live_price(h.ticker, h.market) for h in holdings))

    rows = []
    total_cost = 0.0
    total_value = 0.0
    for holding, price in zip(holdings, prices):
        quantity = float(holding.quantity)
        buy_price = float(holding.buy_price)
        cost = quantity * buy_price
        value = quantity * price if price is not None else cost
        pnl = value - cost
        rows.append({
            "id": holding.id,
            "ticker": holding.ticker,
            "market": holding.market,
            "name": holding.name,
            "quantity": quantity,
            "buy_price": buy_price,
            "current_price": price,
            "cost": round(cost, 2),
            "value": round(value, 2),
            "pnl": round(pnl, 2),
            "pnl_percent": round(pnl / cost * 100, 2) if cost else 0.0,
            "price_available": price is not None,
        })
        total_cost += cost
        total_value += value

    for row in rows:
        row["weight_percent"] = round(row["value"] / total_value * 100, 2) if total_value else 0.0

    total_pnl = total_value - total_cost
    return {
        "holdings": rows,
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_percent": round(total_pnl / total_cost * 100, 2) if total_cost else 0.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
