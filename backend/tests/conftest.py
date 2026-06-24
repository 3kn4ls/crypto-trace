"""Test fixtures: an isolated in-memory database seeded with reference data."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.seed import seed_all
import app.models  # noqa: F401  (register tables on Base.metadata)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = Session()
    seed_all(session)
    try:
        yield session
    finally:
        session.close()
