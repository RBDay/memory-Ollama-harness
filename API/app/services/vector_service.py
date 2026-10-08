import os
import posixpath
import io
import uuid
import zipfile
import logging
from typing import List, Dict, Any, Tuple
import pyarrow as pa
import lancedb
from minio import Minio
from pypdf import PdfReader
from fastapi import HTTPException, status
from app.core.config import settings
from app.services.ollama_service import ollama_service

logger = logging.getLogger("uvicorn")


class VectorService:
    """
    Servicio de memoria vectorial persistente utilizando LanceDB con backend de almacenamiento MinIO (S3).
    Gestiona la ingesta de archivos (texto, código, PDFs, archivos comprimidos ZIP), generación de embeddings
    con Ollama, almacenamiento en LanceDB en MinIO, búsqueda semántica y exportación recursiva.
    """

    def __init__(self):
        # Limpiar el endpoint para el SDK de MinIO (requiere host:puerto sin scheme)
        endpoint_clean = (
            settings.MINIO_ENDPOINT.replace("http://", "")
            .replace("https://", "")
            .rstrip("/")
        )
        self.minio_endpoint = endpoint_clean
        self.minio_client = Minio(
            endpoint_clean,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket_name = settings.MINIO_BUCKET
        self.storage_options = {
            "aws_endpoint": f"http://{endpoint_clean}" if not settings.MINIO_SECURE else f"https://{endpoint_clean}",
            "aws_access_key_id": settings.MINIO_ACCESS_KEY,
            "aws_secret_access_key": settings.MINIO_SECRET_KEY,
            "aws_region": settings.MINIO_REGION,
            "allow_http": "true" if not settings.MINIO_SECURE else "false",
        }

    def ensure_bucket(self):
        """Garantiza que el bucket de MinIO para LanceDB exista."""
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)
                logger.info(f"Bucket '{self.bucket_name}' creado en MinIO con éxito.")
        except Exception as e:
            logger.error(f"Error al verificar/crear bucket '{self.bucket_name}' en MinIO: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo conectar con MinIO para preparar el almacenamiento vectorial.",
            ) from e

    @staticmethod
    def _safe_relative_path(file_path: str) -> str:
        """Normaliza una ruta subida y rechaza rutas absolutas o que salgan de su raíz."""
        normalized = posixpath.normpath((file_path or "").replace("\\", "/"))
        if normalized in ("", ".", "..") or normalized.startswith("../") or normalized.startswith("/"):
            raise HTTPException(
                status_code=422,
                detail=f"Ruta de archivo no válida: {file_path!r}",
            )
        return normalized

    def get_session_db_uri(self, session_id: str) -> str:
        """Retorna la URI S3 de LanceDB para la sesión."""
        return f"s3://{self.bucket_name}/sessions/{session_id}"

    def extract_text_from_file(self, filename: str, content: bytes) -> List[Tuple[str, str]]:
        """
        Extrae el contenido textual de un archivo o conjunto de archivos (si es ZIP).
        Retorna una lista de tuplas (ruta_relativa, texto).
        """
        lower_name = filename.lower()
        extracted: List[Tuple[str, str]] = []

        # Caso 1: Archivo ZIP (descomprimir y procesar de manera recursiva)
        if lower_name.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for zip_info in zf.infolist():
                        if zip_info.is_dir():
                            continue
                        try:
                            member_path = self._safe_relative_path(zip_info.filename)
                        except HTTPException:
                            logger.warning("Se omitió una ruta no válida dentro de '%s'.", filename)
                            continue
                        # Omitir archivos del sistema o metadatos
                        if member_path.startswith("__MACOSX/") or "/.git/" in member_path or member_path.startswith(".git/"):
                            continue
                        sub_content = zf.read(zip_info.filename)
                        sub_extracted = self.extract_text_from_file(member_path, sub_content)
                        extracted.extend(sub_extracted)
                return extracted
            except Exception as e:
                logger.warning(f"Error al descomprimir archivo ZIP '{filename}': {e}")
                return []

        # Caso 2: Archivo PDF
        if lower_name.endswith(".pdf"):
            try:
                reader = PdfReader(io.BytesIO(content))
                text_pages = []
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_pages.append(f"--- Página {i+1} ---\n{page_text}")
                full_text = "\n\n".join(text_pages)
                if full_text.strip():
                    extracted.append((filename, full_text))
                return extracted
            except Exception as e:
                logger.warning(f"Error al procesar PDF '{filename}': {e}")
                return []

        # Descartar archivos binarios no textuales conocidos (imágenes, medios, ejecutables, etc.)
        binary_extensions = (
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".tiff",
            ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
            ".tar", ".gz", ".bz2", ".7z", ".rar",
            ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin",
            ".woff", ".woff2", ".ttf", ".eot", ".otf",
            ".parquet", ".lance", ".db", ".sqlite",
        )
        if any(lower_name.endswith(ext) for ext in binary_extensions):
            return []

        # Comprobar presencia de bytes nulos (indicador clásico de archivo binario)
        if b"\x00" in content[:1024]:
            return []

        # Caso 3: Archivos de texto plano / código fuente
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except Exception:
                text = content.decode("utf-8", errors="replace")

        if text.strip():
            extracted.append((filename, text))

        return extracted

    def chunk_text(
        self,
        text: str,
        file_path: str,
        chunk_size: int = settings.CHUNK_SIZE,
        chunk_overlap: int = settings.CHUNK_OVERLAP,
    ) -> List[Dict[str, Any]]:
        """Divide un texto en fragmentos (chunks) con solapamiento."""
        file_name = os.path.basename(file_path)
        chunks = []
        start = 0
        text_len = len(text)
        chunk_idx = 0

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk_content = text[start:end].strip()

            if chunk_content:
                chunks.append({
                    "id": str(uuid.uuid4()),
                    "file_name": file_name,
                    "file_path": file_path,
                    "chunk_index": chunk_idx,
                    "text": chunk_content,
                })
                chunk_idx += 1

            if end == text_len:
                break
            start += max(1, chunk_size - chunk_overlap)

        return chunks

    def save_raw_files_to_minio(self, session_id: str, files: List[Tuple[str, bytes]]):
        """Guarda copias de los archivos originales en MinIO para permitir su exportación recursiva posterior."""
        self.ensure_bucket()
        for file_path, content in files:
            safe_path = self._safe_relative_path(file_path)

            # Si el archivo es un archivo comprimido ZIP, desempaquetar cada archivo y guardarlo con su ruta
            if safe_path.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        for zip_info in zf.infolist():
                            if zip_info.is_dir():
                                continue
                            try:
                                member_path = self._safe_relative_path(zip_info.filename)
                            except HTTPException:
                                continue
                            if member_path.startswith("__MACOSX/") or "/.git/" in member_path or member_path.startswith(".git/"):
                                continue
                            sub_content = zf.read(zip_info.filename)
                            obj_name = f"files/{session_id}/{member_path}"
                            self.minio_client.put_object(
                                bucket_name=self.bucket_name,
                                object_name=obj_name,
                                data=io.BytesIO(sub_content),
                                length=len(sub_content),
                            )
                    continue
                except Exception as e:
                    logger.warning(f"Error al descomprimir ZIP para almacenamiento individual en MinIO: {e}")

            # Archivo normal
            obj_name = f"files/{session_id}/{safe_path}"
            try:
                self.minio_client.put_object(
                    bucket_name=self.bucket_name,
                    object_name=obj_name,
                    data=io.BytesIO(content),
                    length=len(content),
                )
            except Exception as e:
                logger.error(f"Error al guardar archivo '{obj_name}' en MinIO: {e}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"No se pudo guardar el archivo '{safe_path}' en MinIO.",
                ) from e

    async def index_files_for_session(
        self,
        session_id: str,
        files: List[Tuple[str, bytes]],
        mode: str = "overwrite",
    ) -> Dict[str, Any]:
        """
        Procesa archivos, extrae texto recursivamente, genera embeddings con Ollama
        y almacena los vectores en LanceDB en MinIO.
        """
        self.ensure_bucket()

        files = [(self._safe_relative_path(path), content) for path, content in files]

        # 1. Guardar archivos crudos en MinIO para exportación
        self.save_raw_files_to_minio(session_id, files)

        # 2. Extraer texto recursivamente de todos los archivos
        all_text_files: List[Tuple[str, str]] = []
        for file_path, content in files:
            extracted = self.extract_text_from_file(file_path, content)
            all_text_files.extend(extracted)

        if not all_text_files:
            return {
                "session_id": session_id,
                "status": "warning",
                "message": "No se encontró texto extraíble en los archivos proporcionados.",
                "files_count": 0,
                "chunks_count": 0,
            }

        # 3. Fragmentar el texto en chunks
        all_chunks: List[Dict[str, Any]] = []
        for file_path, text in all_text_files:
            chunks = self.chunk_text(text, file_path)
            for c in chunks:
                c["session_id"] = session_id
            all_chunks.extend(chunks)

        if not all_chunks:
            return {
                "session_id": session_id,
                "status": "warning",
                "message": "El contenido de los archivos estaba vacío tras la fragmentación.",
                "files_count": len(all_text_files),
                "chunks_count": 0,
            }

        logger.info(
            f"LanceDB: Generando embeddings para {len(all_chunks)} chunks de {len(all_text_files)} archivos..."
        )

        # 4. Generar embeddings con Ollama
        chunk_texts = [c["text"] for c in all_chunks]
        embeddings = await ollama_service.get_embeddings_batch(chunk_texts)
        if len(embeddings) != len(all_chunks) or not embeddings or not embeddings[0]:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ollama no devolvió un embedding válido para cada fragmento.",
            )

        for c, emb in zip(all_chunks, embeddings):
            c["vector"] = emb

        sample_vector = embeddings[0]
        vector_dim = len(sample_vector)

        # 5. Guardar en LanceDB apuntando a MinIO
        uri = self.get_session_db_uri(session_id)
        db = lancedb.connect(uri, storage_options=self.storage_options)

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("session_id", pa.string()),
            pa.field("file_name", pa.string()),
            pa.field("file_path", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), vector_dim)),
        ])

        try:
            tbl = db.create_table("context", schema=schema, mode=mode)
            tbl.add(all_chunks)
        except Exception as e:
            logger.error(f"Error al escribir en tabla LanceDB en MinIO: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al persistir contexto en LanceDB: {str(e)}",
            )

        logger.info(
            f"LanceDB: Contexto indexado con éxito para sesión '{session_id}': "
            f"{len(all_text_files)} archivos, {len(all_chunks)} chunks."
        )

        indexed_files = list(set(c["file_path"] for c in all_chunks))
        return {
            "session_id": session_id,
            "status": "success",
            "files_count": len(all_text_files),
            "chunks_count": len(all_chunks),
            "indexed_files": indexed_files,
            "embedding_model": settings.EMBEDDING_MODEL,
            "vector_dimension": vector_dim,
        }

    async def search_context(
        self,
        session_id: str,
        query: str,
        top_k: int = settings.VECTOR_TOP_K,
    ) -> List[Dict[str, Any]]:
        """Realiza una búsqueda por similitud vectorial en la memoria LanceDB de la sesión."""
        if not query or not query.strip():
            return []

        uri = self.get_session_db_uri(session_id)
        try:
            db = lancedb.connect(uri, storage_options=self.storage_options)
            if "context" not in db.table_names():
                return []
            tbl = db.open_table("context")
        except Exception as e:
            logger.debug(f"No se encontró tabla LanceDB para sesión '{session_id}': {e}")
            return []

        # Obtener embedding de la consulta
        query_vector = await ollama_service.get_embedding(query)

        try:
            results = tbl.search(query_vector).limit(top_k).to_list()
            formatted = []
            for r in results:
                formatted.append({
                    "id": r.get("id"),
                    "file_name": r.get("file_name"),
                    "file_path": r.get("file_path"),
                    "chunk_index": r.get("chunk_index"),
                    "text": r.get("text"),
                    "score": float(r.get("_distance", 0.0)),
                })
            return formatted
        except Exception as e:
            logger.error(f"Error en búsqueda vectorial en LanceDB para sesión '{session_id}': {e}")
            return []

    def delete_session_vectors(self, session_id: str) -> Dict[str, Any]:
        """
        Elimina completamente el contexto vectorial generado por LanceDB y los archivos
        asociados a la sesión en el almacenamiento de MinIO.
        """
        self.ensure_bucket()
        deleted_count = 0

        # Eliminar objetos de LanceDB: sessions/{session_id}/
        prefix_lance = f"sessions/{session_id}/"
        try:
            objects = self.minio_client.list_objects(
                self.bucket_name, prefix=prefix_lance, recursive=True
            )
            for obj in objects:
                self.minio_client.remove_object(self.bucket_name, obj.object_name)
                deleted_count += 1
        except Exception as e:
            logger.warning(f"Error al eliminar vectores de LanceDB en MinIO ({prefix_lance}): {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se pudo eliminar el contexto LanceDB de MinIO.",
            ) from e

        # Eliminar archivos crudos guardados: files/{session_id}/
        prefix_files = f"files/{session_id}/"
        try:
            objects = self.minio_client.list_objects(
                self.bucket_name, prefix=prefix_files, recursive=True
            )
            for obj in objects:
                self.minio_client.remove_object(self.bucket_name, obj.object_name)
                deleted_count += 1
        except Exception as e:
            logger.warning(f"Error al eliminar archivos crudos en MinIO ({prefix_files}): {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se pudieron eliminar los archivos de sesión de MinIO.",
            ) from e

        logger.info(
            f"LanceDB: Memoria vectorial y archivos de sesión '{session_id}' eliminados de MinIO ({deleted_count} objetos eliminados)."
        )
        return {
            "session_id": session_id,
            "deleted_objects_count": deleted_count,
            "message": "Contexto vectorial LanceDB y archivos eliminados de MinIO con éxito.",
        }

    async def refresh_session_vectors(
        self,
        session_id: str,
        files: List[Tuple[str, bytes]],
    ) -> Dict[str, Any]:
        """
        Elimina el contexto anterior en LanceDB/MinIO y rehace el contexto vectorial
        con los nuevos archivos proporcionados.
        """
        # 1. Eliminar contexto anterior
        self.delete_session_vectors(session_id)

        # 2. Indexar nuevos archivos
        result = await self.index_files_for_session(session_id, files, mode="overwrite")
        result["refreshed"] = True
        return result

    def export_session_files_as_zip(self, session_id: str) -> Tuple[io.BytesIO, int]:
        """
        Exporta todos los archivos de una sesión almacenados en MinIO de forma recursiva
        empaquetados en un archivo comprimido ZIP.
        Retorna (buffer_zip, total_archivos).
        """
        self.ensure_bucket()
        prefix = f"files/{session_id}/"
        zip_buffer = io.BytesIO()
        file_count = 0

        try:
            objects = list(self.minio_client.list_objects(
                self.bucket_name, prefix=prefix, recursive=True
            ))

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for obj in objects:
                    response = self.minio_client.get_object(self.bucket_name, obj.object_name)
                    content = response.read()
                    response.close()
                    response.release_conn()

                    # Ruta relativa sin el prefijo files/{session_id}/
                    rel_path = obj.object_name[len(prefix):]
                    zf.writestr(rel_path, content)
                    file_count += 1

            zip_buffer.seek(0)
            return zip_buffer, file_count
        except Exception as e:
            logger.error(f"Error al exportar archivos de sesión '{session_id}' en ZIP: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al generar exportación de archivos: {str(e)}",
            )

    def list_session_files(self, session_id: str) -> List[Dict[str, Any]]:
        """Lista los archivos almacenados en MinIO para una sesión."""
        self.ensure_bucket()
        prefix = f"files/{session_id}/"
        files_info = []

        try:
            objects = self.minio_client.list_objects(
                self.bucket_name, prefix=prefix, recursive=True
            )
            for obj in objects:
                rel_path = obj.object_name[len(prefix):]
                files_info.append({
                    "file_path": rel_path,
                    "size_bytes": obj.size,
                    "last_modified": str(obj.last_modified),
                })
        except Exception as e:
            logger.warning(f"Error al listar archivos para sesión '{session_id}': {e}")

        return files_info


vector_service = VectorService()
