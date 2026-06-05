"""SQLAlchemy ORM 模型：股票池 / 因子注册表 / 风控设置等。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 股票池
# ---------------------------------------------------------------------------
class Pool(Base):
    __tablename__ = "pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    pool_type: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    # pool_type: short_term / mid_term / value / dividend / theme / custom
    description: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items: Mapped[list["PoolItem"]] = relationship(
        "PoolItem", back_populates="pool", cascade="all, delete-orphan", lazy="selectin"
    )


class PoolItem(Base):
    __tablename__ = "pool_items"
    __table_args__ = (UniqueConstraint("pool_id", "ticker", name="uq_pool_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("pools.id", ondelete="CASCADE"), index=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(64))

    # 加入时快照
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    added_score: Mapped[float | None] = mapped_column(Float)
    added_reason: Mapped[str | None] = mapped_column(Text)
    added_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 当前复评
    current_score: Mapped[float | None] = mapped_column(Float)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_review_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 用户标注
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="watching")
    # status: watching / holding / paused / closed
    note: Mapped[str | None] = mapped_column(Text)

    pool: Mapped[Pool] = relationship("Pool", back_populates="items")


# ---------------------------------------------------------------------------
# Factor Registry
# ---------------------------------------------------------------------------
class FactorDef(Base):
    __tablename__ = "factor_defs"

    factor_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # bucket: trend / momentum / volume / valuation / quality / risk / capital / event
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    tushare_api: Mapped[str | None] = mapped_column(String(64))
    required_fields: Mapped[list[str] | None] = mapped_column(JSON)
    refresh_frequency: Mapped[str] = mapped_column(String(16), default="daily")
    # daily / weekly / quarterly / event
    permission_required: Mapped[str] = mapped_column(String(16), default="basic")
    # basic / premium
    higher_is_better: Mapped[bool] = mapped_column(Boolean, default=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    missing_reason: Mapped[str | None] = mapped_column(Text)
    fallback_behavior: Mapped[str] = mapped_column(String(32), default="neutral_50")
    # neutral_50 / skip / exclude
    participates_in_score: Mapped[bool] = mapped_column(Boolean, default=True)
    bucket_weight: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# 风控设置（单行）
# ---------------------------------------------------------------------------
class RiskSettings(Base):
    __tablename__ = "risk_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_capital: Mapped[float] = mapped_column(Float, default=100000.0)
    max_loss_per_trade_pct: Mapped[float] = mapped_column(Float, default=1.0)
    max_single_position_pct: Mapped[float] = mapped_column(Float, default=10.0)
    max_industry_exposure_pct: Mapped[float] = mapped_column(Float, default=25.0)
    cap_strong_market_pct: Mapped[float] = mapped_column(Float, default=80.0)
    cap_neutral_market_pct: Mapped[float] = mapped_column(Float, default=50.0)
    cap_weak_market_pct: Mapped[float] = mapped_column(Float, default=20.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# 交易计划（B2）
# ---------------------------------------------------------------------------
class TradingPlan(Base):
    __tablename__ = "trading_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(64))
    pool_id: Mapped[int | None] = mapped_column(ForeignKey("pools.id", ondelete="SET NULL"), index=True)

    action: Mapped[str] = mapped_column(String(16), default="buy")
    # buy / add / hold / reduce / exit
    trading_state: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    # high / medium / low

    # 价位
    entry_zone_low: Mapped[float | None] = mapped_column(Float)
    entry_zone_high: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    stop_loss_method: Mapped[str | None] = mapped_column(String(32))
    # ma60 / swing_low / atr / pct
    take_profits: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    # [{level:1, price:x, ratio:0.5, label:"..."}]

    # 仓位 / 风险
    risk_reward: Mapped[float | None] = mapped_column(Float)
    position_pct: Mapped[float | None] = mapped_column(Float)
    position_shares: Mapped[int | None] = mapped_column(Integer)
    risk_per_trade_pct: Mapped[float | None] = mapped_column(Float)
    account_capital: Mapped[float | None] = mapped_column(Float)

    # 说明
    reasons: Mapped[list[str] | None] = mapped_column(JSON)
    risks: Mapped[list[str] | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    features_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # draft / active / executed / cancelled / expired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# 计划执行追踪（D2）：每条 PlanFill 记一笔实际成交（买/卖），
# 配合 trading_plans 用于计算已实现盈亏、平均成本和剩余持仓。
# ---------------------------------------------------------------------------
class PlanFill(Base):
    __tablename__ = "plan_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("trading_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    # buy / sell
    trade_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# 财务快照（C4）：每个交易日的估值/市值切片 + 每个报告期的财务指标切片。
# 关键：FinaSnapshot.ann_date 用于防未来函数——只有公告日 ≤ 评估日时才可使用。
# ---------------------------------------------------------------------------
class DailyBasicSnapshot(Base):
    """每日基本面切片：来自 tushare daily_basic。"""

    __tablename__ = "daily_basic_snapshots"
    __table_args__ = (UniqueConstraint("ts_code", "trade_date", name="uq_daily_basic_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # YYYY-MM-DD

    pe: Mapped[float | None] = mapped_column(Float)
    pe_ttm: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    ps: Mapped[float | None] = mapped_column(Float)
    ps_ttm: Mapped[float | None] = mapped_column(Float)
    dv_ratio: Mapped[float | None] = mapped_column(Float)
    dv_ttm: Mapped[float | None] = mapped_column(Float)
    total_mv: Mapped[float | None] = mapped_column(Float)
    circ_mv: Mapped[float | None] = mapped_column(Float)
    turnover_rate: Mapped[float | None] = mapped_column(Float)
    turnover_rate_f: Mapped[float | None] = mapped_column(Float)
    volume_ratio: Mapped[float | None] = mapped_column(Float)

    data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinaSnapshot(Base):
    """财务指标快照：来自 tushare fina_indicator。"""

    __tablename__ = "fina_snapshots"
    __table_args__ = (UniqueConstraint("ts_code", "end_date", "ann_date", name="uq_fina_code_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # 报告期 YYYY-MM-DD
    ann_date: Mapped[str | None] = mapped_column(String(10), index=True)  # 公告日 — 防未来函数关键

    eps: Mapped[float | None] = mapped_column(Float)
    bps: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)
    roe_yearly: Mapped[float | None] = mapped_column(Float)
    roa: Mapped[float | None] = mapped_column(Float)
    netprofit_margin: Mapped[float | None] = mapped_column(Float)
    grossprofit_margin: Mapped[float | None] = mapped_column(Float)
    debt_to_assets: Mapped[float | None] = mapped_column(Float)
    current_ratio: Mapped[float | None] = mapped_column(Float)
    netprofit_yoy: Mapped[float | None] = mapped_column(Float)
    or_yoy: Mapped[float | None] = mapped_column(Float)

    data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SnapshotSyncLog(Base):
    """记录每次快照同步的元信息，方便前端展示进度。"""

    __tablename__ = "snapshot_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # daily_basic / fina
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running / succeeded / failed / partial
    requested: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# 滚动回测持久化（D4）：BacktestRun 存一次完整运行的元信息和指标，
# BacktestTrade 存按调仓期展开的持仓/转换明细。
# ---------------------------------------------------------------------------
class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str | None] = mapped_column(String(128))
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rebalance: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, default=10)
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    pool_id: Mapped[int | None] = mapped_column(ForeignKey("pools.id", ondelete="SET NULL"), index=True)

    total_return: Mapped[float | None] = mapped_column(Float)
    annualized_return: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    bench_total_return: Mapped[float | None] = mapped_column(Float)
    bench_annualized_return: Mapped[float | None] = mapped_column(Float)

    params: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    equity_curve: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    period_returns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    warnings: Mapped[list[str] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    trades: Mapped[list["BacktestTrade"]] = relationship(
        "BacktestTrade", back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period_index: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[str] = mapped_column(String(10), nullable=False)
    period_end: Mapped[str | None] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    # enter / hold / exit
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    weight: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)

    run: Mapped[BacktestRun] = relationship("BacktestRun", back_populates="trades")
