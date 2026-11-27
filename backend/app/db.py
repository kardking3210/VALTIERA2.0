"""Persistent SQLAlchemy storage. SQLite is the local default; production can use PostgreSQL."""
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./valtiera.db").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgres://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgresql://")
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Supabase transaction pooling requires TLS and does not support prepared statements.
    connect_args = {"sslmode": "require", "prepare_threshold": 0}
serverless = os.getenv("VERCEL") == "1"
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if serverless and not DATABASE_URL.startswith("sqlite"):
    engine_options.update(pool_size=1, max_overflow=0, pool_recycle=300)
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def initialize_storage(base=Base):
    """Create/update the schema safely when several serverless instances start together."""
    if os.getenv("VERCEL") == "1" and DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("DATABASE_URL must be set to persistent PostgreSQL for Vercel deployments")
    if not DATABASE_URL.startswith("sqlite") and not os.getenv("VALTIERA_SECRET"):
        raise RuntimeError("VALTIERA_SECRET must be configured for non-development deployments")

    # PostgreSQL advisory transaction locks serialize first-start DDL across Vercel
    # instances while remaining compatible with Supabase's transaction pooler.
    with engine.begin() as connection:
        if not DATABASE_URL.startswith("sqlite"):
            connection.execute(text("SELECT pg_advisory_xact_lock(731904218)"))
        base.metadata.create_all(bind=connection)

        inspector = inspect(connection)
        if "risk_settings" in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns("risk_settings")}
            additions = {
                "portfolio_nav": "FLOAT NOT NULL DEFAULT 100000",
                "risk_profile": "VARCHAR(20) NOT NULL DEFAULT 'moderate'",
                "max_leverage_pct": "FLOAT NOT NULL DEFAULT 100",
                "asset_class_limits": "JSON NOT NULL DEFAULT '{}'",
                "volatility_tolerance": "VARCHAR(20) NOT NULL DEFAULT 'moderate'",
                "liquidity_floor_usd": "FLOAT NOT NULL DEFAULT 0",
                "investment_horizon_months": "INTEGER NOT NULL DEFAULT 12",
            }
            for column, ddl in additions.items():
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE risk_settings ADD COLUMN {column} {ddl}"))

        if "paper_orders" in inspector.get_table_names():
            order_columns = {column["name"] for column in inspector.get_columns("paper_orders")}
            if "filled_quantity" not in order_columns:
                connection.execute(text("ALTER TABLE paper_orders ADD COLUMN filled_quantity FLOAT NOT NULL DEFAULT 0"))
            if "average_fill_price" not in order_columns:
                connection.execute(text("ALTER TABLE paper_orders ADD COLUMN average_fill_price FLOAT"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
