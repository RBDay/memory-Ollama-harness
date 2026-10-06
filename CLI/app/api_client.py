import os
from typing import Optional, Dict, Any, List
import httpx

DEFAULT_API_URL = os.getenv("API_URL", "http://localhost:8001/api/v1").rstrip("/")


class APIClient:
    """Cliente HTTP síncrono para comunicarse con la API de Memory Ollama."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 180.0):
        self.base_url = (base_url or DEFAULT_API_URL).rstrip("/")
        # Si la url termina en /v1, derivar la url raíz para el healthcheck
        self.root_url = self.base_url[:-7] if self.base_url.endswith("/api/v1") else self.base_url
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def check_health(self) -> Dict[str, Any]:
        """Comprueba el estado general del backend y Ollama."""
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{self.root_url}/health")
            resp.raise_for_status()
            return resp.json()

    def list_sessions(self, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Obtiene la lista de sesiones."""
        with self._client() as client:
            resp = client.get("/sessions/", params={"skip": skip, "limit": limit})
            resp.raise_for_status()
            return resp.json()

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Obtiene una sesión específica."""
        with self._client() as client:
            resp = client.get(f"/sessions/{session_id}")
            resp.raise_for_status()
            return resp.json()

    def create_session(
        self,
        title: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crea una nueva sesión."""
        payload: Dict[str, Any] = {"title": title}
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if model:
            payload["model"] = model
        if session_id:
            payload["session_id"] = session_id

        with self._client() as client:
            resp = client.post("/sessions/", json=payload)
            resp.raise_for_status()
            return resp.json()

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        """Elimina una sesión y toda su memoria."""
        with self._client() as client:
            resp = client.delete(f"/sessions/{session_id}")
            resp.raise_for_status()
            return resp.json()

    def get_session_memory(self, session_id: str, limit: int = 50) -> Dict[str, Any]:
        """Obtiene el historial de memoria reciente de una sesión."""
        with self._client() as client:
            resp = client.get(f"/sessions/{session_id}/memory", params={"limit": limit})
            resp.raise_for_status()
            return resp.json()

    def clear_session_memory(self, session_id: str) -> Dict[str, Any]:
        """Vacia la memoria de una sesión manteniendo su configuración."""
        with self._client() as client:
            resp = client.delete(f"/sessions/{session_id}/memory")
            resp.raise_for_status()
            return resp.json()

    def chat(
        self,
        session_id: str,
        content: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Envía un mensaje para ser procesado por el Harness con memoria."""
        payload: Dict[str, Any] = {"content": content}
        if model:
            payload["model"] = model
        if temperature is not None:
            payload["temperature"] = temperature

        with self._client() as client:
            resp = client.post(f"/sessions/{session_id}/chat", json=payload)
            resp.raise_for_status()
            return resp.json()
