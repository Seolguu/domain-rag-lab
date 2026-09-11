"""교육용 퀀트 분석 — 몬테카를로 포트폴리오 시나리오, VaR/CVaR, MA 크로스오버 백테스트.

investment-analysis 프로젝트의 quant 라우터를 이식해 self-contained 로 만든 것.
모든 수치는 학습용 가정이며 투자 예측이 아니다.
"""

from __future__ import annotations

import base64
import io

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/quant", tags=["quant"])

_KOREAN_FONT_READY = False


def _configure_korean_font(plt) -> None:
    global _KOREAN_FONT_READY
    if _KOREAN_FONT_READY:
        return
    from pathlib import Path
    import matplotlib.font_manager as fm

    for font_path in (
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ):
        if font_path.exists():
            fm.fontManager.addfont(str(font_path))
            plt.rcParams["font.family"] = fm.FontProperties(fname=str(font_path)).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False
    _KOREAN_FONT_READY = True


class PortfolioScenarioRequest(BaseModel):
    profile: str = Field(default="balanced", pattern="^(stable|balanced|growth)$")
    initial_amount: int = Field(default=10_000_000, ge=0, le=1_000_000_000)
    monthly_amount: int = Field(default=500_000, ge=0, le=100_000_000)
    years: int = Field(default=10, ge=1, le=30)


class RiskRequest(BaseModel):
    confidence: float = Field(default=0.95, ge=0.90, le=0.99)
    n_scenarios: int = Field(default=10000, ge=1000, le=100000)
    portfolio_value: float = Field(default=100_000_000, ge=1_000_000)


class BacktestRequest(BaseModel):
    fast_ma: int = Field(default=20, ge=5, le=60)
    slow_ma: int = Field(default=60, ge=20, le=200)
    n_days: int = Field(default=1260, ge=252, le=5040)


class PortfolioRequest(BaseModel):
    n_simulations: int = Field(default=3000, ge=500, le=10000)
    risk_free: float = Field(default=0.03, ge=0.0, le=0.1)


class FinancialKnowledgeRequest(BaseModel):
    n_simulations: int = Field(default=3000, ge=500, le=10000)
    risk_free: float = Field(default=0.03, ge=0.0, le=0.1)


@router.post("/portfolio-scenario")
def portfolio_scenario(req: PortfolioScenarioRequest) -> dict[str, object]:
    """단순 포트폴리오 프로파일에 대한 교육용 몬테카를로 적립 시뮬레이션."""
    import numpy as np

    profiles = {
        "stable": {"label": "안정 중심", "return": 0.045, "volatility": 0.07},
        "balanced": {"label": "균형 중심", "return": 0.065, "volatility": 0.12},
        "growth": {"label": "성장 중심", "return": 0.085, "volatility": 0.18},
    }
    config = profiles[req.profile]
    rng = np.random.default_rng(20260911)
    paths = 5_000
    balances = np.full(paths, float(req.initial_amount))
    monthly_return = (1 + config["return"]) ** (1 / 12) - 1
    monthly_volatility = config["volatility"] / np.sqrt(12)
    points = [{"year": 0, "cautious": int(req.initial_amount), "middle": int(req.initial_amount), "positive": int(req.initial_amount)}]

    for month in range(1, req.years * 12 + 1):
        changes = rng.normal(monthly_return, monthly_volatility, paths)
        balances = np.maximum(0, (balances + req.monthly_amount) * (1 + changes))
        if month % 12 == 0:
            cautious, middle, positive = np.percentile(balances, [10, 50, 90])
            points.append({
                "year": month // 12,
                "cautious": int(round(cautious)),
                "middle": int(round(middle)),
                "positive": int(round(positive)),
            })

    total_paid = req.initial_amount + req.monthly_amount * req.years * 12
    final = points[-1]
    return {
        "profile_label": config["label"],
        "years": req.years,
        "total_paid": int(total_paid),
        "points": points,
        "summary": {"cautious": final["cautious"], "middle": final["middle"], "positive": final["positive"]},
        "explanation": "같은 구성이라도 시장 흐름에 따라 결과가 달라질 수 있음을 보여주는 학습용 가상 시나리오입니다.",
    }


