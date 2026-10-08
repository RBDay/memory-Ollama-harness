from fastapi import APIRouter
from app.api.v1.endpoints.sessions import router as sessions_router
from app.api.v1.endpoints.memory import router as memory_router

api_v1_router = APIRouter()

api_v1_router.include_router(
    sessions_router,
    prefix="/sessions",
    tags=["Sessions"],
)

api_v1_router.include_router(
    sessions_router,
    prefix="/session",
    tags=["Session"],
)

api_v1_router.include_router(
    memory_router,
    prefix="/memory",
    tags=["Memory"],
)
