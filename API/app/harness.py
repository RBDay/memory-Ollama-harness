import logging
from typing import Optional, List, Dict, Any, Tuple
from fastapi import HTTPException, status
from app.core.config import settings
from app.repositories.session_repository import session_repository, SessionRepository
from app.repositories.memory_repository import memory_repository, MemoryRepository
from app.services.ollama_service import ollama_service, OllamaService
from app.schemas.memory import (
    MessageItem,
    ChatResponse,
)

logger = logging.getLogger("uvicorn")


class OllamaHarness:
    """
    Andamiaje (Harness) para Ollama con gestión de memoria y contexto persistente en MongoDB.
    
    Flujo:
    1. Intercepta la petición con session_id y mensaje.
    2. Reconstruye el contexto recuperando el system_prompt de la sesión y el historial de la colección 'memory'.
    3. Realiza la inferencia contra Ollama pasando toda la memoria acumulada.
    4. Persiste el mensaje del usuario y la respuesta del asistente en la colección 'memory'.
    """

    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        memory_repo: Optional[MemoryRepository] = None,
        ollama_svc: Optional[OllamaService] = None,
    ):
        self.session_repo = session_repo or session_repository
        self.memory_repo = memory_repo or memory_repository
        self.ollama_svc = ollama_svc or ollama_service

    async def build_context(
        self, session_id: str, new_user_message: str
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        """
        Reconstruye el contexto completo de la conversación:
        - System prompt / contexto inicial de la sesión (si existe)
        - Historial de mensajes previos almacenados en 'memory'
        - El nuevo mensaje del usuario
        """
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La sesión con ID '{session_id}' no existe. Debe crearla antes de iniciar una conversación.",
            )

        messages_payload: List[Dict[str, str]] = []

        # 1. Contexto inicial / System Prompt
        system_prompt = session.get("system_prompt")
        if system_prompt and system_prompt.strip():
            messages_payload.append({
                "role": "system",
                "content": system_prompt.strip(),
            })

        # 2. Historial de mensajes previos ordenados cronológicamente
        history = await self.memory_repo.get_messages_by_session(session_id)
        for msg in history:
            messages_payload.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        # 3. Nuevo mensaje del usuario
        messages_payload.append({
            "role": "user",
            "content": new_user_message.strip(),
        })

        return messages_payload, session

    async def execute_chat(
        self,
        session_id: str,
        content: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> ChatResponse:
        """
        Ejecuta el ciclo completo del Harness:
        reconstruir contexto -> invocar Ollama -> persistir interacción -> retornar respuesta.
        """
        if not content or not content.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El contenido del mensaje no puede estar vacío.",
            )

        # 1. Reconstruir contexto
        messages_payload, session = await self.build_context(session_id, content)

        # 2. Determinar modelo (override puntual -> modelo de sesión -> default global)
        target_model = model or session.get("model") or settings.MODEL_NAME

        # 3. Llamar a Ollama con la memoria reconstruida
        logger.info(
            f"Harness: Enviando {len(messages_payload)} mensajes para sesión '{session_id}' a modelo '{target_model}'"
        )
        ollama_result = await self.ollama_svc.chat(
            messages=messages_payload,
            model=target_model,
            temperature=temperature,
        )

        assistant_content = ollama_result.get("content", "")
        extra_metadata = ollama_result.get("metadata", {})

        # 4. Persistir mensaje del usuario en MongoDB (colección 'memory')
        user_doc = await self.memory_repo.add_message(
            session_id=session_id,
            role="user",
            content=content.strip(),
        )

        # 5. Persistir respuesta del asistente en MongoDB (colección 'memory')
        assistant_doc = await self.memory_repo.add_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            metadata=extra_metadata,
        )

        # 6. Actualizar fecha de actualización de la sesión
        await self.session_repo.touch(session_id)

        # 7. Contar mensajes totales
        total_messages = await self.memory_repo.count_by_session(session_id)

        return ChatResponse(
            session_id=session_id,
            user_message=MessageItem(
                message_id=user_doc["message_id"],
                session_id=user_doc["session_id"],
                role=user_doc["role"],
                content=user_doc["content"],
                created_at=user_doc["created_at"],
                metadata=user_doc.get("metadata", {}),
            ),
            assistant_message=MessageItem(
                message_id=assistant_doc["message_id"],
                session_id=assistant_doc["session_id"],
                role=assistant_doc["role"],
                content=assistant_doc["content"],
                created_at=assistant_doc["created_at"],
                metadata=assistant_doc.get("metadata", {}),
            ),
            model=target_model,
            total_messages_in_session=total_messages,
        )


harness = OllamaHarness()