@router.post("/risk")
def quant_risk(req: RiskRequest) -> dict[str, object]:
    """VaR / CVaR 리스크 분석."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    _configure_korean_font(plt)

    rng = np.random.default_rng(42)
    mu, sigma = 0.0004, 0.012
    daily_ret = rng.normal(mu, sigma, req.n_scenarios).astype(float)

    alpha = 1 - req.confidence
    var_pct = float(np.percentile(daily_ret, alpha * 100))
    cvar_pct = float(daily_ret[daily_ret <= var_pct].mean())
    var_amt = abs(var_pct) * req.portfolio_value
    cvar_amt = abs(cvar_pct) * req.portfolio_value

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), facecolor="#0f172a")
    text_c, grid_c = "#e2e8f0", "#1e293b"

    ax = axes[0]
    ax.set_facecolor("#1e293b")
    ax.hist(daily_ret * 100, bins=80, color="#3b82f6", alpha=0.75, edgecolor="none")
    ax.axvline(var_pct * 100, color="#f97316", lw=2, linestyle="--", label=f"VaR ({req.confidence:.0%}): {var_pct:.2%}")
    ax.axvline(cvar_pct * 100, color="#ef4444", lw=2, linestyle="-", label=f"CVaR: {cvar_pct:.2%}")
    ax.set_xlabel("일간 수익률 (%)", color=text_c)
    ax.set_ylabel("빈도", color=text_c)
    ax.set_title(f"수익률 분포 & VaR/CVaR ({req.confidence:.0%} 신뢰수준)", color=text_c, fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, labelcolor=text_c, facecolor="#0f172a")
    ax.tick_params(colors=text_c)
    ax.spines[:].set_color(grid_c)
    ax.grid(True, alpha=0.2, color=grid_c)

    ax2 = axes[1]
    ax2.set_facecolor("#1e293b")
    labels = ["VaR 예상 손실", "CVaR 예상 손실", "포트폴리오 가치"]
    values = [var_amt / 1e6, cvar_amt / 1e6, req.portfolio_value / 1e6]
    bars = ax2.barh(labels, values, color=["#f97316", "#ef4444", "#22c55e"], alpha=0.85, edgecolor=grid_c)
    for bar, val in zip(bars, values):
        ax2.text(val + req.portfolio_value / 1e6 * 0.01, bar.get_y() + bar.get_height() / 2,
                 f"{val:.1f}M", va="center", color=text_c, fontsize=10, fontweight="bold")
    ax2.set_xlabel("금액 (백만원)", color=text_c)
    ax2.set_title("리스크 금액 비교", color=text_c, fontsize=11, fontweight="bold")
    ax2.tick_params(colors=text_c)
    ax2.spines[:].set_color(grid_c)
    ax2.grid(True, alpha=0.2, color=grid_c, axis="x")

    fig.patch.set_facecolor("#0f172a")
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close(fig)

    return {
        "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
        "var_pct": round(var_pct, 6),
        "cvar_pct": round(cvar_pct, 6),
        "var_amount": round(var_amt, 0),
        "cvar_amount": round(cvar_amt, 0),
        "confidence": req.confidence,
        "portfolio_value": req.portfolio_value,
    }


@router.post("/backtest")
def quant_backtest(req: BacktestRequest) -> dict[str, object]:
    """MA 크로스오버 전략 백테스트 (합성 가격 경로 기준)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    _configure_korean_font(plt)

    rng = np.random.default_rng(42)
    dt = 1 / 252
    mu, sigma = 0.08, 0.20
    daily_r = rng.normal((mu - 0.5 * sigma**2) * dt, sigma * np.sqrt(dt), req.n_days)
    prices = pd.Series(
        100 * np.exp(np.cumsum(daily_r)),
        index=pd.date_range("2020-01-01", periods=req.n_days, freq="B"),
        name="Close",
    )

    df = pd.DataFrame({"Close": prices})
    df["MA_fast"] = df["Close"].rolling(req.fast_ma).mean()
    df["MA_slow"] = df["Close"].rolling(req.slow_ma).mean()
    df["Signal"] = (df["MA_fast"] > df["MA_slow"]).astype(float)
    df["Position"] = df["Signal"].shift(1).fillna(0)
    df["Ret"] = df["Close"].pct_change()
    df["Strat_Ret"] = df["Position"] * df["Ret"]
    df["Strat_Cum"] = (1 + df["Strat_Ret"]).cumprod()
    df["BH_Cum"] = (1 + df["Ret"]).cumprod()
    df = df.dropna()

    ret = df["Strat_Ret"]
    n_years = len(ret) / 252
    cum = df["Strat_Cum"]
    cagr = float(cum.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 else 0
    excess = ret - 0.03 / 252
    sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0
    rolling_max = cum.cummax()
    dd = (cum - rolling_max) / rolling_max
    mdd = float(dd.min())
    wins, losses = ret[ret > 0], ret[ret < 0]
    win_rate = len(wins) / max(len(ret[ret != 0]), 1)
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and losses.sum() != 0 else 9.99
    n_trades = int(df["Position"].diff().abs()[lambda x: x > 0].count())
    total_ret = float(cum.iloc[-1] - 1)
    bh_ret = float(df["BH_Cum"].iloc[-1] - 1)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), facecolor="#0f172a")
    text_c, grid_c = "#e2e8f0", "#1e293b"

    ax1.set_facecolor("#1e293b")
    ax1.plot(df.index, df["Close"], color="#64748b", lw=0.8, label="주가")
    ax1.plot(df.index, df["MA_fast"], color="#3b82f6", lw=1.5, label=f"MA{req.fast_ma}")
    ax1.plot(df.index, df["MA_slow"], color="#f97316", lw=1.5, label=f"MA{req.slow_ma}")
    buy_m = (df["Position"] == 1) & (df["Position"].shift(1) == 0)
    sell_m = (df["Position"] == 0) & (df["Position"].shift(1) == 1)
    ax1.scatter(df.index[buy_m], df["Close"][buy_m], marker="^", color="#22c55e", s=50, zorder=5, label="매수")
    ax1.scatter(df.index[sell_m], df["Close"][sell_m], marker="v", color="#ef4444", s=50, zorder=5, label="매도")
    ax1.set_title(f"MA 크로스오버 전략 (MA{req.fast_ma}/MA{req.slow_ma})", color=text_c, fontsize=11, fontweight="bold")
    ax1.legend(fontsize=8, ncol=5, labelcolor=text_c, facecolor="#0f172a")
    ax1.tick_params(colors=text_c)
    ax1.spines[:].set_color(grid_c)
    ax1.grid(True, alpha=0.2, color=grid_c)

    ax2.set_facecolor("#1e293b")
    ax2.plot(df.index, df["Strat_Cum"], color="#3b82f6", lw=2, label=f"전략 ({total_ret:+.1%})")
    ax2.plot(df.index, df["BH_Cum"], color="#94a3b8", lw=2, ls="--", label=f"Buy & Hold ({bh_ret:+.1%})")
    ax2.axhline(1.0, color="#475569", lw=0.6)
    ax2.set_title("누적 수익률 비교", color=text_c, fontsize=11)
    ax2.legend(fontsize=9, labelcolor=text_c, facecolor="#0f172a")
    ax2.tick_params(colors=text_c)
    ax2.spines[:].set_color(grid_c)
    ax2.grid(True, alpha=0.2, color=grid_c)

    fig.patch.set_facecolor("#0f172a")
    fig.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close(fig)
    return {
        "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
        "metrics": {
            "cagr": round(cagr, 4), "sharpe": round(sharpe, 2), "mdd": round(mdd, 4),
            "win_rate": round(win_rate, 4), "profit_factor": round(pf, 2),
            "n_trades": n_trades, "total_return": round(total_ret, 4), "bh_return": round(bh_ret, 4),
        },
    }


