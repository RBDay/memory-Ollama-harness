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
        files: Optional[List[tuple]] = None,
    ) -> Dict[str, Any]:
        """Crea una nueva sesión, opcionalmente con archivos para memoria vectorial LanceDB."""
        if files:
            return self.create_session_with_files(
                title=title,
                files=files,
                system_prompt=system_prompt,
                model=model,
                session_id=session_id,
            )

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

    def create_session_with_files(
        self,
        title: str,
        files: List[tuple],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crea una nueva sesión indexando archivos/carpetas en LanceDB y MinIO."""
        data_dict: Dict[str, Any] = {"title": title, "relative_paths": []}
        if system_prompt:
            data_dict["system_prompt"] = system_prompt
        if model:
            data_dict["model"] = model
        if session_id:
            data_dict["session_id"] = session_id

        files_payload: List[tuple] = []
        for rel_path, content in files:
            data_dict["relative_paths"].append(rel_path)
            files_payload.append(
                ("files", (os.path.basename(rel_path) or "archivo", content, "application/octet-stream"))
            )

        with self._client() as client:
            resp = client.post("/sessions/", data=data_dict, files=files_payload)
            resp.raise_for_status()
            return resp.json()

    def refresh_session_files(
        self,
        session_id: str,
        files: List[tuple],
    ) -> Dict[str, Any]:
        """Reemplaza el contexto vectorial anterior en LanceDB y MinIO con nuevos archivos."""
        data_dict: Dict[str, Any] = {"relative_paths": []}
        files_payload: List[tuple] = []
        for rel_path, content in files:
            data_dict["relative_paths"].append(rel_path)
            files_payload.append(
                ("files", (os.path.basename(rel_path) or "archivo", content, "application/octet-stream"))
            )

        with self._client() as client:
            resp = client.put(f"/sessions/{session_id}/refresh", data=data_dict, files=files_payload)
            resp.raise_for_status()
            return resp.json()

    def list_session_files(self, session_id: str) -> Dict[str, Any]:
        """Lista todos los archivos almacenados en MinIO/LanceDB para una sesión."""
        with self._client() as client:
            resp = client.get(f"/sessions/{session_id}/files")
            resp.raise_for_status()
            return resp.json()

    def export_session_files(
        self,
        session_id: str,
        destination_path: Optional[str] = None,
    ) -> str:
        """Descarga todos los archivos de la sesión en un archivo ZIP recursivo."""
        output_file = destination_path or f"session-{session_id}-files.zip"
        with self._client() as client:
            resp = client.get(f"/sessions/{session_id}/export")
            resp.raise_for_status()
            with open(output_file, "wb") as f:
                f.write(resp.content)
        return output_file

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        """Elimina una sesión y toda su memoria (conversacional y vectorial)."""
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


def collect_files_from_paths(paths: List[str]) -> List[tuple]:
    """
    Escanea rutas de archivos y carpetas locales de forma recursiva.
    Retorna una lista de tuplas (ruta_relativa, contenido_bytes).
    Ignora carpetas de control de versiones y entornos virtuales.
    """
    collected: List[tuple] = []
    ignored_patterns = {".git", ".svn", ".hg", ".venv", "venv", ".idea", ".vscode", ".DS_Store"}
    allowed_dotfiles = {
        ".env", ".env.local", ".env.production", ".env.development", ".env.example",
        ".gitignore", ".dockerignore", ".editorconfig", ".eslintrc", ".prettierrc",
        ".babelrc", ".npmrc", ".yarnrc", ".mvn"
    }

    for p in paths:
        clean_p = p.strip().strip("'\"")
        abs_p = os.path.abspath(clean_p)
        if not os.path.exists(abs_p):
            raise FileNotFoundError(f"No se encontró la ruta: '{p}'")

        if os.path.isfile(abs_p):
            rel_name = os.path.basename(abs_p)
            with open(abs_p, "rb") as f:
                collected.append((rel_name, f.read()))
        elif os.path.isdir(abs_p):
            root_name = os.path.basename(abs_p) or "carpeta"
            for root, dirs, files in os.walk(abs_p):
                dirs[:] = [d for d in dirs if d not in ignored_patterns and not (d.startswith(".") and d != ".mvn")]
                for fname in files:
                    if fname in ignored_patterns:
                        continue
                    if fname.startswith(".") and fname not in allowed_dotfiles:
                        continue
                    full_file = os.path.join(root, fname)
                    rel_to_dir = os.path.relpath(full_file, abs_p).replace("\\", "/")
                    rel_path = f"{root_name}/{rel_to_dir}".lstrip("/")
                    with open(full_file, "rb") as f:
                        collected.append((rel_path, f.read()))

    return collected

