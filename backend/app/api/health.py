from fastapi import APIRouter

from backend.app.core.config import get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    return {
        "ok": True,
        "data": {
            "status": "ok",
            "service": get_settings().app_name,
            "version": "2.0.0-dev",
        },
        "error": None,
    }

