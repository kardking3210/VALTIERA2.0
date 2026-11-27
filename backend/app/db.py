"""Persistent SQLAlchemy storage. SQLite is the local default; production can use PostgreSQL."""
import os
from sqlalchemy import create_engine
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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
