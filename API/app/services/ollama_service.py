import asyncio
import logging
from typing import List, Dict, Any, Optional
import httpx
from fastapi import HTTPException, status
from app.core.config import settings

logger = logging.getLogger("uvicorn")


class OllamaService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.default_model = settings.MODEL_NAME
        self.timeout = settings.OLLAMA_TIMEOUT

    async def check_health(self) -> Dict[str, Any]:
        """Comprueba si el servicio Ollama está accesible."""
        # Determinar url raíz para consultar estado
        root_url = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{root_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {
                        "status": "healthy",
                        "available_models": [m.get("name") for m in models],
                    }
                return {"status": "unhealthy", "code": resp.status_code}
        except Exception as e:
            logger.warning(f"Ollama healthcheck failed: {e}")
            return {"status": "unavailable", "error": str(e)}

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Envía el historial estructurado de mensajes a Ollama y retorna la respuesta generada."""
        target_model = model or self.default_model
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        # Si OLLAMA_BASE_URL incluye /v1, usar OpenAI compatible endpoint
        if self.base_url.endswith("/v1"):
            url = f"{self.base_url}/chat/completions"
            is_openai_compat = True
        else:
            url = f"{self.base_url}/api/chat"
            is_openai_compat = False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)

                if response.status_code != 200:
                    # Intento alternativo en caso de desajuste de endpoint v1 vs api/chat
                    alt_url = (
                        f"{self.base_url[:-3]}/api/chat"
                        if is_openai_compat
                        else f"{self.base_url}/v1/chat/completions"
                    )
                    alt_resp = await client.post(alt_url, json=payload)
                    if alt_resp.status_code == 200:
                        response = alt_resp
                        is_openai_compat = not is_openai_compat
                    else:
                        logger.error(
                            f"Error de Ollama ({response.status_code}): {response.text}"
                        )
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Error en Ollama ({response.status_code}): {response.text}",
                        )

                data = response.json()

                if is_openai_compat:
                    choices = data.get("choices", [])
                    if not choices:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Respuesta vacía de Ollama",
                        )
                    content = choices[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    return {
                        "content": content,
                        "model": target_model,
                        "metadata": {"usage": usage, "finish_reason": choices[0].get("finish_reason")},
                    }
                else:
                    message = data.get("message", {})
                    content = message.get("content", "")
                    metadata = {
                        "eval_count": data.get("eval_count"),
                        "prompt_eval_count": data.get("prompt_eval_count"),
                        "total_duration": data.get("total_duration"),
                    }
                    return {
                        "content": content,
                        "model": target_model,
                        "metadata": metadata,
                    }

        except httpx.ConnectError as e:
            logger.error(f"No se pudo conectar a Ollama en {url}: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"No se pudo conectar al servicio Ollama en {self.base_url}. Asegúrate de que Ollama esté en ejecución.",
            )
        except httpx.TimeoutException:
            logger.error(f"Timeout al esperar respuesta de Ollama ({self.timeout}s)")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Tiempo de espera agotado al consultar a Ollama.",
            )

    async def _get_single_embedding(
        self,
        client: httpx.AsyncClient,
        text: str,
        target_model: str,
        root_url: str,
    ) -> List[float]:
        """Obtiene el embedding de un único texto con reintento."""
        url = f"{root_url}/api/embeddings"
        payload = {"model": target_model, "prompt": text}
        try:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                emb = data.get("embedding", [])
                if emb:
                    return emb
        except Exception as e:
            logger.debug(f"Fallo en api/embeddings: {e}")

        # Intento con api/embed
        alt_url = f"{root_url}/api/embed"
        alt_payload = {"model": target_model, "input": text}
        alt_resp = await client.post(alt_url, json=alt_payload)
        if alt_resp.status_code == 200:
            embeddings_list = alt_resp.json().get("embeddings", [])
            if embeddings_list:
                return embeddings_list[0]

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ollama retornó un vector de embedding vacío.",
        )

    async def get_embedding(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> List[float]:
        """Genera el vector de embedding para un fragmento de texto usando Ollama."""
        target_model = model or settings.EMBEDDING_MODEL
        root_url = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._get_single_embedding(client, text, target_model, root_url)
        except httpx.ConnectError as e:
            logger.error(f"No se pudo conectar a Ollama para embeddings: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"No se pudo conectar al servicio Ollama en {self.base_url}. Asegúrate de que el modelo '{target_model}' esté disponible.",
            ) from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout al esperar embedding de Ollama ({self.timeout}s)")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Tiempo de espera agotado al generar embedding en Ollama.",
            ) from e

    async def get_embeddings_batch(
        self,
        texts: List[str],
        model: Optional[str] = None,
        batch_size: int = 50,
        concurrency: int = 4,
    ) -> List[List[float]]:
        """
        Genera embeddings para una lista de textos de forma eficiente en lotes
        usando /api/embed de Ollama, con fallback concurrente.
        """
        if not texts:
            return []

        target_model = model or settings.EMBEDDING_MODEL
        root_url = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        embed_url = f"{root_url}/api/embed"

        # 1. Intentar procesamiento masivo por lotes vía /api/embed (altamente eficiente para ingesta masiva)
        try:
            results: List[List[float]] = []
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for i in range(0, len(texts), batch_size):
                    batch = texts[i : i + batch_size]
                    payload = {"model": target_model, "input": batch}
                    resp = await client.post(embed_url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        batch_embeddings = data.get("embeddings", [])
                        if len(batch_embeddings) == len(batch):
                            results.extend(batch_embeddings)
                            continue
                    raise ValueError(f"Batch embed status {resp.status_code}")
            return results
        except Exception as e:
            logger.info(f"Ollama batch /api/embed no disponible o falló ({e}), activando fallback concurrente.")

        # 2. Fallback concurrente con semáforo y cliente HTTP reutilizado
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async def _embed_one(t: str) -> List[float]:
                async with sem:
                    return await self._get_single_embedding(client, t, target_model, root_url)

            tasks = [_embed_one(text) for text in texts]
            return await asyncio.gather(*tasks)


ollama_service = OllamaService()
