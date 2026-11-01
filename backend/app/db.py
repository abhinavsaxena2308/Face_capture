from __future__ import annotations

import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    """Ensure newly introduced columns exist in the database without requiring manual migrations."""
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            if "searches" in tables:
                search_cols = {col["name"] for col in inspector.get_columns("searches")}
                if "target_emotion" not in search_cols:
                    conn.execute(
                        text("ALTER TABLE searches ADD COLUMN IF NOT EXISTS target_emotion VARCHAR(32) DEFAULT 'all';")
                    )
            if "matches" in tables:
                match_cols = {col["name"] for col in inspector.get_columns("matches")}
                if "emotion" not in match_cols:
                    conn.execute(
                        text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS emotion VARCHAR(32) DEFAULT 'neutral';")
                    )
    except Exception as e:
        logger.warning("Could not auto-update schema: %s", e)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
