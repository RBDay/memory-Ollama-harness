from datetime import datetime
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field


MessageRole = Literal["system", "user", "assistant"]


class MessageItem(BaseModel):
    """Schema representativo de un mensaje almacenado en la colección memory."""
    message_id: str
    session_id: str
    role: MessageRole
    content: str
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """Schema para enviar un mensaje dentro de una sesión específica."""
    content: str = Field(..., description="Contenido del mensaje del usuario", min_length=1)
    model: Optional[str] = Field(None, description="Modelo Ollama a utilizar si se desea sobreescribir el de la sesión")
    temperature: Optional[float] = Field(None, description="Temperatura de generación (0.0 a 2.0)", ge=0.0, le=2.0)


class ChatSessionRequest(BaseModel):
    """Schema para enviar un mensaje proveyendo session_id en el cuerpo (endpoint /memory/chat)."""
    session_id: str = Field(..., description="Identificador de la sesión existente")
    content: str = Field(..., description="Contenido del mensaje del usuario", min_length=1)
    model: Optional[str] = Field(None, description="Modelo Ollama a utilizar si se desea sobreescribir el de la sesión")
    temperature: Optional[float] = Field(None, description="Temperatura de generación", ge=0.0, le=2.0)


class ChatResponse(BaseModel):
    """Schema de respuesta tras interactuar con Ollama."""
    session_id: str
    user_message: MessageItem
    assistant_message: MessageItem
    model: str
    total_messages_in_session: int


class MemoryHistoryResponse(BaseModel):
    """Schema para devolver el historial completo o paginado de una sesión."""
    session_id: str
    total: int
    messages: List[MessageItem]


class MemoryClearResponse(BaseModel):
    """Schema de respuesta tras vaciar la memoria de una sesión."""
    session_id: str
    deleted_count: int
    message: str
