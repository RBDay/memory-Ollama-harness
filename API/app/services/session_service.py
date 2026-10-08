import uuid
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, status
from app.core.config import settings
from app.repositories.session_repository import session_repository, SessionRepository
from app.repositories.memory_repository import memory_repository, MemoryRepository
from app.services.vector_service import vector_service, VectorService
from app.schemas.session import SessionCreate, SessionUpdate, SessionResponse, SessionListResponse


class SessionService:
    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        memory_repo: Optional[MemoryRepository] = None,
        vector_svc: Optional[VectorService] = None,
    ):
        self.session_repo = session_repo or session_repository
        self.memory_repo = memory_repo or memory_repository
        self.vector_svc = vector_svc or vector_service

    async def create_session(self, data: SessionCreate) -> SessionResponse:
        """Crea una nueva sesión en MongoDB."""
        session_id = data.session_id or str(uuid.uuid4())
        
        # Validar si ya existe
        existing = await self.session_repo.get_by_id(session_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe una sesión con el ID '{session_id}'.",
            )

        doc = {
            "session_id": session_id,
            "title": data.title or "Nueva Sesión",
            "system_prompt": data.system_prompt,
            "model": data.model or settings.MODEL_NAME,
            "metadata": data.metadata or {},
        }
        created = await self.session_repo.create(doc)
        return SessionResponse(
            session_id=created["session_id"],
            title=created["title"],
            system_prompt=created.get("system_prompt"),
            model=created.get("model"),
            created_at=created["created_at"],
            updated_at=created["updated_at"],
            message_count=0,
            metadata=created.get("metadata", {}),
        )

    async def create_session_with_files(
        self,
        data: SessionCreate,
        files: List[tuple[str, bytes]],
    ) -> tuple[SessionResponse, Dict[str, Any]]:
        """Crea una sesión e indexa sus archivos; revierte la sesión si falla la ingesta."""
        session = await self.create_session(data)
        try:
            vector_context = await self.vector_svc.index_files_for_session(
                session.session_id, files, mode="overwrite"
            )
        except Exception:
            self.vector_svc.delete_session_vectors(session.session_id)
            await self.memory_repo.delete_by_session(session.session_id)
            await self.session_repo.delete(session.session_id)
            raise
        return session, vector_context

    async def refresh_session_vectors(
        self,
        session_id: str,
        files: List[tuple[str, bytes]],
    ) -> Dict[str, Any]:
        """Sustituye el contexto vectorial de una sesión existente."""
        await self.get_session(session_id)
        result = await self.vector_svc.refresh_session_vectors(session_id, files)
        await self.session_repo.touch(session_id)
        return result

    async def get_session(self, session_id: str) -> SessionResponse:
        """Obtiene los detalles de una sesión junto al conteo de mensajes."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontró la sesión con ID '{session_id}'.",
            )

        count = await self.memory_repo.count_by_session(session_id)
        return SessionResponse(
            session_id=session["session_id"],
            title=session.get("title", "Sesión"),
            system_prompt=session.get("system_prompt"),
            model=session.get("model", settings.MODEL_NAME),
            created_at=session["created_at"],
            updated_at=session["updated_at"],
            message_count=count,
            metadata=session.get("metadata", {}),
        )

    async def list_sessions(self, skip: int = 0, limit: int = 50) -> SessionListResponse:
        """Lista todas las sesiones con conteo de mensajes."""
        total = await self.session_repo.count()
        raw_sessions = await self.session_repo.list_all(skip=skip, limit=limit)

        session_ids = [s["session_id"] for s in raw_sessions]
        counts = await self.memory_repo.count_multiple_sessions(session_ids)

        items = [
            SessionResponse(
                session_id=s["session_id"],
                title=s.get("title", "Sesión"),
                system_prompt=s.get("system_prompt"),
                model=s.get("model", settings.MODEL_NAME),
                created_at=s["created_at"],
                updated_at=s["updated_at"],
                message_count=counts.get(s["session_id"], 0),
                metadata=s.get("metadata", {}),
            )
            for s in raw_sessions
        ]

        return SessionListResponse(total=total, sessions=items)

    async def update_session(self, session_id: str, data: SessionUpdate) -> SessionResponse:
        """Actualiza el contexto o metadatos de una sesión."""
        # Validar existencia
        await self.get_session(session_id)

        update_dict = data.model_dump(exclude_unset=True)
        updated = await self.session_repo.update(session_id, update_dict)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se pudo actualizar la sesión '{session_id}'.",
            )

        count = await self.memory_repo.count_by_session(session_id)
        return SessionResponse(
            session_id=updated["session_id"],
            title=updated.get("title", "Sesión"),
            system_prompt=updated.get("system_prompt"),
            model=updated.get("model", settings.MODEL_NAME),
            created_at=updated["created_at"],
            updated_at=updated["updated_at"],
            message_count=count,
            metadata=updated.get("metadata", {}),
        )

    async def delete_session(self, session_id: str) -> Dict[str, Any]:
        """Elimina la sesión y sus memorias conversacional y vectorial asociadas."""
        await self.get_session(session_id)
        vector_cleanup = self.vector_svc.delete_session_vectors(session_id)
        deleted_messages = await self.memory_repo.delete_by_session(session_id)
        deleted_session = await self.session_repo.delete(session_id)

        return {
            "session_id": session_id,
            "deleted": deleted_session,
            "deleted_messages_count": deleted_messages,
            "deleted_vector_objects_count": vector_cleanup["deleted_objects_count"],
            "message": "Sesión y memorias conversacional y vectorial eliminadas con éxito.",
        }


session_service = SessionService()
