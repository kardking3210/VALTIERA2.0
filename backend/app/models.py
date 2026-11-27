from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON
from .db import Base

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="researcher")
    password_hash: Mapped[str] = mapped_column(String(256))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class RevokedSession(Base):
    __tablename__ = "revoked_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class EngineRun(Base):
    __tablename__ = "engine_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    engine: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class RiskSettings(Base):
    __tablename__ = "risk_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    max_position_pct: Mapped[float] = mapped_column(Float, default=10)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=15)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, default=2)
    max_gross_exposure_pct: Mapped[float] = mapped_column(Float, default=100)
    portfolio_nav: Mapped[float] = mapped_column(Float, default=100000)
    risk_profile: Mapped[str] = mapped_column(String(20), default="moderate")
    max_leverage_pct: Mapped[float] = mapped_column(Float, default=100)
    asset_class_limits: Mapped[dict] = mapped_column(JSON, default=dict)
    volatility_tolerance: Mapped[str] = mapped_column(String(20), default="moderate")
    liquidity_floor_usd: Mapped[float] = mapped_column(Float, default=0)
    investment_horizon_months: Mapped[int] = mapped_column(Integer, default=12)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    asset_class: Mapped[str] = mapped_column(String(32), default="equity")
    quantity: Mapped[float] = mapped_column(Float)
    average_cost: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Backtest(Base):
    __tablename__ = "backtests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    engine: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ResearchJob(Base):
    __tablename__ = "research_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    engine: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    parameters: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"
    service: Mapped[str] = mapped_column(String(64), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), default="workspace")
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    cash: Mapped[float] = mapped_column(Float, default=100000)
    positions: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class PaperOrder(Base):
    __tablename__ = "paper_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    asset_class: Mapped[str] = mapped_column(String(16), default="crypto")
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee_bps: Mapped[float] = mapped_column(Float, default=10)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
