from fastapi import APIRouter, Response
from sqlalchemy import text

from docintel.routers.dependencies import ContainerDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response, c: ContainerDep) -> dict[str, str]:
    """Readiness: the database answers."""
    try:
        async with c.sessions() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # any failure means not ready; never leak the reason
        response.status_code = 503
        return {"status": "unavailable", "database": "down"}
    return {"status": "ok", "database": "up"}
