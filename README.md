# 🧠 Memory Ollama — Local LLM Harness con Memoria Persistente

Este repositorio proporciona un **Harness (Andamiaje)** local para modelos de lenguaje en **Ollama**, dotándolos de memoria conversacional persistente organizada por sesiones en **MongoDB** y una interfaz **CLI interactiva** lista para usar como comando global en tu terminal (`ollama_local_chat_memory`).

---

## ⚡ Despliegue Rápido desde Cero (Quickstart)

Sigue estos 3 sencillos pasos una vez hayas clonado este repositorio en tu máquina:

### Paso 1: Asegurarte de tener Ollama activo en tu equipo

1. Si aún no tienes Ollama instalado en tu sistema Linux:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. Descarga el modelo por defecto (`qwen2.5-coder:7b`) o el que prefieras:
   ```bash
   ollama pull qwen2.5-coder:7b
   ```
3. Verifica que el servicio esté corriendo:
   ```bash
   ollama list
   ```

---

### Paso 2: Levantar los servicios backend con Docker (en 1 comando)

No necesitas configurar bases de datos manualmente; Docker Compose levanta MongoDB y la API REST en segundo plano:

```bash
docker compose up -d
```

* **API REST:** Disponible en `http://localhost:8001` (Documentación interactiva en `http://localhost:8001/docs`)
* **MongoDB:** Corriendo en el puerto `27017`
* **Mongo Express (Panel Web opcional):** `http://localhost:8081`

---

### Paso 3: Instalar el CLI (Sin necesidad de entender Docker)

Para poder chatear directamente desde tu terminal y gestionar sesiones como lo harías con herramientas como `claude` o `gemini`, ejecuta el script de instalación automática incluido:

```bash
./install_cli.sh
```

> **¿Qué hace este instalador automáticamente?**
> * Crea un entorno virtual Python aislado en `CLI/.venv` (no ensucia las librerías de tu sistema operativo).
> * Instala las dependencias necesarias (`httpx`, `rich`).
> * Registra el comando global `ollama_local_chat_memory` en tu carpeta `~/.local/bin/`.

¡Listo! A partir de este momento puedes invocar el CLI desde cualquier carpeta de tu terminal.

---

## 💻 Uso del CLI: `ollama_local_chat_memory`

El CLI ha sido diseñado para ser intuitivo y ofrecer soporte visual avanzado con colores, tablas y formateo Markdown.

### 1. Menú Guiado Interactivo (Recomendado)
Si no recuerdas los comandos, simplemente ejecuta:
```bash
ollama_local_chat_memory
```
Se abrirá un menú con opciones numéricas para listar, crear, chatear y gestionar tus sesiones fácilmente.

---

### 2. Comandos Directos

#### 📋 Listar sesiones existentes
```bash
ollama_local_chat_memory list
```
Muestra una tabla con el identificador (`session_id`), título, modelo, número de mensajes guardados en memoria y el contexto inicial asignado.

#### ➕ Crear una nueva sesión con contexto propio
Puedes especificar un *System Prompt* o rol inicial que determine el comportamiento del asistente, y elegir el modelo que desees:
```bash
ollama_local_chat_memory create --title "Arquitecto Backend" --prompt "Eres un arquitecto senior especialista en Python, FastAPI y Docker. Responde siempre en español." --model "qwen2.5-coder:7b"
```
*(Si ejecutas solo `ollama_local_chat_memory create` o desde el menú interactivo, te preguntará el título, contexto y el **modelo de Ollama**, mostrando `qwen2.5-coder:7b` por defecto pero permitiéndote escribir cualquier otro modelo instalado en tu Ollama).*

#### 💬 Entrar al chat de una sesión (con carga de memoria previa)
```bash
ollama_local_chat_memory chat <id_de_sesion>
```
* **Contexto visual:** Al entrar, el CLI recupera y muestra en tu pantalla los **últimos 50 mensajes** de esa sesión en MongoDB para que recuerdes de qué estabas hablando.
* **Memoria total del LLM:** Ollama recibe todo el historial acumulado en la base de datos en cada llamada.
* **Comandos disponibles dentro del chat:**
  * `/clear`: Vacía los mensajes de la sesión en MongoDB (resetea la memoria manteniendo la sesión).
  * `/context`: Muestra el *System Prompt* / contexto inicial configurado.
  * `/help`: Muestra la lista de comandos disponibles.
  * `/exit` (o `exit`): Vuelve a la terminal.

#### 🗑️ Eliminar una sesión completa
```bash
ollama_local_chat_memory delete <id_de_sesion>
```
Elimina la sesión de MongoDB y borra en cascada toda su memoria asociada.

#### 🧹 Vaciar la memoria de una sesión
```bash
ollama_local_chat_memory clear <id_de_sesion>
```

---

## 📮 Pruebas con Postman

En la raíz del proyecto encontrarás el archivo:
👉 **[`postman_collection.json`](./postman_collection.json)**

Puedes importarlo directamente en Postman para probar todos los endpoints REST:
* **Health Check:** `GET /health`
* **Sesiones:** `GET`, `POST`, `PUT`, `DELETE` en `/api/v1/sessions/`
* **Chat con Memoria:** `POST /api/v1/sessions/{session_id}/chat`
* **Historial de Memoria:** `GET /api/v1/sessions/{session_id}/memory`

---

## 🏗️ Arquitectura y Estructura del Proyecto

```text
Memory_Ollama/
├── API/
│   ├── app/
│   │   ├── api/v1/          # Endpoints REST (sessions, memory) y routers FastAPI
│   │   ├── core/            # Configuración (pydantic-settings) y conexión a MongoDB (Motor)
│   │   ├── models/          # Modelos de datos para MongoDB
│   │   ├── repositories/    # Capa de acceso a datos (colecciones 'sessions' y 'memory')
│   │   ├── schemas/         # Esquemas de validación Pydantic
│   │   ├── services/        # Lógica de negocio y cliente HTTP hacia Ollama
│   │   ├── harness.py       # Orquestador del Harness (reconstruye contexto y persiste memoria)
│   │   └── main.py          # Aplicación FastAPI y ciclo de vida (lifespan)
│   ├── Dockerfile
│   └── requirements.txt
├── CLI/
│   ├── app/                 # Código fuente del CLI (cliente API, interfaz visual Rich)
│   ├── pyproject.toml       # Definición de empaquetado para 'ollama_local_chat_memory'
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml       # Orquestación de MongoDB, Mongo Express y API
├── install_cli.sh           # Script instalador global para la terminal local
├── postman_collection.json  # Colección exportable para Postman v2.1
├── MEMORY.md                # Memoria y detalles técnicos del proyecto
└── README.md                # Guía de despliegue y uso
```

---

## 🧠 ¿Cómo funciona la persistencia de memoria?

1. **Colección `sessions`:** Almacena los metadatos de la sesión, título, modelo asignado y su `system_prompt` (contexto inicial).
2. **Colección `memory`:** Cada interacción guarda de forma individual los mensajes del usuario y del asistente vinculados al `session_id`.
3. **El Harness:** Antes de consultar a Ollama, el Harness recupera el contexto inicial de la sesión más todo el historial cronológico de la colección `memory`, compone el array de mensajes para Ollama y, al recibir la respuesta, la persiste automáticamente en MongoDB.

## 🧠 ¿Quieres información detallada?
Consulta el archivo `MEMORY.md` para obtener una visión más profunda de cómo la persistencia de memoria está implementada en el proyecto.