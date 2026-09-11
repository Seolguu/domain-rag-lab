from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, func

from app.core.database import Base


class PortfolioHolding(Base):
    """로그인한 사용자가 직접 등록하는 개인 보유 종목 (본인만의 신규 기능)."""

    __tablename__ = "portfolio_holdings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    market = Column(String(20), nullable=False)  # KOSPI | KOSDAQ
    name = Column(String(80), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    buy_price = Column(Numeric(16, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
