from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorCollection
from app.core.database import get_sessions_collection


class SessionRepository:
    def __init__(self, collection: Optional[AsyncIOMotorCollection] = None):
        self._collection = collection

    @property
    def collection(self) -> AsyncIOMotorCollection:
        if self._collection is not None:
            return self._collection
        return get_sessions_collection()

    async def create(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """Inserta una nueva sesión en la colección 'sessions'."""
        data = dict(session_data)
        now = datetime.now(timezone.utc)
        if "created_at" not in data:
            data["created_at"] = now
        if "updated_at" not in data:
            data["updated_at"] = now
        
        await self.collection.insert_one(data)
        data.pop("_id", None)
        return data

    async def get_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Busca una sesión por su session_id."""
        doc = await self.collection.find_one({"session_id": session_id}, {"_id": 0})
        return doc

    async def list_all(self, skip: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
        """Lista sesiones ordenadas por fecha de actualización descendente."""
        cursor = self.collection.find({}, {"_id": 0}).sort("updated_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count(self) -> int:
        """Retorna el total de sesiones registradas."""
        return await self.collection.count_documents({})

    async def update(self, session_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Actualiza campos de una sesión y refresca updated_at."""
        clean_update = {k: v for k, v in update_data.items() if v is not None and k != "session_id"}
        clean_update["updated_at"] = datetime.now(timezone.utc)
        
        result = await self.collection.find_one_and_update(
            {"session_id": session_id},
            {"$set": clean_update},
            projection={"_id": 0},
            return_document=True,
        )
        return result

    async def touch(self, session_id: str) -> None:
        """Actualiza únicamente el timestamp updated_at de la sesión."""
        await self.collection.update_one(
            {"session_id": session_id},
            {"$set": {"updated_at": datetime.now(timezone.utc)}},
        )

    async def delete(self, session_id: str) -> bool:
        """Elimina una sesión por su session_id."""
        result = await self.collection.delete_one({"session_id": session_id})
        return result.deleted_count > 0


session_repository = SessionRepository()
