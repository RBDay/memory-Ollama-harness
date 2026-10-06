import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo import ASCENDING
from app.core.config import settings

logger = logging.getLogger("uvicorn")


class Database:
    client: Optional[AsyncIOMotorClient] = None


db = Database()


async def init_indexes() -> None:
    """Crea los índices necesarios en las colecciones sessions y memory."""
    try:
        database = get_database()
        sessions_col = database[settings.SESSIONS_COLLECTION]
        memory_col = database[settings.MEMORY_COLLECTION]

        # Índice único por session_id en sessions
        await sessions_col.create_index([("session_id", ASCENDING)], unique=True)

        # Índices en memory para optimizar la búsqueda cronológica por sesión
        await memory_col.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
        await memory_col.create_index([("session_id", ASCENDING)])

        logger.info("Índices de MongoDB creados/verificados correctamente.")
    except Exception as e:
        logger.warning(f"No se pudieron inicializar los índices de MongoDB: {e}")


async def connect_to_mongo() -> None:
    """Abre el pool de conexiones con MongoDB al arrancar la API."""
    logger.info(f"Conectando a MongoDB en {settings.MONGO_URI}...")
    db.client = AsyncIOMotorClient(
        settings.MONGO_URI,
        maxPoolSize=10,
        minPoolSize=1,
    )
    try:
        await db.client.admin.command("ping")
        logger.info("Conexión con MongoDB establecida correctamente.")
        await init_indexes()
    except Exception as e:
        logger.error(f"Error conectando a MongoDB: {e}")
        raise e


async def close_mongo_connection() -> None:
    """Cierra el pool de conexiones al apagar la API."""
    if db.client:
        logger.info("Cerrando conexión con MongoDB...")
        db.client.close()
        logger.info("Conexión con MongoDB cerrada.")


def get_database() -> AsyncIOMotorDatabase:
    """Obtiene la instancia de la base de datos en MongoDB."""
    if db.client is None:
        raise RuntimeError("La base de datos no está inicializada.")
    return db.client[settings.DATABASE_NAME]


def get_sessions_collection() -> AsyncIOMotorCollection:
    """Obtiene la colección 'sessions'."""
    return get_database()[settings.SESSIONS_COLLECTION]


def get_memory_collection() -> AsyncIOMotorCollection:
    """Obtiene la colección 'memory'."""
    return get_database()[settings.MEMORY_COLLECTION]