"""HTTP API routers."""

from fastapi import APIRouter

from app.api import analyses, dashboard, executions, health, repositories

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(analyses.router)
api_router.include_router(executions.router)
api_router.include_router(repositories.router)
api_router.include_router(dashboard.router)

__all__ = ["api_router"]
