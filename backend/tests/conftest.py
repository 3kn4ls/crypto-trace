"""Test fixtures: an isolated in-memory database seeded with reference data."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.seed import seed_all
import app.models  # noqa: F401  (register tables on Base.metadata)
from app.main import app


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


@pytest.fixture()
def taxpayer(db):
    from app.models import Taxpayer
    taxpayer = Taxpayer(name="Test Taxpayer", tax_id="12345678A")
    db.add(taxpayer)
    db.commit()
    db.refresh(taxpayer)
    return taxpayer


@pytest.fixture()
def account(db, taxpayer):
    from app.models import Account
    account = Account(
        taxpayer_id=taxpayer.id, name="Test Account", platform="CRYPTO_COM_BANK",
        type="EXCHANGE", is_abroad=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    seed_session = TestingSession()
    seed_all(seed_session)
    seed_session.close()

    def override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
