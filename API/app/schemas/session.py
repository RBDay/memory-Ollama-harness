from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """Schema para crear una nueva sesión de conversación."""
    session_id: Optional[str] = Field(None, description="Identificador único opcional. Si no se provee, se genera un UUID.")
    title: Optional[str] = Field("Nueva Sesión", description="Título descriptivo de la sesión")
    system_prompt: Optional[str] = Field(None, description="Contexto inicial o instrucciones de sistema para esta sesión")
    model: Optional[str] = Field(None, description="Modelo Ollama a utilizar en esta sesión (ej. qwen2.5-coder:7b)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadatos adicionales")


class SessionUpdate(BaseModel):
    """Schema para actualizar una sesión existente."""
    title: Optional[str] = Field(None, description="Nuevo título de la sesión")
    system_prompt: Optional[str] = Field(None, description="Nuevo contexto de sistema para la sesión")
    model: Optional[str] = Field(None, description="Nuevo modelo asociado")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Metadatos a actualizar")


class SessionResponse(BaseModel):
    """Schema de respuesta para una sesión."""
    session_id: str
    title: str
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    """Schema de respuesta paginada para listar sesiones."""
    total: int
    sessions: List[SessionResponse]
