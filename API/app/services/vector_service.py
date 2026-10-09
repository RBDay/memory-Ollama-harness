import os
import posixpath
import io
import uuid
import zipfile
import logging
import xml.etree.ElementTree as ET
import dis
import marshal
import struct
import re
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
        """Normaliza una ruta subida asegurando que sea relativa y segura."""
        clean = (file_path or "").replace("\\", "/").strip().lstrip("/")
        normalized = posixpath.normpath(clean)
        if normalized in ("", ".", "..") or normalized.startswith("../"):
            base = posixpath.basename(clean)
            if base and base not in (".", ".."):
                return base
            raise HTTPException(
                status_code=422,
                detail=f"Ruta de archivo no válida: {file_path!r}",
            )
        return normalized

    def get_session_db_uri(self, session_id: str) -> str:
        """Retorna la URI S3 de LanceDB para la sesión."""
        return f"s3://{self.bucket_name}/sessions/{session_id}"

    @staticmethod
    def _extract_java_class(content: bytes) -> str:
        """Extrae nombres de clases, métodos, firmas y cadenas de un archivo compilado .class de Java."""
        if not content.startswith(b"\xca\xfe\xba\xbe") or len(content) < 10:
            return ""
        try:
            cp_count = struct.unpack(">H", content[8:10])[0]
            pos = 10
            strings = []
            i = 1
            while i < cp_count and pos < len(content):
                tag = content[pos]
                pos += 1
                if tag == 1:  # CONSTANT_Utf8
                    length = struct.unpack(">H", content[pos : pos + 2])[0]
                    pos += 2
                    try:
                        s = content[pos : pos + length].decode("utf-8", errors="ignore")
                        if len(s) > 1 and any(c.isalnum() for c in s):
                            strings.append(s)
                    except Exception:
                        pass
                    pos += length
                elif tag in (3, 4):  # Integer, Float
                    pos += 4
                elif tag in (5, 6):  # Long, Double
                    pos += 8
                    i += 1
                elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
                    pos += 2
                elif tag in (9, 10, 11, 12, 18):  # Fieldref, Methodref, InterfaceMethodref, NameAndType, InvokeDynamic
                    pos += 4
                elif tag == 15:  # MethodHandle
                    pos += 3
                else:
                    break
                i += 1
            if strings:
                return f"[Símbolos y definiciones Java .class]:\n" + ", ".join(strings)
            return ""
        except Exception:
            return ""

    @staticmethod
    def _disassemble_pyc(filename: str, content: bytes) -> List[Tuple[str, str]]:
        """Desensambla bytecode de Python (.pyc/.pyo) y extrae cadenas, docstrings e instrucciones."""
        dis_text = ""
        const_strings = []
        for offset in (16, 12, 8):
            try:
                co = marshal.loads(content[offset:])
                out = io.StringIO()
                dis.dis(co, file=out)
                dis_text = out.getvalue()
                if hasattr(co, "co_consts"):
                    const_strings = [str(c) for c in co.co_consts if isinstance(c, (str, bytes)) and len(str(c).strip()) > 1]
                if dis_text:
                    break
            except Exception:
                continue

        if dis_text:
            parts = [f"--- Desensamblado Bytecode Python: {filename} ---", dis_text]
            if const_strings:
                parts.append("--- Constantes y Docstrings:\n" + "\n".join(const_strings[:50]))
            return [(filename, "\n\n".join(parts))]

        # Fallback si marshal falla: extraer cadenas legibles del binario
        matches = re.findall(rb"[a-zA-Z0-9_\.\-\:\/\(\)\s]{4,}", content)
        readable = " ".join(m.decode("latin-1", errors="ignore") for m in matches if len(m) > 3)
        if readable.strip():
            return [(filename, f"[Contenido legible extraído de pyc {filename}]:\n{readable}")]

        return []

    def extract_text_from_file(self, filename: str, content: bytes) -> List[Tuple[str, str]]:
        """
        Extrae el contenido textual de un archivo o conjunto de archivos (si es ZIP/JAR).
        Soporta archivos de programación (.php, .py, .js, .ts, .java, .c, .cpp, .cs, .go, .rs, .rb, etc.),
        bytecode (.pyc, .pyo, .class), empaquetados (.jar, .war, .zip), logs (.log), documentos Office y PDF.
        Retorna una lista de tuplas (ruta_relativa, texto).
        """
        lower_name = filename.lower()
        base_name = os.path.basename(lower_name)
        extracted: List[Tuple[str, str]] = []

        # Caso 1: Archivo ZIP o JAR/WAR/EAR (descomprimir y procesar de manera recursiva)
        if lower_name.endswith((".zip", ".jar", ".war", ".ear")):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for zip_info in zf.infolist():
                        if zip_info.is_dir():
                            continue
                        try:
                            member_path = self._safe_relative_path(zip_info.filename)
                        except HTTPException:
                            continue
                        # Omitir archivos del sistema o metadatos
                        if member_path.startswith("__MACOSX/") or "/.git/" in member_path or member_path.startswith(".git/"):
                            continue
                        sub_content = zf.read(zip_info.filename)
                        sub_extracted = self.extract_text_from_file(member_path, sub_content)
                        extracted.extend(sub_extracted)
                return extracted
            except Exception as e:
                logger.warning(f"Error al descomprimir archivo ZIP/JAR '{filename}': {e}")
                return []

        # Caso 2: Archivos compilados Python (.pyc, .pyo)
        if lower_name.endswith((".pyc", ".pyo")):
            return self._disassemble_pyc(filename, content)

        # Caso 3: Archivos compilados Java (.class)
        if lower_name.endswith(".class"):
            class_text = self._extract_java_class(content)
            if class_text:
                return [(filename, class_text)]
            return []

        # Caso 4: Documento Word (.docx)
        if lower_name.endswith(".docx"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    if "word/document.xml" in zf.namelist():
                        xml_content = zf.read("word/document.xml")
                        tree = ET.fromstring(xml_content)
                        paragraphs = []
                        for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                            texts = [
                                node.text
                                for node in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                                if node.text
                            ]
                            if texts:
                                paragraphs.append("".join(texts))
                        full_text = "\n\n".join(paragraphs)
                        if full_text.strip():
                            extracted.append((filename, full_text))
                return extracted
            except Exception as e:
                logger.warning(f"Error al procesar DOCX '{filename}': {e}")
                return []

        # Caso 5: Presentación PowerPoint (.pptx)
        if lower_name.endswith(".pptx"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    slide_files = sorted([
                        n for n in zf.namelist()
                        if n.startswith("ppt/slides/slide") and n.endswith(".xml")
                    ])
                    slides_text = []
                    for sf in slide_files:
                        tree = ET.fromstring(zf.read(sf))
                        texts = [
                            node.text
                            for node in tree.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
                            if node.text
                        ]
                        if texts:
                            slides_text.append(" ".join(texts))
                    if slides_text:
                        full_text = "\n\n".join(slides_text)
                        if full_text.strip():
                            extracted.append((filename, full_text))
                return extracted
            except Exception as e:
                logger.warning(f"Error al procesar PPTX '{filename}': {e}")
                return []

        # Caso 6: Hoja de cálculo Excel (.xlsx)
        if lower_name.endswith(".xlsx"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    if "xl/sharedStrings.xml" in zf.namelist():
                        tree = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                        texts = [
                            node.text
                            for node in tree.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                            if node.text
                        ]
                        if texts:
                            full_text = "\n".join(texts)
                            if full_text.strip():
                                extracted.append((filename, full_text))
                return extracted
            except Exception as e:
                logger.warning(f"Error al procesar XLSX '{filename}': {e}")
                return []

        # Caso 7: Archivo PDF
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

        # Caso 8: Archivos de código fuente conocidos, scripts, logs y formatos de configuración
        code_text_extensions = {
            # Python
            ".py", ".pyw", ".pyx", ".pxd", ".pxi", ".pyi", ".ipynb",
            # PHP
            ".php", ".phtml", ".php3", ".php4", ".php5", ".php7", ".phps",
            # JavaScript / TypeScript / Web
            ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx",
            ".vue", ".svelte", ".astro", ".html", ".htm", ".xhtml",
            ".css", ".scss", ".sass", ".less", ".styl", ".svg",
            # Java / JVM
            ".java", ".kt", ".kts", ".scala", ".sc", ".groovy", ".gvy", ".clj", ".cljs", ".cljc", ".edn",
            # C / C++ / Objective-C
            ".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx", ".c++", ".h++", ".inl", ".tpp", ".ipp",
            ".m", ".mm",
            # C# / .NET / F# / VB
            ".cs", ".csx", ".vb", ".vbs", ".fs", ".fsx", ".fsi", ".xaml", ".csproj", ".sln", ".vbproj", ".fsproj",
            # Go / Rust / Swift / Dart
            ".go", ".mod", ".sum", ".rs", ".rlib", ".swift", ".dart",
            # Ruby / Perl / Lua / R
            ".rb", ".rbw", ".rake", ".gemspec", ".pl", ".pm", ".t", ".lua", ".r", ".rmd",
            # Shell / Scripts
            ".sh", ".bash", ".zsh", ".fish", ".ksh", ".csh", ".tcsh", ".bat", ".cmd", ".ps1", ".psm1", ".psd1",
            # Datos / Serialización / Configuración
            ".json", ".json5", ".jsonc", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg", ".conf", ".config",
            ".env", ".properties", ".proto", ".avsc", ".thrift", ".csv", ".tsv",
            # SQL / Bases de datos
            ".sql", ".prisma", ".graphql", ".gql", ".cql", ".pgsql", ".plsql",
            # Logs y diagnósticos
            ".log", ".out", ".err", ".trace", ".diag",
            # Documentación y marcado
            ".md", ".markdown", ".rst", ".txt", ".tex", ".latex", ".asciidoc", ".adoc",
            # DevOps y Build
            ".dockerfile", ".dockerignore", ".gitignore", ".gitattributes", ".editorconfig",
            ".tf", ".tfvars", ".hcl", ".gradle", ".cmake"
        }

        code_text_filenames = {
            "dockerfile", "containerfile", "makefile", "gnumakefile",
            "cmakelists.txt", "gemfile", "rakefile", "vagrantfile",
            "procfile", "jenkinsfile", ".env", ".gitignore",
            ".dockerignore", ".editorconfig", ".npmrc", ".yarnrc",
            "composer.json", "composer.lock", "package.json", "package-lock.json"
        }

        is_known_code = any(lower_name.endswith(ext) for ext in code_text_extensions) or base_name in code_text_filenames

        # Descartar archivos binarios no textuales (medios, librerías nativas compiladas)
        binary_extensions = (
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".tiff",
            ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
            ".tar", ".gz", ".bz2", ".7z", ".rar",
            ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin",
            ".woff", ".woff2", ".ttf", ".eot", ".otf",
            ".parquet", ".lance", ".db", ".sqlite",
        )
        if not is_known_code and any(lower_name.endswith(ext) for ext in binary_extensions):
            return []

        # Si no es un archivo de código reconocido, verificar presencia de bytes nulos (indicador de binario genérico)
        if not is_known_code and b"\x00" in content[:1024]:
            return []

        # Caso 9: Decodificar texto plano / código fuente
        text = None
        for enc in ("utf-8", "latin-1", "utf-16"):
            try:
                decoded = content.decode(enc)
                if decoded.strip():
                    text = decoded
                    break
            except Exception:
                pass

        if not text and is_known_code:
            try:
                text = content.decode("utf-8", errors="replace")
            except Exception:
                text = ""

        if text and text.strip():
            extracted.append((filename, text))

        return extracted

    def chunk_text(
        self,
        text: str,
        file_path: str,
        chunk_size: int = settings.CHUNK_SIZE,
        chunk_overlap: int = settings.CHUNK_OVERLAP,
    ) -> List[Dict[str, Any]]:
        """Divide un texto en fragmentos (chunks) con solapamiento y metadatos de ruta."""
        file_name = os.path.basename(file_path)
        chunks = []
        start = 0
        text_len = len(text)
        chunk_idx = 0

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk_content = text[start:end].strip()

            if chunk_content:
                # Incluir la ruta del archivo explícitamente en el texto para enriquecer los embeddings y contexto
                enriched_text = f"[Archivo: {file_path}]\n{chunk_content}"
                chunks.append({
                    "id": str(uuid.uuid4()),
                    "file_name": file_name,
                    "file_path": file_path,
                    "chunk_index": chunk_idx,
                    "text": enriched_text,
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

            # Si el archivo es un archivo comprimido ZIP o JAR, desempaquetar cada archivo y guardarlo con su ruta
            if safe_path.lower().endswith((".zip", ".jar", ".war", ".ear")):
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
                            prefix_jar = "" if safe_path.lower().endswith(".zip") else f"{safe_path}_contents/"
                            obj_name = f"files/{session_id}/{prefix_jar}{member_path}"
                            self.minio_client.put_object(
                                bucket_name=self.bucket_name,
                                object_name=obj_name,
                                data=io.BytesIO(sub_content),
                                length=len(sub_content),
                            )
                    # Si es jar/war/ear, también guardar el archivo original para exportación
                    if not safe_path.lower().endswith(".zip"):
                        obj_name = f"files/{session_id}/{safe_path}"
                        self.minio_client.put_object(
                            bucket_name=self.bucket_name,
                            object_name=obj_name,
                            data=io.BytesIO(content),
                            length=len(content),
                        )
                    continue
                except Exception as e:
                    logger.warning(f"Error al desemprimir archivo ZIP/JAR para almacenamiento individual en MinIO: {e}")

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
