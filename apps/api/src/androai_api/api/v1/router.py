import os

from fastapi import APIRouter, Response, status

from ...db import check_database
from ...redis_client import check_redis
from . import admin, admin_workers, artifacts, auth, builds, projects, testruns, users, worker

router = APIRouter()


@router.get("/health/ready", tags=["health"])
def readiness(response: Response) -> dict:
    """Dependency connectivity check (PostgreSQL, Redis). 503 if any is down."""
    checks = {"database": check_database(), "redis": check_redis()}
    ok = all(checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ok else "degraded", "checks": checks}


router.include_router(auth.router, prefix="/auth")
router.include_router(users.router, prefix="/users")
router.include_router(projects.router, prefix="/projects")
router.include_router(artifacts.router, prefix="/artifacts")
router.include_router(admin.router, prefix="/admin")
router.include_router(admin_workers.router, prefix="/admin")
router.include_router(builds.router, prefix="/builds")
router.include_router(testruns.router, prefix="/tests")
router.include_router(worker.router, prefix="/worker")
if os.environ.get("AGENT_DEV_BRIDGE") == "1":
    # DEV ONLY: in-process stand-in for the agent API (see agent_dev.py). Never set in production.
    from . import agent_dev

    router.include_router(agent_dev.router, prefix="/agent")
# Not yet implemented (see docs/BACKEND_PROGRESS.md): /agent (except the dev bridge), /usage, /billing
