import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection, db
from app.api.v1.router import api_v1_router
from app.services.ollama_service import ollama_service

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestor de ciclo de vida de la aplicación (conexión a DB al iniciar y cierre al apagar)."""
    logger.info("Iniciando aplicación Memory Ollama API...")
    await connect_to_mongo()
    yield
    logger.info("Apagando aplicación Memory Ollama API...")
    await close_mongo_connection()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API REST con persistencia en MongoDB para dotar de memoria y contexto conversacional a modelos locales en Ollama.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configuración de CORS para permitir consumo desde frontends o herramientas externas
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusión del enrutador de la API v1
app.include_router(api_v1_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["General"])
async def root():
    """Ruta raíz de bienvenida y estado de la API."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "v1_api": settings.API_V1_STR,
    }


@app.get("/health", tags=["General"])
async def health_check():
    """Verificación de salud de la API, conexión con MongoDB y conectividad con Ollama."""
    mongo_status = "healthy"
    try:
        if db.client:
            await db.client.admin.command("ping")
        else:
            mongo_status = "disconnected"
    except Exception as e:
        mongo_status = f"error: {str(e)}"

    ollama_status = await ollama_service.check_health()

    return {
        "status": "ok" if mongo_status == "healthy" else "degraded",
        "mongo": mongo_status,
        "ollama": ollama_status,
        "database_name": settings.DATABASE_NAME,
        "collections": {
            "sessions": settings.SESSIONS_COLLECTION,
            "memory": settings.MEMORY_COLLECTION,
        },
    }