import json
import os
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, File, Form, HTTPException, Request, status, Query, Path, UploadFile
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile as StarletteUploadFile
from app.services.session_service import session_service
from app.services.memory_service import memory_service
from app.services.vector_service import vector_service
from app.harness import harness
from app.schemas.session import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionListResponse,
    SessionVectorResponse,
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
    response_model=Union[SessionResponse, SessionVectorResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Crear una sesión e indexar archivos opcionales",
    description="Acepta JSON para crear una sesión o multipart/form-data con archivos (incluidas rutas relativas de carpeta) para crearla e indexar su contexto vectorial.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/SessionCreate"}
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "string"},
                            "title": {"type": "string"},
                            "system_prompt": {"type": "string"},
                            "model": {"type": "string"},
                            "metadata": {"type": "string", "description": "Objeto JSON opcional"},
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            },
                            "relative_paths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Rutas relativas opcionales en el mismo orden que files.",
                            },
                        },
                        "required": ["files"],
                    }
                },
            }
        }
    },
)
async def create_session(request: Request):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        uploads = [
            item for field in ("files", "file")
            for item in form.getlist(field)
            if isinstance(item, StarletteUploadFile)
        ]
        relative_paths = [str(path) for path in form.getlist("relative_paths")]
        files = await _read_uploaded_files(uploads, relative_paths or None)
        metadata: Dict[str, Any] = {}
        raw_metadata = form.get("metadata")
        if raw_metadata:
            try:
                metadata = json.loads(str(raw_metadata))
                if not isinstance(metadata, dict):
                    raise ValueError("metadata debe ser un objeto JSON")
            except (json.JSONDecodeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Metadata inválida: {exc}") from exc

        data = SessionCreate(
            session_id=form.get("session_id"),
            title=form.get("title") or "Nueva Sesión",
            system_prompt=form.get("system_prompt"),
            model=form.get("model"),
            metadata=metadata,
        )
        session, vector_context = await session_service.create_session_with_files(data, files)
        return SessionVectorResponse(session=session, vector_context=vector_context)

    try:
        data = SessionCreate.model_validate(await request.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="El cuerpo debe ser JSON válido o multipart/form-data con archivos.",
        ) from exc
    return await session_service.create_session(data)


async def _read_uploaded_files(
    uploads: List[UploadFile],
    relative_paths: Optional[List[str]] = None,
) -> List[tuple[str, bytes]]:
    if not uploads:
        raise HTTPException(status_code=422, detail="Debe proporcionar al menos un archivo en el campo 'files'.")
    if relative_paths is not None and len(relative_paths) != len(uploads):
        raise HTTPException(status_code=422, detail="Debe enviar una ruta relativa por cada archivo recibido.")

    files: List[tuple[str, bytes]] = []
    for index, upload in enumerate(uploads):
        source_name = relative_paths[index] if relative_paths is not None else upload.filename
        filename = (source_name or "").replace("\\", "/")
        normalized = os.path.normpath(filename).replace("\\", "/")
        if not filename or normalized in (".", "..") or normalized.startswith("../") or normalized.startswith("/"):
            raise HTTPException(status_code=422, detail=f"Ruta de archivo no válida: {filename!r}")
        files.append((normalized, await upload.read()))
        await upload.close()
    return files


@router.put(
    "/{session_id}/refresh",
    summary="Reemplazar el contexto vectorial de una sesión",
    description="Elimina el contexto anterior de LanceDB y los archivos de MinIO y lo reconstruye con los archivos recibidos.",
)
async def refresh_session_context(
    session_id: str = Path(..., description="ID de la sesión"),
    files: List[UploadFile] = File(..., description="Archivos a indexar; repetir este campo para varios archivos"),
    relative_paths: Optional[List[str]] = Form(None, description="Rutas relativas opcionales, una por archivo y en el mismo orden"),
):
    uploaded_files = await _read_uploaded_files(files, relative_paths)
    return await session_service.refresh_session_vectors(session_id, uploaded_files)


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


@router.get(
    "/{session_id}/files",
    summary="Listar archivos guardados de una sesión",
    description="Lista recursivamente los archivos originales almacenados en MinIO.",
)
async def list_session_files(session_id: str = Path(..., description="ID de la sesión")):
    await session_service.get_session(session_id)
    return {"session_id": session_id, "files": vector_service.list_session_files(session_id)}


@router.get(
    "/{session_id}/export",
    summary="Exportar archivos de una sesión",
    description="Descarga como ZIP todos los archivos almacenados para la sesión, conservando su estructura de carpetas.",
    response_class=StreamingResponse,
)
async def export_session_files(session_id: str = Path(..., description="ID de la sesión")):
    await session_service.get_session(session_id)
    archive, file_count = vector_service.export_session_files_as_zip(session_id)
    if file_count == 0:
        raise HTTPException(status_code=404, detail="La sesión no tiene archivos almacenados para exportar.")
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="session-{session_id}-files.zip"'},
    )


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
