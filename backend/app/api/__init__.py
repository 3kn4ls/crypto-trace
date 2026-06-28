"""API routers."""
from fastapi import APIRouter

from app.api import accounts, fiscal, imports, meta, reports, reviews, taxpayers, transactions

api_router = APIRouter()
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(taxpayers.router, prefix="/taxpayers", tags=["taxpayers"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(fiscal.router, prefix="/fiscal-years", tags=["fiscal"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
