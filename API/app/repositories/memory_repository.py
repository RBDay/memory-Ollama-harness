import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorCollection
from app.core.database import get_memory_collection


class MemoryRepository:
    def __init__(self, collection: Optional[AsyncIOMotorCollection] = None):
        self._collection = collection

    @property
    def collection(self) -> AsyncIOMotorCollection:
        if self._collection is not None:
            return self._collection
        return get_memory_collection()

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Guarda un mensaje en la colección 'memory' asociado a una sesión."""
        message_doc = {
            "message_id": str(uuid.uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": datetime.now(timezone.utc),
            "metadata": metadata or {},
        }
        await self.collection.insert_one(message_doc)
        message_doc.pop("_id", None)
        return message_doc

    async def get_messages_by_session(
        self, session_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Obtiene los mensajes de una sesión ordenados cronológicamente."""
        cursor = self.collection.find({"session_id": session_id}, {"_id": 0}).sort("created_at", 1)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit)

    async def count_by_session(self, session_id: str) -> int:
        """Cuenta el número de mensajes guardados para una sesión."""
        return await self.collection.count_documents({"session_id": session_id})

    async def count_multiple_sessions(self, session_ids: List[str]) -> Dict[str, int]:
        """Obtiene el conteo de mensajes para múltiples sesiones mediante agregación."""
        if not session_ids:
            return {}
        pipeline = [
            {"$match": {"session_id": {"$in": session_ids}}},
            {"$group": {"_id": "$session_id", "count": {"$sum": 1}}},
        ]
        results = await self.collection.aggregate(pipeline).to_list(length=len(session_ids))
        counts = {r["_id"]: r["count"] for r in results}
        return {s_id: counts.get(s_id, 0) for s_id in session_ids}

    async def delete_by_session(self, session_id: str) -> int:
        """Elimina todos los mensajes asociados a una sesión."""
        result = await self.collection.delete_many({"session_id": session_id})
        return result.deleted_count

    async def delete_message(self, message_id: str) -> bool:
        """Elimina un mensaje específico por su ID."""
        result = await self.collection.delete_one({"message_id": message_id})
        return result.deleted_count > 0


memory_repository = MemoryRepository()