@router.post("/portfolio")
def quant_portfolio(req: PortfolioRequest) -> dict[str, object]:
    """포트폴리오 최적화 — 효율적 프론티어 + Sharpe 극대화."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    _configure_korean_font(plt)

    tickers = ["KOSPI", "S&P500", "국채10Y", "금(Gold)", "BTC"]
    mu_ann = np.array([0.10, 0.12, 0.04, 0.07, 0.30])
    vol_ann = np.array([0.18, 0.17, 0.06, 0.15, 0.70])
    corr = np.array([
        [1.00, 0.75, 0.10, 0.10, 0.20],
        [0.75, 1.00, 0.05, 0.05, 0.25],
        [0.10, 0.05, 1.00, 0.20, 0.00],
        [0.10, 0.05, 0.20, 1.00, 0.05],
        [0.20, 0.25, 0.00, 0.05, 1.00],
    ])
    cov = np.outer(vol_ann, vol_ann) * corr
    n = len(tickers)
    rng = np.random.default_rng(42)
    rf = req.risk_free

    port_rets, port_vols, port_sharpes, all_weights = [], [], [], []
    for _ in range(req.n_simulations):
        w = rng.random(n)
        w /= w.sum()
        r = float(w @ mu_ann)
        v = float(np.sqrt(w @ cov @ w))
        port_rets.append(r)
        port_vols.append(v)
        port_sharpes.append((r - rf) / v)
        all_weights.append(w)

    port_rets = np.array(port_rets)
    port_vols = np.array(port_vols)
    port_sharpes = np.array(port_sharpes)
    all_weights = np.array(all_weights)
    best_i = int(np.argmax(port_sharpes))
    best_w = all_weights[best_i]
    inv_vol = 1 / vol_ann
    rp_w = inv_vol / inv_vol.sum()
    rp_r = float(rp_w @ mu_ann)
    rp_v = float(np.sqrt(rp_w @ cov @ rp_w))

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), facecolor="#0f172a")
    text_c, grid_c = "#e2e8f0", "#1e293b"

    ax = axes[0]
    ax.set_facecolor("#1e293b")
    sc = ax.scatter(port_vols * 100, port_rets * 100, c=port_sharpes, cmap="RdYlGn", s=4, alpha=0.6)
    ax.scatter(port_vols[best_i] * 100, port_rets[best_i] * 100, marker="*", color="#fbbf24", s=300, zorder=10,
               label=f"최적(Sharpe={port_sharpes[best_i]:.2f})")
    ax.scatter(rp_v * 100, rp_r * 100, marker="D", color="#22d3ee", s=120, zorder=10, label="Risk-Parity")
    for i, tk in enumerate(tickers):
        ax.scatter(vol_ann[i] * 100, mu_ann[i] * 100, marker="o", s=80, zorder=10)
        ax.annotate(tk, (vol_ann[i] * 100, mu_ann[i] * 100), textcoords="offset points", xytext=(5, 3), color=text_c, fontsize=8)
    cbar = plt.colorbar(sc, ax=ax)
    cbar.set_label("Sharpe Ratio", color=text_c)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=text_c)
    ax.set_xlabel("리스크 (변동성 %)", color=text_c)
    ax.set_ylabel("기대수익률 (%)", color=text_c)
    ax.set_title("효율적 프론티어", color=text_c, fontsize=12, fontweight="bold")
    ax.legend(fontsize=8, labelcolor=text_c, facecolor="#0f172a")
    ax.tick_params(colors=text_c)
    ax.spines[:].set_color(grid_c)
    ax.grid(True, alpha=0.2, color=grid_c)

    ax2 = axes[1]
    ax2.set_facecolor("#1e293b")
    colors = ["#3b82f6", "#22c55e", "#f97316", "#fbbf24", "#a78bfa"]
    bars = ax2.bar(tickers, best_w * 100, color=colors, alpha=0.85, edgecolor=grid_c)
    for bar, val in zip(bars, best_w):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5, f"{val:.1%}", ha="center", va="bottom",
                 color=text_c, fontsize=9, fontweight="bold")
    ax2.set_title(f"최적 포트폴리오 비중 (Sharpe={port_sharpes[best_i]:.2f})", color=text_c, fontsize=12, fontweight="bold")
    ax2.set_ylabel("비중 (%)", color=text_c)
    ax2.tick_params(colors=text_c)
    ax2.spines[:].set_color(grid_c)
    ax2.grid(True, alpha=0.2, color=grid_c, axis="y")

    fig.patch.set_facecolor("#0f172a")
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close(fig)

    return {
        "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
        "optimal_weights": {tk: round(float(w), 4) for tk, w in zip(tickers, best_w)},
        "optimal_return": round(float(port_rets[best_i]), 4),
        "optimal_vol": round(float(port_vols[best_i]), 4),
        "optimal_sharpe": round(float(port_sharpes[best_i]), 4),
        "riskparity_weights": {tk: round(float(w), 4) for tk, w in zip(tickers, rp_w)},
    }


@router.post("/financial-knowledge")
def quant_financial_knowledge(req: FinancialKnowledgeRequest) -> dict[str, object]:
    """금융상품 이해 + 자산배분방법론 통합 대시보드 (주식/ETF·채권·파생상품·포트폴리오이론·자산배분모델)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    _configure_korean_font(plt)

    rng = np.random.default_rng(7)
    n_days = 252
    asset_names = ["주식/ETF", "채권", "원자재", "현금"]
    mu = np.array([0.10, 0.04, 0.06, 0.025])
    vol = np.array([0.19, 0.07, 0.16, 0.01])
    corr = np.array([
        [1.00, -0.10, 0.25, 0.00],
        [-0.10, 1.00, 0.05, 0.00],
        [0.25, 0.05, 1.00, 0.00],
        [0.00, 0.00, 0.00, 1.00],
    ])
    cov = np.outer(vol, vol) * corr
    daily_mean = mu / 252
    daily_cov = cov / 252
    returns = rng.multivariate_normal(daily_mean, daily_cov, n_days)
    curves = np.cumprod(1 + returns, axis=0)

    inv_vol = 1 / vol
    risk_parity_w = inv_vol / inv_vol.sum()
    sixty_forty_w = np.array([0.60, 0.35, 0.00, 0.05])
    investor_view = np.array([0.005, 0.000, 0.006, 0.000])
    black_litterman_return = (mu * 0.75) + ((mu + investor_view) * 0.25)

    port_rets, port_vols, sharpes, weights = [], [], [], []
    for _ in range(req.n_simulations):
        w = rng.random(len(asset_names))
        w = w / w.sum()
        r = float(w @ mu)
        v = float(np.sqrt(w.T @ cov @ w))
        s = (r - req.risk_free) / v
        port_rets.append(r)
        port_vols.append(v)
        sharpes.append(s)
        weights.append(w)

    port_rets = np.array(port_rets)
    port_vols = np.array(port_vols)
    sharpes = np.array(sharpes)
    weights = np.array(weights)
    best_i = int(np.argmax(sharpes))
    mean_variance_w = weights[best_i]
    black_litterman_w = black_litterman_return / black_litterman_return.sum()

    def metrics(w: "np.ndarray") -> dict[str, float]:
        portfolio_daily = returns @ w
        cumulative = np.cumprod(1 + portfolio_daily)
        cagr = float(cumulative[-1] ** (252 / len(cumulative)) - 1)
        annual_vol = float(np.std(portfolio_daily) * np.sqrt(252))
        mdd = float(np.min(cumulative / np.maximum.accumulate(cumulative) - 1))
        downside = portfolio_daily[portfolio_daily < 0]
        downside_vol = float(np.std(downside) * np.sqrt(252)) if len(downside) else annual_vol
        sharpe = float((cagr - req.risk_free) / annual_vol) if annual_vol else 0.0
        sortino = float((cagr - req.risk_free) / downside_vol) if downside_vol else 0.0
        return {"cagr": round(cagr, 4), "volatility": round(annual_vol, 4), "mdd": round(mdd, 4),
                "sharpe": round(sharpe, 3), "sortino": round(sortino, 3)}

    strategies = {
        "60/40 사례": sixty_forty_w,
        "평균분산": mean_variance_w,
        "블랙-리터만": black_litterman_w,
        "Risk-Parity": risk_parity_w,
    }
    strategy_payload = {
        name: {"weights": {asset: round(float(weight), 4) for asset, weight in zip(asset_names, w)}, "metrics": metrics(w)}
        for name, w in strategies.items()
    }

    spots = np.linspace(70, 130, 121)
    call = np.maximum(spots - 100, 0) - 5
    put = np.maximum(100 - spots, 0) - 4
    straddle = call + put
    tenors = ["3M", "2Y", "5Y", "10Y", "30Y"]
    yields = np.array([4.6, 4.3, 4.0, 4.1, 4.25])

    text_c, grid_c = "#e2e8f0", "#334155"
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), facecolor="#0f172a")

    ax = axes[0, 0]
    ax.set_facecolor("#1e293b")
    for i, name in enumerate(asset_names):
        ax.plot(curves[:, i] * 100, label=name, linewidth=1.4)
    ax.set_title("주식/ETF · 채권 상품 이해: 자산군별 누적 성과", color=text_c, fontweight="bold")
    ax.set_ylabel("기준가", color=text_c)
    ax.legend(fontsize=8, labelcolor=text_c, facecolor="#0f172a")
    ax.tick_params(colors=text_c)
    ax.grid(True, alpha=0.2, color=grid_c)
    ax.spines[:].set_color(grid_c)

    ax = axes[0, 1]
    ax.set_facecolor("#1e293b")
    sc = ax.scatter(port_vols * 100, port_rets * 100, c=sharpes, cmap="viridis", s=5, alpha=0.55)
    ax.scatter(port_vols[best_i] * 100, port_rets[best_i] * 100, marker="*", s=260, color="#fbbf24", label="평균분산")
    rp_r = float(risk_parity_w @ mu)
    rp_v = float(np.sqrt(risk_parity_w.T @ cov @ risk_parity_w))
    ax.scatter(rp_v * 100, rp_r * 100, marker="D", s=110, color="#22c55e", label="Risk-Parity")
    ax.set_title("포트폴리오 이론: 효율적 투자선", color=text_c, fontweight="bold")
    ax.set_xlabel("변동성 (%)", color=text_c)
    ax.set_ylabel("기대수익률 (%)", color=text_c)
    ax.legend(fontsize=8, labelcolor=text_c, facecolor="#0f172a")
    ax.tick_params(colors=text_c)
    ax.grid(True, alpha=0.2, color=grid_c)
    ax.spines[:].set_color(grid_c)
    cbar = plt.colorbar(sc, ax=ax)
    cbar.set_label("Sharpe", color=text_c)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=text_c)

    ax = axes[1, 0]
    ax.set_facecolor("#1e293b")
    x = np.arange(len(asset_names))
    width = 0.2
    for offset, (name, w) in zip([-1.5, -0.5, 0.5, 1.5], strategies.items()):
        ax.bar(x + offset * width, w * 100, width=width, label=name)
    ax.set_xticks(x)
    ax.set_xticklabels(asset_names, color=text_c)
    ax.set_title("자산배분 모델별 비중 비교", color=text_c, fontweight="bold")
    ax.set_ylabel("비중 (%)", color=text_c)
    ax.legend(fontsize=8, labelcolor=text_c, facecolor="#0f172a")
    ax.tick_params(colors=text_c)
    ax.grid(True, alpha=0.2, color=grid_c, axis="y")
    ax.spines[:].set_color(grid_c)

    ax = axes[1, 1]
    ax.set_facecolor("#1e293b")
    ax.plot(spots, call, label="콜 매수", color="#3b82f6")
    ax.plot(spots, put, label="풋 매수", color="#ef4444")
    ax.plot(spots, straddle, label="스트래들", color="#a855f7")
    ax2 = ax.twinx()
    ax2.plot(np.arange(len(tenors)), yields, marker="o", color="#22c55e", label="채권 수익률곡선")
    ax2.set_ylabel("금리 (%)", color="#22c55e")
    ax2.tick_params(colors="#22c55e")
    ax2.set_xticks(np.arange(len(tenors)))
    ax2.set_xticklabels(tenors, color=text_c)
    ax.axhline(0, color="#94a3b8", linewidth=0.8)
    ax.set_title("파생상품 손익 + 채권 수익률곡선", color=text_c, fontweight="bold")
    ax.set_xlabel("기초자산 가격 / 만기", color=text_c)
    ax.set_ylabel("옵션 손익", color=text_c)
    ax.legend(fontsize=8, labelcolor=text_c, facecolor="#0f172a", loc="upper left")
    ax.tick_params(colors=text_c)
    ax.grid(True, alpha=0.2, color=grid_c)
    ax.spines[:].set_color(grid_c)

    fig.suptitle("금융상품 이해 + 자산배분방법론 대시보드", color=text_c, fontsize=15, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close(fig)

    return {
        "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
        "strategies": strategy_payload,
        "curriculum": [
            {"title": "주식/ETF 상품 이해", "practice": "ETF 성과 비교"},
            {"title": "채권 상품 이해", "practice": "수익률 곡선·듀레이션"},
            {"title": "파생상품 이해", "practice": "옵션 손익 시뮬레이션"},
            {"title": "포트폴리오 이론 및 성과 분석", "practice": "CAGR·MDD·Sharpe"},
            {"title": "자산배분 모델 및 사례 분석", "practice": "평균분산·블랙리터만·Risk-Parity 비교"},
        ],
    }
