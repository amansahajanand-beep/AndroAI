from fastapi import APIRouter, Response, status

from ...db import check_database
from ...redis_client import check_redis

router = APIRouter()


@router.get("/health/ready", tags=["health"])
def readiness(response: Response) -> dict:
    """Dependency connectivity check (PostgreSQL, Redis). 503 if any is down."""
    checks = {"database": check_database(), "redis": check_redis()}
    ok = all(checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ok else "degraded", "checks": checks}


# Feature routers: router.include_router(projects_router, prefix="/projects")
