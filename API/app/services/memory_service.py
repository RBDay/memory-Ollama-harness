from typing import Optional, List
from fastapi import HTTPException, status
from app.repositories.memory_repository import memory_repository, MemoryRepository
from app.repositories.session_repository import session_repository, SessionRepository
from app.schemas.memory import (
    MessageItem,
    MemoryHistoryResponse,
    MemoryClearResponse,
)


class MemoryService:
    def __init__(
        self,
        memory_repo: Optional[MemoryRepository] = None,
        session_repo: Optional[SessionRepository] = None,
    ):
        self.memory_repo = memory_repo or memory_repository
        self.session_repo = session_repo or session_repository

    async def get_history(self, session_id: str, limit: Optional[int] = None) -> MemoryHistoryResponse:
        """Recupera el historial de conversación en orden cronológico."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró la sesión '{session_id}'.",
            )

        messages_raw = await self.memory_repo.get_messages_by_session(session_id, limit=limit)
        items = [
            MessageItem(
                message_id=m["message_id"],
                session_id=m["session_id"],
                role=m["role"],
                content=m["content"],
                created_at=m["created_at"],
                metadata=m.get("metadata", {}),
            )
            for m in messages_raw
        ]

        total = await self.memory_repo.count_by_session(session_id)
        return MemoryHistoryResponse(
            session_id=session_id,
            total=total,
            messages=items,
        )

    async def clear_memory(self, session_id: str) -> MemoryClearResponse:
        """Borra todos los mensajes de una sesión, reiniciando su memoria."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró la sesión '{session_id}'.",
            )

        deleted = await self.memory_repo.delete_by_session(session_id)
        await self.session_repo.touch(session_id)

        return MemoryClearResponse(
            session_id=session_id,
            deleted_count=deleted,
            message="Memoria de la sesión vaciada exitosamente.",
        )


memory_service = MemoryService()
