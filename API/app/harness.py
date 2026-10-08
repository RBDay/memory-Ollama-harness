import logging
from typing import Optional, List, Dict, Any, Tuple
from fastapi import HTTPException, status
from app.core.config import settings
from app.repositories.session_repository import session_repository, SessionRepository
from app.repositories.memory_repository import memory_repository, MemoryRepository
from app.services.ollama_service import ollama_service, OllamaService
from app.services.vector_service import vector_service, VectorService
from app.schemas.memory import (
    MessageItem,
    ChatResponse,
)

logger = logging.getLogger("uvicorn")


class OllamaHarness:
    """
    Andamiaje (Harness) para Ollama con gestión de memoria conversacional en MongoDB
    y memoria vectorial de documentos en LanceDB (con persistencia en MinIO).
    
    Flujo:
    1. Intercepta la petición con session_id y mensaje.
    2. Reconstruye el contexto recuperando el system_prompt, la memoria vectorial relevante en LanceDB
       y el historial cronológico de la colección 'memory'.
    3. Realiza la inferencia contra Ollama pasando toda la memoria acumulada.
    4. Persiste el mensaje del usuario y la respuesta del asistente en la colección 'memory'.
    """

    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        memory_repo: Optional[MemoryRepository] = None,
        ollama_svc: Optional[OllamaService] = None,
        vector_svc: Optional[VectorService] = None,
    ):
        self.session_repo = session_repo or session_repository
        self.memory_repo = memory_repo or memory_repository
        self.ollama_svc = ollama_svc or ollama_service
        self.vector_svc = vector_svc or vector_service

    async def build_context(
        self, session_id: str, new_user_message: str
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any], List[Dict[str, Any]]]:
        """
        Reconstruye el contexto completo de la conversación:
        - System prompt / contexto inicial de la sesión
        - Memoria vectorial semántica en LanceDB recuperada para la consulta
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

        # 1. Búsqueda de contexto en memoria vectorial de LanceDB
        vector_chunks = await self.vector_svc.search_context(
            session_id=session_id,
            query=new_user_message,
            top_k=settings.VECTOR_TOP_K,
        )

        rag_block = ""
        if vector_chunks:
            snippets = []
            for c in vector_chunks:
                source = c.get("file_path") or c.get("file_name", "documento")
                idx = c.get("chunk_index", 0)
                text = c.get("text", "")
                snippets.append(f"--- [Fuente: {source} | Chunk: {idx}] ---\n{text}")
            rag_block = (
                "\n\n[CONTEXTO DE DOCUMENTOS INDEXADOS EN MEMORIA VECTORIAL (LanceDB)]:\n"
                + "\n\n".join(snippets)
                + "\n[FIN DE CONTEXTO DE DOCUMENTOS]"
            )

        # 2. Contexto inicial / System Prompt (enriquecido con contexto vectorial si existe)
        system_prompt = session.get("system_prompt", "") or ""
        full_system_content = system_prompt.strip()

        if rag_block:
            if full_system_content:
                full_system_content = f"{full_system_content}\n\nUtiliza los siguientes documentos indexados como contexto para responder con precisión cuando sea pertinente:{rag_block}"
            else:
                full_system_content = f"Eres un asistente analítico. Utiliza el siguiente contexto indexado en tu memoria vectorial para fundamentar tus respuestas:{rag_block}"

        if full_system_content:
            messages_payload.append({
                "role": "system",
                "content": full_system_content,
            })

        # 3. Historial de mensajes previos ordenados cronológicamente
        history = await self.memory_repo.get_messages_by_session(session_id)
        for msg in history:
            messages_payload.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        # 4. Nuevo mensaje del usuario
        messages_payload.append({
            "role": "user",
            "content": new_user_message.strip(),
        })

        return messages_payload, session, vector_chunks

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
        messages_payload, session, vector_chunks = await self.build_context(session_id, content)

        # 2. Determinar modelo (override puntual -> modelo de sesión -> default global)
        target_model = model or session.get("model") or settings.MODEL_NAME

        # 3. Llamar a Ollama con la memoria reconstruida
        logger.info(
            f"Harness: Enviando {len(messages_payload)} mensajes para sesión '{session_id}' a modelo '{target_model}' (chunks vectoriales LanceDB: {len(vector_chunks)})"
        )
        ollama_result = await self.ollama_svc.chat(
            messages=messages_payload,
            model=target_model,
            temperature=temperature,
        )

        assistant_content = ollama_result.get("content", "")
        extra_metadata = ollama_result.get("metadata", {}) or {}
        if vector_chunks:
            extra_metadata["vector_chunks_used"] = len(vector_chunks)
            extra_metadata["vector_sources"] = list(
                set(c.get("file_path") or c.get("file_name", "") for c in vector_chunks)
            )

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
