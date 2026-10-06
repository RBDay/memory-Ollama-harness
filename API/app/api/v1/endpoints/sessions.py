from typing import Optional
from fastapi import APIRouter, status, Query, Path
from app.services.session_service import session_service
from app.services.memory_service import memory_service
from app.harness import harness
from app.schemas.session import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionListResponse,
)
from app.schemas.memory import (
    ChatRequest,
    ChatResponse,
    MemoryHistoryResponse,
    MemoryClearResponse,
)

router = APIRouter()


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una nueva sesión",
    description="Crea una sesión en la colección 'sessions' con su propio contexto inicial (system_prompt).",
)
async def create_session(data: SessionCreate):
    return await session_service.create_session(data)


@router.get(
    "/",
    response_model=SessionListResponse,
    summary="Listar sesiones",
    description="Obtiene una lista paginada de todas las sesiones registradas en MongoDB.",
)
async def list_sessions(
    skip: int = Query(0, ge=0, description="Número de elementos a omitir"),
    limit: int = Query(50, ge=1, le=100, description="Número máximo de sesiones a retornar"),
):
    return await session_service.list_sessions(skip=skip, limit=limit)


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Obtener sesión por ID",
    description="Obtiene los datos de una sesión específica junto con el recuento de mensajes en memoria.",
)
async def get_session(
    session_id: str = Path(..., description="ID de la sesión"),
):
    return await session_service.get_session(session_id)


@router.put(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Actualizar contexto de sesión",
    description="Actualiza el contexto (system_prompt), título o modelo asignado a la sesión.",
)
async def update_session(
    session_id: str = Path(..., description="ID de la sesión"),
    data: SessionUpdate = ...,
):
    return await session_service.update_session(session_id, data)


@router.delete(
    "/{session_id}",
    summary="Eliminar sesión",
    description="Elimina la sesión de la colección 'sessions' y borra en cascada todos sus mensajes en 'memory'.",
)
async def delete_session(
    session_id: str = Path(..., description="ID de la sesión"),
):
    return await session_service.delete_session(session_id)


# Endpoints de interacción dentro de la sesión
@router.post(
    "/{session_id}/chat",
    response_model=ChatResponse,
    summary="Enviar mensaje con memoria en la sesión",
    description="Reconstruye el contexto previo de la sesión desde la colección 'memory', consulta a Ollama y persiste la nueva interacción.",
)
async def chat_in_session(
    session_id: str = Path(..., description="ID de la sesión"),
    request: ChatRequest = ...,
):
    return await harness.execute_chat(
        session_id=session_id,
        content=request.content,
        model=request.model,
        temperature=request.temperature,
    )


@router.get(
    "/{session_id}/memory",
    response_model=MemoryHistoryResponse,
    summary="Obtener memoria de la sesión",
    description="Devuelve el historial cronológico de mensajes almacenados en la colección 'memory' para esta sesión.",
)
async def get_session_memory(
    session_id: str = Path(..., description="ID de la sesión"),
    limit: Optional[int] = Query(None, ge=1, description="Límite opcional de mensajes a recuperar"),
):
    return await memory_service.get_history(session_id, limit=limit)


@router.delete(
    "/{session_id}/memory",
    response_model=MemoryClearResponse,
    summary="Vaciar memoria de la sesión",
    description="Elimina todos los mensajes de la colección 'memory' asociados a la sesión, conservando la configuración de la sesión.",
)
async def clear_session_memory(
    session_id: str = Path(..., description="ID de la sesión"),
):
    return await memory_service.clear_memory(session_id)
