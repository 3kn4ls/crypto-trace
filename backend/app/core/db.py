"""Database engine, session factory and declarative base."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# SQLite needs check_same_thread=False to be used across FastAPI's threadpool.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _column_exists(conn, table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(conn).get_columns(table)]


def _table_exists(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def migrate_db() -> None:
    """Idempotent migration for a local SQLite schema.

    Adds the taxpayers table and taxpayer_id/source columns introduced when
    moving from a single-user model to a multi-taxpayer model.

    Note: changing existing UNIQUE constraints in SQLite normally requires
    recreating the table. For a local dev/test database the simplest path is
    to remove the old DB file and let it be recreated. This function only
    adds the new columns and back-fills them safely.
    """
    from app import models  # noqa: F401  register models on Base.metadata

    with engine.begin() as conn:
        # 1. Create any new tables defined in Base.metadata (e.g. taxpayers).
        Base.metadata.create_all(conn)

        def add_fk(table: str, column: str, fk: str) -> None:
            if _table_exists(conn, table) and not _column_exists(conn, table, column):
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER REFERENCES {fk}")
                )

        def add_col(table: str, column: str, ddl: str) -> None:
            if _table_exists(conn, table) and not _column_exists(conn, table, column):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))

        # 2. Add taxpayer_id FK columns to existing tables.
        add_fk("accounts", "taxpayer_id", "taxpayers(id)")
        add_fk("import_batches", "taxpayer_id", "taxpayers(id)")
        add_fk("transactions", "taxpayer_id", "taxpayers(id)")
        add_fk("lots", "taxpayer_id", "taxpayers(id)")
        add_fk("disposals", "taxpayer_id", "taxpayers(id)")
        add_fk("income_events", "taxpayer_id", "taxpayers(id)")
        add_fk("fiscal_year_summaries", "taxpayer_id", "taxpayers(id)")
        add_fk("fiscal_years", "taxpayer_id", "taxpayers(id)")

        # 3. Add source column to transactions.
        add_col("transactions", "source", "VARCHAR(64)")

        # 4. Add columns for configurable FIFO behaviour and explicit cost basis.
        add_col("transactions", "is_internal_transfer", "BOOLEAN DEFAULT 1")
        add_col("transactions", "cost_basis_eur", "TEXT")

        # 5. Create reward preference table if it does not exist.
        if not _table_exists(conn, "taxpayer_reward_preferences"):
            conn.execute(text(
                "CREATE TABLE taxpayer_reward_preferences ("
                "  id INTEGER PRIMARY KEY,"
                "  taxpayer_id INTEGER NOT NULL REFERENCES taxpayers(id),"
                "  transaction_type VARCHAR(24) NOT NULL,"
                "  income_category VARCHAR(16) NOT NULL,"
                "  zero_cost_basis BOOLEAN DEFAULT 0,"
                "  UNIQUE (taxpayer_id, transaction_type)"
                ")"
            ))

        # 4. Ensure a default taxpayer exists.
        if _table_exists(conn, "taxpayers"):
            first = conn.execute(text("SELECT id FROM taxpayers ORDER BY id LIMIT 1")).scalar()
            if first is None:
                conn.execute(text("INSERT INTO taxpayers (name) VALUES ('Principal')"))
                first = conn.execute(text("SELECT id FROM taxpayers ORDER BY id LIMIT 1")).scalar()

            # 6. Back-fill taxpayer_id for rows that do not have one.
            for table in (
                "accounts", "import_batches", "transactions", "lots",
                "disposals", "income_events", "fiscal_year_summaries", "fiscal_years",
            ):
                if _table_exists(conn, table) and _column_exists(conn, table, "taxpayer_id"):
                    conn.execute(
                        text(f"UPDATE {table} SET taxpayer_id = :tid WHERE taxpayer_id IS NULL"),
                        {"tid": first},
                    )

            # 7. Back-fill Transaction.source from ImportBatch.connector.
            if (
                _table_exists(conn, "transactions")
                and _column_exists(conn, "transactions", "source")
                and _column_exists(conn, "transactions", "import_batch_id")
                and _table_exists(conn, "import_batches")
            ):
                conn.execute(text(
                    "UPDATE transactions SET source = ("
                    "  SELECT ib.connector FROM import_batches ib WHERE ib.id = transactions.import_batch_id"
                    ") WHERE source IS NULL AND import_batch_id IS NOT NULL"
                ))


def init_db() -> None:
    """Create the SQLite file/dir, run migrations and all tables if missing."""
    db_path = Path(settings.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Import models so they register on Base.metadata before create_all.
    from app import models  # noqa: F401

    migrate_db()
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
