from typing import Optional
from fastapi import APIRouter, Path, Query
from app.harness import harness
from app.services.memory_service import memory_service
from app.schemas.memory import (
    ChatSessionRequest,
    ChatResponse,
    MemoryHistoryResponse,
    MemoryClearResponse,
)

router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Interacción de chat por session_id",
    description="Permite enviar un mensaje proveyendo session_id en el cuerpo de la petición. Reconstruye la memoria de la sesión desde MongoDB, consulta a Ollama y persiste el resultado.",
)
async def chat_with_memory(request: ChatSessionRequest):
    return await harness.execute_chat(
        session_id=request.session_id,
        content=request.content,
        model=request.model,
        temperature=request.temperature,
    )


@router.get(
    "/{session_id}",
    response_model=MemoryHistoryResponse,
    summary="Consultar memoria de una sesión",
    description="Obtiene el historial cronológico de la colección 'memory' para la sesión especificada.",
)
async def get_memory(
    session_id: str = Path(..., description="ID de la sesión"),
    limit: Optional[int] = Query(None, ge=1, description="Límite opcional de mensajes a recuperar"),
):
    return await memory_service.get_history(session_id, limit=limit)


@router.delete(
    "/{session_id}",
    response_model=MemoryClearResponse,
    summary="Vaciar memoria de una sesión",
    description="Elimina todos los mensajes registrados en la colección 'memory' para la sesión especificada.",
)
async def clear_memory(
    session_id: str = Path(..., description="ID de la sesión"),
):
    return await memory_service.clear_memory(session_id)
